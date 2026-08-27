import os
import re
import math
import datetime

import pandas as pd
from gurobipy import *
import numpy as np

# ==========================================
# GLOBAL CONSTANTS
# ==========================================
NUM_STEPS = 10          # points sampled along each Pareto curve
AUGMECON2_DELTA = 1e-3  # small slack-penalty weight, Mavrotas & Florios (2013);
                         # must be small relative to the primary objective's scale
                         # but not so small it underflows solver tolerance.
BALANCE_REL_TOL = 1e-6  # mass-balance audit tolerance (relative)
BALANCE_ABS_TOL = 1e-3  # mass-balance audit tolerance (absolute floor, kg/kWp)

# Reference module rating used throughout the thesis (Section 4.2.1: 435 Wp
# toom Baumarkt / JA Solar module) -- also the basis for omega_k (49.3 kg/kWp
# = 21.5 kg / 0.435 kWp). Needed to convert '10. Revenues' figures, which are
# priced per PHYSICAL MODULE (see fix_revenue_units below), into per-kWp terms.
MODULE_KWP = 0.435

# ==========================================
# SCENARIOS
# ==========================================
# recycling_available (default True): when False, solve_scenario_pareto
# forces R=[] for that scenario's solve regardless of what recycling
# facilities exist in the data -- i.e. recycling is not just economically
# unappealing, it is structurally removed as an option. Only consulted by
# solve_scenario_pareto (the production sweep); the validation/test
# functions call build_model directly and always see the full R, since
# those are testing the recycling mechanism itself, not a named scenario's
# policy intent.
#
# Why this flag exists: A ("linear baseline") was found to use recycling at
# up to 58.6% of collected material once the emissions cap tightened
# (verified in the solved output) -- silently contaminating what was meant
# to be a pure take-make-dispose reference point, since recycling (R) was
# structurally available to every scenario by default. A and C now force
# recycling off, so they represent what reuse/refurbishment policy ALONE
# can achieve.
#
# R_None / R_Bulk / R_HighValue form a controlled triplet: identical reuse
# (5%) and refurb yield (20%), varying only whether/which recycling exists.
# R_None -> R_Bulk isolates "does recycling help at all, at today's real
# technology" (a comparison A/C alone couldn't provide, since they differ
# from R_Bulk in reuse/refurb too, confounding any observed gap). R_Bulk ->
# R_HighValue isolates the technology choice specifically (this pairing was
# already verified to produce a real ~9.9% cost gap at Germany cost-min,
# unlike B/E2 at high refurb yield, where F1's 1,000,000 kWp/year capacity
# already absorbs 76.22% of collected material on its own -- capping
# recycling's addressable share at 3.78% and making any tech upgrade nearly
# invisible).
scenarios = {
    "A": {"name": "Linear_Like",           "reuse_limit": 0.10, "refurb_yield": 0.30, "tech_class_override": None, "recycling_available": False},
    "C": {"name": "Consumer_Reuse",         "reuse_limit": 0.60, "refurb_yield": 0.50, "tech_class_override": None, "recycling_available": False},
    "R_None": {"name": "Recycling_None",      "reuse_limit": 0.05, "refurb_yield": 0.20, "tech_class_override": None,       "recycling_available": False},
    "R_Bulk": {"name": "Recycling_Bulk",      "reuse_limit": 0.05, "refurb_yield": 0.20, "tech_class_override": "bulk",      "recycling_available": True},
    "R_HighValue": {"name": "Recycling_HighValue", "reuse_limit": 0.05, "refurb_yield": 0.20, "tech_class_override": "highvalue", "recycling_available": True},
}

COUNTRIES = {
    "Germany": {"file": "Germany_data_v3_extended.xlsx", "col": "Germany"},
    "India":   {"file": "India_data_v1_starter.xlsx",    "col": "India"},
}

ID_TOKEN_RE = re.compile(r"^[A-Za-z]{1,3}\d{1,3}$")


def log(msg):
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")


def get_set(df, col):
    return [x for x in df[col].dropna().unique()]


def material_short_name(name):
    """'Other (polymer/backsheet/EVA/junction box)' -> 'Other', 'Aluminium' -> 'Aluminium'."""
    return str(name).split(" (")[0].strip().replace(" ", "_")


# ==========================================
# 1.4 -- MANDATORY PRE-FLIGHT ID-CONSISTENCY CHECK
# ==========================================
def assert_id_consistency(xlsx_path):
    """
    Cross-check every ID declared in '1. Sets' against every ID actually
    referenced in the cost/capacity/transportation/BOM sheets. Raises (does
    not warn-and-continue) on any mismatch in either direction, and on any
    value in '1. Sets' that doesn't look like a short ID token (catches a
    real bug seen during data prep: '1. Sets' declaring "P1 (Mundra, GJ)"
    while every other sheet used plain "P1").
    """
    xls = pd.ExcelFile(xlsx_path)
    df_sets = pd.read_excel(xls, "1. Sets")
    id_cols = [
        "Plants (P)", "CustomerZones/Market (C)", "Collection Centers (O)",
        "Refurbish Centers (F)", "Landfills (L)", "Suppliers (S)",
        "Recycling Facilities (R)",
    ]

    declared = set()
    for col in id_cols:
        if col not in df_sets.columns:
            raise ValueError(f"[{xlsx_path}] '1. Sets' is missing expected column '{col}'")
        for v in df_sets[col].dropna():
            sv = str(v).strip()
            if not ID_TOKEN_RE.match(sv):
                raise ValueError(
                    f"[{xlsx_path}] '1. Sets' column '{col}' contains '{sv}', which does not "
                    f"look like a short ID token (expected e.g. 'P1', 'C12'). This is exactly "
                    f"the stray-legend-row failure mode: fix the sheet before proceeding."
                )
            declared.add(sv)

    referenced = set()

    def add_col(sheet, col):
        if sheet not in xls.sheet_names:
            return
        df = pd.read_excel(xls, sheet)
        if col in df.columns:
            referenced.update(str(v).strip() for v in df[col].dropna())

    add_col(" Prod", "Plant_ID")
    add_col("3. Operational Costs", "Facility_ID")
    add_col("4. Fixed Costs", "Facility_ID")
    add_col("9. Capacities", "Facility_ID")
    add_col("15. Recycling Facilities", "Facility_ID")
    add_col("6. Demand & Returns", "Customer_Zone_ID")
    add_col("13. Supplier_BOM", "Supplier_ID")
    add_col("11. Transportation", "Origin_ID")
    add_col("11. Transportation", "Destination_ID")

    missing_declared = referenced - declared
    if missing_declared:
        raise ValueError(
            f"[{xlsx_path}] IDs referenced in data sheets but never declared in '1. Sets': "
            f"{sorted(missing_declared)}"
        )

    unreferenced = declared - referenced
    if unreferenced:
        raise ValueError(
            f"[{xlsx_path}] IDs declared in '1. Sets' but never referenced anywhere else: "
            f"{sorted(unreferenced)} -- usually means a facility was added to Sets but its "
            f"cost/capacity/transport rows were forgotten."
        )

    log(f"    [OK] ID-consistency pre-flight passed for {xlsx_path} "
        f"({len(declared)} declared IDs, all cross-referenced).")


# ==========================================
# DATA LOADING (per country)
# ==========================================
def get_lever(df_levers, label_substr, country_col):
    """Returns (value, is_numeric) for a '16. Country Levers' row matched by substring."""
    row = df_levers[df_levers["Parameter"].str.contains(label_substr, case=False, na=False, regex=False)]
    if row.empty:
        raise KeyError(f"'16. Country Levers': no row matching '{label_substr}'")
    raw = row.iloc[0][country_col]
    try:
        return float(raw), True
    except (TypeError, ValueError):
        return raw, False


def load_country_data(xlsx_path, country_col):
    xls = pd.ExcelFile(xlsx_path)

    # ---- Sets ----
    df_sets = pd.read_excel(xls, "1. Sets")
    P = get_set(df_sets, "Plants (P)")
    C = get_set(df_sets, "CustomerZones/Market (C)")
    O = get_set(df_sets, "Collection Centers (O)")
    F = get_set(df_sets, "Refurbish Centers (F)")
    L = get_set(df_sets, "Landfills (L)")
    S = get_set(df_sets, "Suppliers (S)")
    R = get_set(df_sets, "Recycling Facilities (R)")

    df_w_raw = pd.read_excel(xls, "7. Module Weights")
    K = [x for x in df_w_raw["Module_Type_ID"].dropna().unique()]

    df_mat = pd.read_excel(xls, "14. Materials")
    M = [x for x in df_mat["Material"].dropna().unique()]

    # ---- Production costs (sheet is named ' Prod' with a leading space) ----
    sheet_prod = "2. Production Costs" if "2. Production Costs" in xls.sheet_names else "Prod"
    if "Prod" not in xls.sheet_names and "2. Production Costs" not in xls.sheet_names:
        possible = [s for s in xls.sheet_names if "Prod" in s]
        if possible:
            sheet_prod = possible[0]
    PC = pd.read_excel(xls, sheet_prod).set_index("Plant_ID")["Production_Cost_per_KWp (PC_p)"].to_dict()

    # ---- Operational / fixed / penalty costs ----
    ops_col = [c for c in pd.read_excel(xls, "3. Operational Costs").columns if c.startswith("Cost_per_Unit")][0]
    df_ops = pd.read_excel(xls, "3. Operational Costs").set_index("Facility_ID")[ops_col]
    CC = {o: df_ops.get(o, 0) for o in O}
    FC = {f: df_ops.get(f, 0) for f in F}
    DC = {l: df_ops.get(l, 0) for l in L}
    # Note: R1's row in this sheet is NOT used -- see RC/FixR sourcing below.
    # (Confirmed a real unit inconsistency between the two workbooks' R1 rows
    # in this sheet: Germany's is per-kWp, India's is per-kg, despite the
    # identical column header. Sheet 15 is the only sourced-from-one-place
    # reference for RC/FixR, per that sheet's own "Country note" cell.)

    df_fix = pd.read_excel(xls, "4. Fixed Costs").set_index("Facility_ID")["Fixed_Operational_Cost (Fix)"]
    FixO = {o: df_fix.get(o, 0) for o in O}
    FixF = {f: df_fix.get(f, 0) for f in F}

    Penalty = pd.read_excel(xls, "5. Penalty Costs").set_index("Module_Type_ID")["Penalty_Cost_per_KWp (Pen_k)"].to_dict()

    # ---- Demand & returns ----
    df_dem = pd.read_excel(xls, "6. Demand & Returns")
    DEM = {(r["Customer_Zone_ID"], r["Module_Type_ID"]): r["Demand_KWp (DEM_ck)"] for _, r in df_dem.iterrows()}
    RET = {(r["Customer_Zone_ID"], r["Module_Type_ID"]): r["Returns_KWp (RET_ck)"] for _, r in df_dem.iterrows()}

    df_w = pd.read_excel(xls, "7. Module Weights")
    omega = {r["Module_Type_ID"]: float(str(r["Weight_kg_per_KWp (omega_k)"]).replace(",", ".")) for _, r in df_w.iterrows()}

    # ---- Capacities (P/O/F kept in kWp as before; R1 read here too, kWp-equivalent) ----
    CAP_all = pd.read_excel(xls, "9. Capacities").set_index("Facility_ID")["Capacity_Value_kWp"].to_dict()
    CAP = {node: CAP_all[node] for node in list(P) + list(O) + list(F) if node in CAP_all}
    CAPR = {r: CAP_all[r] for r in R if r in CAP_all}
    # CAPR sourced from sheet 9 (kWp), not sheet 15's kg figure: sheet 9's R1
    # row was deliberately precomputed as the kWp-equivalent of sheet 15's kg
    # capacity, specifically so the recycling capacity constraint can stay in
    # kWp units like the existing P/O/F capacity constraints (no omega
    # conversion needed on that constraint).

    # ---- Revenues ----
    df_rev = pd.read_excel(xls, "10. Revenues")
    rev_col = [c for c in df_rev.columns if c.startswith("Revenue_per_Unit")][0]
    Rev_reuse = df_rev[df_rev["Revenue_Stream"] == "Reuse"].set_index("Item_ID")[rev_col].to_dict()
    Rev_refurb = df_rev[df_rev["Revenue_Stream"] == "Refurbish"].set_index("Item_ID")[rev_col].to_dict()

    # ---- Transportation ----
    df_trans = pd.read_excel(xls, "11. Transportation")
    dist_map = {(r["Origin_ID"], r["Destination_ID"]): r["Distance_km"] for _, r in df_trans.iterrows()}
    T_cost = df_trans["Cost_per_kg_km"].iloc[0]
    T_emit = df_trans["Emission_per_kg_km"].iloc[0]

    def DIST(a, b, strict=False):
        key = (a, b)
        if key in dist_map:
            return dist_map[key]
        if strict:
            raise ValueError(
                f"No transportation distance found for required recycling-echelon leg {key} "
                f"in {xlsx_path}. Refusing to silently fall back to a default distance here -- "
                f"that would corrupt every cost/emission number for this leg."
            )
        return 500

    # ---- Environmental (E_p/E_o/E_f/E_l/E_r are all already country-baked here) ----
    df_env = pd.read_excel(xls, "12. Environmental").set_index("Parameter_Name")["Value_kg_CO2e"]
    E_p = df_env.get("E_p", 580)
    E_co = df_env.get("E_o", 0.4)
    E_f = df_env.get("E_f", 1.2)
    E_l = df_env.get("E_l", 0.3)
    E_r = df_env.get("E_r", 8.0)
    # E_r (this sheet, per kWp) and sheet 15's ER_per_kg represent the same
    # physical recycling-process-emissions figure in two unit conventions.
    # Only E_r is re-derived per country here (India = Germany x1.2, same
    # convention as E_o/E_f/E_l); sheet 15's ER stays at the Germany value in
    # both workbooks and would be silently wrong for India if used directly.
    # E_r is therefore the sole recycling-emissions parameter used below.

    # ---- BOM (kept for bookkeeping; NOT used in either objective anymore -- see V_pm/U_pm) ----
    df_bom = pd.read_excel(xls, "13. Supplier_BOM")
    BOM = df_bom.set_index("Supplier_ID")["Qty_per_Module"].to_dict()
    Mat_Cost = df_bom.set_index("Supplier_ID")["Cost_per_Unit"].to_dict()
    Em_Supplier = df_bom.set_index("Supplier_ID")["Emission_per_kWp"].fillna(0).to_dict()

    # ---- Materials (global, same in both workbooks) ----
    df_mat_idx = df_mat.set_index("Material")
    mu = df_mat_idx["mu_kg_per_kWp (omega=49.3)"].to_dict()  # already pre-multiplied by omega_k -- do not re-multiply
    MCv = df_mat_idx["MCv_virgin_EUR_per_kg"].to_dict()
    MVs = df_mat_idx["MVs_secondary_EUR_per_kg"].to_dict()
    EMv = df_mat_idx["EMv_virgin_kgCO2e_per_kg"].to_dict()
    beta = df_mat_idx["beta_quality_substitution"].to_dict()
    rho_bulk = df_mat_idx["rho_bulk (mechanical, Reiling-type)"].to_dict()
    rho_highvalue = df_mat_idx["rho_highvalue (FRELP-type)"].to_dict()
    rho_by_tech = {"bulk": rho_bulk, "highvalue": rho_highvalue}

    # ---- Recycling Facilities (sheet 15 is a shared, deliberately-unscaled
    # Germany-baseline row in BOTH workbooks -- its own "Country note" cell
    # instructs computing India's numbers as this row x the country's
    # labour multiplier, which is what happens below) ----
    df_recyc = pd.read_excel(xls, "15. Recycling Facilities").set_index("Facility_ID")
    tech_class_raw = df_recyc["Tech_Class"].to_dict()
    RC_raw = df_recyc["RC_per_kg_EUR"].to_dict()
    FixR_raw = df_recyc["FixR_EUR"].to_dict()

    # ---- Country Levers ----
    df_levers = pd.read_excel(xls, "16. Country Levers")

    eta_val, eta_ok = get_lever(df_levers, "eta (formal", country_col)
    if not eta_ok:
        raise ValueError(f"[{xlsx_path}] eta (collection efficiency) is not numeric for column '{country_col}'")
    eta = eta_val

    labour_val, labour_ok = get_lever(df_levers, "Labour/handling cost multiplier", country_col)
    labour_mult = labour_val if labour_ok else 1.0

    eleak_val, eleak_ok = get_lever(df_levers, "E_leak", country_col)
    if eleak_ok:
        E_leak = eleak_val
    else:
        E_leak = 0.0
        log(f"    [Note] E_leak not numeric for column '{country_col}' (raw='{eleak_val}') -> treated as 0.0, "
            f"matching the modeler's own annotation that the leak term is negligible here.")

    RC = {r: RC_raw[r] * labour_mult for r in R}
    FixR = {r: FixR_raw[r] * labour_mult for r in R}

    return {
        "P": P, "C": C, "O": O, "F": F, "L": L, "S": S, "R": R, "K": K, "M": M,
        "PC": PC, "CC": CC, "FC": FC, "DC": DC, "FixO": FixO, "FixF": FixF,
        "Penalty": Penalty, "DEM": DEM, "RET": RET, "omega": omega,
        "CAP": CAP, "CAPR": CAPR, "Rev_reuse": Rev_reuse, "Rev_refurb": Rev_refurb,
        "DIST": DIST, "T_cost": T_cost, "T_emit": T_emit, "dist_map": dist_map,
        "E_p": E_p, "E_co": E_co, "E_f": E_f, "E_l": E_l, "E_r": E_r, "E_leak": E_leak, "eta": eta,
        "BOM": BOM, "Mat_Cost": Mat_Cost, "Em_Supplier": Em_Supplier,
        "mu": mu, "MCv": MCv, "MVs": MVs, "EMv": EMv, "beta": beta,
        "rho_by_tech": rho_by_tech, "tech_class_raw": tech_class_raw,
        "RC": RC, "FixR": FixR,
    }


# ==========================================
# 7.3 -- MASS-BALANCE AUDIT (run on every solved point)
# ==========================================
def mass_balance_audit(data, C, O, F, L, R, M, P, K, Y_cok, Y_ock, Y_ofk, Y_ork, Y_olk, Y_frk, Y_flk,
                        Q_rm, RES_r, V_pm, U_pm, X_pk):
    omega = data["omega"]
    mu = data["mu"]

    def close(a, b):
        return math.isclose(a, b, rel_tol=BALANCE_REL_TOL, abs_tol=BALANCE_ABS_TOL)

    # Constraint 3.2: collection center 4-way balance, recomputed independently.
    for o in O:
        for k in K:
            inflow = sum(Y_cok[c, o, k].X for c in C)
            outflow = (sum(Y_ock[o, c, k].X for c in C) + sum(Y_ofk[o, f, k].X for f in F)
                       + sum(Y_ork[o, r, k].X for r in R) + sum(Y_olk[o, l, k].X for l in L))
            if not close(inflow, outflow):
                raise AssertionError(f"[mass-balance audit] Collection center {o}, module {k}: "
                                      f"inflow={inflow} != outflow={outflow}")

    # Constraints 3.4 & 3.7 mutual consistency: recovered + residue == total inflow, per facility.
    for r in R:
        total_in = sum(omega[k] * (sum(Y_ork[o, r, k].X for o in O) + sum(Y_frk[f, r, k].X for f in F))
                        for k in K)
        recovered_plus_residue = sum(Q_rm[r, mm].X for mm in M) + RES_r[r].X
        if not close(total_in, recovered_plus_residue):
            raise AssertionError(f"[mass-balance audit] Recycling facility {r}: "
                                  f"total_in={total_in} != recovered+residue={recovered_plus_residue}")

    # Constraint 3.6: plant material balance, per plant and material.
    for p in P:
        for mm in M:
            lhs = V_pm[p, mm].X + U_pm[p, mm].X
            rhs = sum(mu[mm] * X_pk[p, k].X for k in K)
            if not close(lhs, rhs):
                raise AssertionError(f"[mass-balance audit] Plant {p}, material {mm}: "
                                      f"V+U={lhs} != embodied={rhs}")

    # System-level aggregate check (independent guard against an indexing bug
    # that cancels out per-plant but not in aggregate).
    for mm in M:
        total_V = sum(V_pm[p, mm].X for p in P)
        total_U = sum(U_pm[p, mm].X for p in P)
        total_embodied = sum(mu[mm] * X_pk[p, k].X for p in P for k in K)
        if not close(total_V + total_U, total_embodied):
            raise AssertionError(f"[mass-balance audit] System-level, material {mm}: "
                                  f"V+U={total_V + total_U} != embodied={total_embodied}")


# ==========================================
# MODEL BUILD + SOLVE FOR ONE (country, scenario)
# ==========================================
def build_model(data, scenario_data, price_materials=True,
                 fix_revenue_units=True, fix_landfill_emission_units=True,
                 fix_refurb_waste_leg=True):
    """
    price_materials=True (default, used for every production scenario run):
        the material-level V_pm/U_pm mechanism REPLACES the old component-level
        Mat_Cost[s]*Z_sp[s,p] cost term (and adds EMv[m]*V_pm to Expr_Env, which
        the old model never priced at all) -- see module-level notes on the
        replace-vs-coexist decision.
    price_materials=False (used ONLY by the Section 7.1 regression test):
        keeps the OLD Mat_Cost[s]*Z_sp[s,p] cost term and omits the new
        MCv/MVs/EMv-based terms entirely, so that turning R=[] and eta=1 is a
        true apples-to-apples isolation of constraints 3.1-3.3 against the
        pre-extension model -- the material-costing replacement is a real,
        deliberate modeling choice (changes absolute EUR numbers even when
        R=[], since virgin material is still purchased) and is NOT vacuous
        under R=[], so it must be excluded from that specific comparison.

    fix_revenue_units=True (default): '10. Revenues' prices reuse/refurbish
        modules per PHYSICAL MODULE (sourced from SecondSol.com EUR/Wp listings
        x the 435 Wp reference module -- confirmed by back-checking the cited
        0.08-0.2 EUR/Wp range against the stored 50/80 EUR figures), but
        Y_ock/Y_fpk are in kWp. The original model multiplied them directly,
        understating reuse/refurbish revenue by 1/MODULE_KWP (~2.3x). Fixed
        here by dividing through by MODULE_KWP. False reproduces the original
        (buggy) behavior -- used only by the regression test, since the old
        committed baseline CSVs were generated with the bug present.

    fix_landfill_emission_units=True (default): E_o/E_f/E_p are all applied
        per-kWp (no omega multiplication) and the source data sets E_l equal
        to E_o (both 5, described identically in the thesis prose as "~5 kg
        CO2e per kWp" for collection AND landfill) -- yet the original formula
        omega-multiplied ONLY E_l, making its effective per-kWp contribution
        ~49x larger than E_o's despite an identical source value and
        description. That magnitude (~246 kgCO2e/kWp) is also physically
        implausible for landfilling largely-inert module material (glass/
        aluminium/silicon don't decompose the way organic waste does, unlike
        DC's cost analog which genuinely is billed per-kg/tonne in reality).
        Fixed here by treating E_l per-kWp like E_o/E_f. For the new RES_r
        residue term (mass-only, no natural kWp equivalent), an effective
        per-kg rate is derived as E_l / omega[K[0]] -- exact for today's
        single-module-type data, would need re-deriving per module type if a
        second module type with a different weight is ever added. False
        reproduces the original per-kg-via-omega treatment for Y_olk/Y_flk
        (used only by the regression test).

    fix_refurb_waste_leg=True (default): the F1->L1 (refurb waste -> landfill)
        transport leg was hardcoded at 50km in the original model because
        that leg was simply missing from '11. Transportation'. It's now a
        real row in both workbooks (Germany: geography-consistent placeholder;
        India: set equal to the existing F1->O1 distance, since L1 is
        co-located with O1). True uses the real DIST() lookup. False keeps
        the original hardcoded 50km (used only by the regression test, since
        the old committed baseline CSVs were generated with that fallback).
    """
    P, C, O, F, L, S, R, K, M = (data[k] for k in ("P", "C", "O", "F", "L", "S", "R", "K", "M"))
    PC, CC, FC, DC = data["PC"], data["CC"], data["FC"], data["DC"]
    FixO, FixF, FixR = data["FixO"], data["FixF"], data["FixR"]
    Penalty, DEM, RET, omega = data["Penalty"], data["DEM"], data["RET"], data["omega"]
    CAP, CAPR = data["CAP"], data["CAPR"]
    Rev_reuse, Rev_refurb = data["Rev_reuse"], data["Rev_refurb"]
    DIST, T_cost, T_emit, dist_map = data["DIST"], data["T_cost"], data["T_emit"], data["dist_map"]
    E_p, E_co, E_f, E_l, E_r, E_leak, eta = (
        data["E_p"], data["E_co"], data["E_f"], data["E_l"], data["E_r"], data["E_leak"], data["eta"])
    BOM, Mat_Cost = data["BOM"], data["Mat_Cost"]
    mu, MCv, MVs, EMv, beta_q = data["mu"], data["MCv"], data["MVs"], data["EMv"], data["beta"]
    rho_by_tech, tech_class_raw, RC = data["rho_by_tech"], data["tech_class_raw"], data["RC"]

    reuse_lim = scenario_data["reuse_limit"]
    refurb_yld = scenario_data["refurb_yield"]
    tech_override = scenario_data.get("tech_class_override")
    alpha = {f: refurb_yld for f in F}

    def resolved_tech(r):
        if tech_override is not None:
            return tech_override
        return "highvalue" if "high" in str(tech_class_raw.get(r, "")).lower() else "bulk"

    rho = {(r, mm): rho_by_tech[resolved_tech(r)][mm] for r in R for mm in M}

    # Revenue unit fix: '10. Revenues' is priced per physical module, not per kWp.
    if fix_revenue_units:
        Rev_reuse_eff = {k: v / MODULE_KWP for k, v in Rev_reuse.items()}
        Rev_refurb_eff = {k: v / MODULE_KWP for k, v in Rev_refurb.items()}
    else:
        Rev_reuse_eff, Rev_refurb_eff = Rev_reuse, Rev_refurb

    # Landfill emissions unit fix: treat E_l per-kWp like E_o/E_f (no omega on
    # Y_olk/Y_flk); derive an effective per-kg rate for the mass-only RES_r term.
    if fix_landfill_emission_units:
        E_l_per_k = {k: E_l for k in K}
        E_l_residue_per_kg = E_l / omega[K[0]]
    else:
        E_l_per_k = {k: E_l * omega[k] for k in K}
        E_l_residue_per_kg = E_l

    m = Model("PV_Circular")
    m.setParam("OutputFlag", 0)

    # Variables
    X_pk = m.addVars(P, K, lb=0)
    X_pck = m.addVars(P, C, K, lb=0)
    Y_cok = m.addVars(C, O, K, lb=0)
    Y_ock = m.addVars(O, C, K, lb=0)
    Y_ofk = m.addVars(O, F, K, lb=0)
    Y_olk = m.addVars(O, L, K, lb=0)
    Y_ork = m.addVars(O, R, K, lb=0)
    Y_fpk = m.addVars(F, P, K, lb=0)
    Y_flk = m.addVars(F, L, K, lb=0)
    Y_frk = m.addVars(F, R, K, lb=0)
    S_ck = m.addVars(C, K, lb=0)
    W_o = m.addVars(O, vtype=GRB.BINARY)
    W_f = m.addVars(F, vtype=GRB.BINARY)
    W_r = m.addVars(R, vtype=GRB.BINARY)
    Z_sp = m.addVars(S, P, lb=0)          # kept for BOM bookkeeping only; not used in either objective (see 5)
    Q_rm = m.addVars(R, M, lb=0)
    U_pm = m.addVars(P, M, lb=0)
    V_pm = m.addVars(P, M, lb=0)
    G_m = m.addVars(M, lb=0)
    RES_r = m.addVars(R, lb=0)

    # ---- Constraints ----
    for p in P:
        for s in S:
            m.addConstr(Z_sp[s, p] == quicksum(X_pk[p, k] for k in K) * BOM[s])

    for c in C:
        for k in K:
            m.addConstr(quicksum(X_pck[p, c, k] for p in P) + quicksum(Y_ock[o, c, k] for o in O)
                        + S_ck[c, k] == DEM.get((c, k), 0))

    # 3.1 -- collection with formal-collection efficiency eta (replaces old returns balance)
    for c in C:
        for k in K:
            m.addConstr(quicksum(Y_cok[c, o, k] for o in O) == eta * RET.get((c, k), 0))

    for p in P:
        for k in K:
            m.addConstr(X_pk[p, k] + quicksum(Y_fpk[f, p, k] for f in F) == quicksum(X_pck[p, c, k] for c in C))

    # 3.2 -- collection center 4-way balance (replaces 3-way) + reuse limit
    for o in O:
        for k in K:
            In = quicksum(Y_cok[c, o, k] for c in C)
            Out = (quicksum(Y_ock[o, c, k] for c in C) + quicksum(Y_ofk[o, f, k] for f in F)
                   + quicksum(Y_ork[o, r, k] for r in R) + quicksum(Y_olk[o, l, k] for l in L))
            m.addConstr(In == Out)
            m.addConstr(quicksum(Y_ock[o, c, k] for c in C) <= reuse_lim * In)

    # Refurb yield success (unchanged) + 3.3 residue split (new: two destinations)
    for f in F:
        for k in K:
            In_Refurb = quicksum(Y_ofk[o, f, k] for o in O)
            m.addConstr(quicksum(Y_fpk[f, p, k] for p in P) == alpha[f] * In_Refurb)
            m.addConstr(quicksum(Y_frk[f, r, k] for r in R) + quicksum(Y_flk[f, l, k] for l in L)
                        == (1 - alpha[f]) * In_Refurb)

    # 3.4 -- material recovery
    for r in R:
        for mm in M:
            inflow_kg = (quicksum(mu[mm] * Y_ork[o, r, k] for o in O for k in K)
                         + quicksum(mu[mm] * Y_frk[f, r, k] for f in F for k in K))
            m.addConstr(Q_rm[r, mm] == rho[(r, mm)] * inflow_kg)

    # 3.5 -- disposition balance + quality cap (two separate constraints, bind at different times)
    for mm in M:
        m.addConstr(quicksum(U_pm[p, mm] for p in P) + G_m[mm] == quicksum(Q_rm[r, mm] for r in R))
        m.addConstr(quicksum(U_pm[p, mm] for p in P) <= beta_q[mm] * quicksum(Q_rm[r, mm] for r in R))

    # 3.6 -- plant material balance (THE sole recovery-credit mechanism)
    for p in P:
        for mm in M:
            m.addConstr(V_pm[p, mm] + U_pm[p, mm] == quicksum(mu[mm] * X_pk[p, k] for k in K))

    # 3.7 -- recycling residue
    for r in R:
        total_in = quicksum(omega[k] * (quicksum(Y_ork[o, r, k] for o in O)
                                         + quicksum(Y_frk[f, r, k] for f in F)) for k in K)
        m.addConstr(RES_r[r] == total_in - quicksum(Q_rm[r, mm] for mm in M))

    # Capacities, incl. 3.8 (kWp units throughout, matching P/O/F pattern)
    for p in P:
        m.addConstr(quicksum(X_pk[p, k] for k in K) <= CAP.get(p, 1e12))
    for o in O:
        m.addConstr(quicksum(Y_cok[c, o, k] for c in C for k in K) <= CAP.get(o, 1e12) * W_o[o])
    for f in F:
        m.addConstr(quicksum(Y_ofk[o, f, k] for o in O for k in K) <= CAP.get(f, 1e12) * W_f[f])
    for r in R:
        inflow_kwp = quicksum(quicksum(Y_ork[o, r, k] for o in O) + quicksum(Y_frk[f, r, k] for f in F)
                               for k in K)
        m.addConstr(inflow_kwp <= CAPR.get(r, 1e12) * W_r[r])

    # Recycling-facility -> landfill legs: only the pairs that actually exist
    # in the transportation data (avoids summing RES_r[r] against every (r,l)
    # combination, which would double/multi-count if more than one landfill
    # existed; current data has exactly one R1-L1 leg).
    recycle_landfill_pairs = [(r, l) for r in R for l in L if (r, l) in dist_map]
    if R and not recycle_landfill_pairs:
        raise ValueError("Recycling facilities exist but no R->L transportation leg was found; "
                          "residue would have no disposal route.")

    # ---- Objectives ----
    if price_materials:
        # Material-level costing REPLACES the old component-level Mat_Cost*Z_sp
        # term: M's "Other" bucket already absorbs the non-tracked-component
        # cost, so this is a clean replacement, not a coexistence -- avoids
        # double-counting Aluminium_Frame (BOM) vs Aluminium (Materials), etc.
        material_cost_term = (quicksum(MCv[mm] * V_pm[p, mm] for p in P for mm in M)
                               - quicksum(MVs[mm] * G_m[mm] for mm in M))
        material_env_term = quicksum(EMv[mm] * V_pm[p, mm] for p in P for mm in M)
    else:
        material_cost_term = quicksum(Mat_Cost[s] * Z_sp[s, p] for s in S for p in P)
        material_env_term = 0

    Expr_Cost = (
        quicksum(FixO[o] * W_o[o] for o in O) + quicksum(FixF[f] * W_f[f] for f in F)
        + quicksum(FixR[r] * W_r[r] for r in R)
        + quicksum(PC[p] * X_pk[p, k] for p in P for k in K)
        + quicksum(CC[o] * Y_cok[c, o, k] for c in C for o in O for k in K)
        + quicksum(FC[f] * Y_ofk[o, f, k] for o in O for f in F for k in K)
        + quicksum(DC[l] * Y_olk[o, l, k] * omega[k] for o in O for l in L for k in K)
        + quicksum(DC[l] * Y_flk[f, l, k] * omega[k] for f in F for l in L for k in K)
        # recycling processing cost: RC is per kg (sheet 15), mass = omega[k]*flow
        + quicksum(RC[r] * omega[k] * Y_ork[o, r, k] for o in O for r in R for k in K)
        + quicksum(RC[r] * omega[k] * Y_frk[f, r, k] for f in F for r in R for k in K)
        # transport, existing legs
        + quicksum(T_cost * DIST(p, c) * X_pck[p, c, k] * omega[k] for p in P for c in C for k in K)
        + quicksum(T_cost * DIST(c, o) * Y_cok[c, o, k] * omega[k] for c in C for o in O for k in K)
        + quicksum(T_cost * DIST(o, c) * Y_ock[o, c, k] * omega[k] for o in O for c in C for k in K)
        + quicksum(T_cost * DIST(o, f) * Y_ofk[o, f, k] * omega[k] for o in O for f in F for k in K)
        + quicksum(T_cost * DIST(o, l) * Y_olk[o, l, k] * omega[k] for o in O for l in L for k in K)
        # F1->L1 (refurb waste to landfill): real data-driven leg when fixed
        # (see '11. Transportation'), matching the other two landfill legs.
        + quicksum((DIST(f, l, strict=True) if fix_refurb_waste_leg else 50)
                   * T_cost * Y_flk[f, l, k] * omega[k] for f in F for l in L for k in K)
        + quicksum(T_cost * DIST(f, p) * Y_fpk[f, p, k] * omega[k] for f in F for p in P for k in K)
        # transport, new recycling-echelon legs (strict=True: no silent 500km fallback)
        + quicksum(T_cost * DIST(o, r, strict=True) * Y_ork[o, r, k] * omega[k] for o in O for r in R for k in K)
        + quicksum(T_cost * DIST(f, r, strict=True) * Y_frk[f, r, k] * omega[k] for f in F for r in R for k in K)
        + quicksum(T_cost * DIST(r, l, strict=True) * RES_r[r] for (r, l) in recycle_landfill_pairs)
        + quicksum(DC[l] * RES_r[r] for (r, l) in recycle_landfill_pairs)
        + quicksum(Penalty[k] * S_ck[c, k] for c in C for k in K)
        - (quicksum(Rev_reuse_eff.get(k, 0) * Y_ock[o, c, k] for o in O for c in C for k in K)
           + quicksum(Rev_refurb_eff.get(k, 0) * Y_fpk[f, p, k] for f in F for p in P for k in K))
        + material_cost_term
    )

    Expr_Env = (
        quicksum(E_p * X_pk[p, k] for p in P for k in K)
        + quicksum(E_co * Y_cok[c, o, k] for c in C for o in O for k in K)
        + quicksum(E_f * Y_ofk[o, f, k] for o in O for f in F for k in K)
        + quicksum(E_l_per_k[k] * Y_olk[o, l, k] for o in O for l in L for k in K)
        + quicksum(E_l_per_k[k] * Y_flk[f, l, k] for f in F for l in L for k in K)
        # recycling processing emissions: E_r is per kWp (sheet 12, already country-correct)
        + quicksum(E_r * Y_ork[o, r, k] for o in O for r in R for k in K)
        + quicksum(E_r * Y_frk[f, r, k] for f in F for r in R for k in K)
        + quicksum(T_emit * DIST(p, c) * X_pck[p, c, k] * omega[k] for p in P for c in C for k in K)
        + quicksum(T_emit * DIST(c, o) * Y_cok[c, o, k] * omega[k] for c in C for o in O for k in K)
        + quicksum(T_emit * DIST(o, c) * Y_ock[o, c, k] * omega[k] for o in O for c in C for k in K)
        + quicksum(T_emit * DIST(o, f) * Y_ofk[o, f, k] * omega[k] for o in O for f in F for k in K)
        + quicksum(T_emit * DIST(o, l) * Y_olk[o, l, k] * omega[k] for o in O for l in L for k in K)
        + quicksum((DIST(f, l, strict=True) if fix_refurb_waste_leg else 50)
                   * T_emit * Y_flk[f, l, k] * omega[k] for f in F for l in L for k in K)
        + quicksum(T_emit * DIST(f, p) * Y_fpk[f, p, k] * omega[k] for f in F for p in P for k in K)
        + quicksum(T_emit * DIST(o, r, strict=True) * Y_ork[o, r, k] * omega[k] for o in O for r in R for k in K)
        + quicksum(T_emit * DIST(f, r, strict=True) * Y_frk[f, r, k] * omega[k] for f in F for r in R for k in K)
        + quicksum(T_emit * DIST(r, l, strict=True) * RES_r[r] for (r, l) in recycle_landfill_pairs)
        + quicksum(E_l_residue_per_kg * RES_r[r] for (r, l) in recycle_landfill_pairs)
        + material_env_term
        + E_leak * (1 - eta) * quicksum(RET.get((c, k), 0) for c in C for k in K)
        # No credit term for U_pm or Q_rm anywhere in this expression -- the
        # avoided-burden credit is carried entirely by the reduced V_pm above.
    )

    handles = dict(
        X_pk=X_pk, X_pck=X_pck, Y_cok=Y_cok, Y_ock=Y_ock, Y_ofk=Y_ofk, Y_olk=Y_olk, Y_ork=Y_ork,
        Y_fpk=Y_fpk, Y_flk=Y_flk, Y_frk=Y_frk, S_ck=S_ck, W_o=W_o, W_f=W_f, W_r=W_r, Z_sp=Z_sp,
        Q_rm=Q_rm, U_pm=U_pm, V_pm=V_pm, G_m=G_m, RES_r=RES_r,
    )
    return m, Expr_Cost, Expr_Env, handles


def summarize_solution(data, handles):
    """Extended output columns: shares, per-material recovery/displacement, open facilities."""
    C, O, F, L, R, M, K = (data[k] for k in ("C", "O", "F", "L", "R", "M", "K"))
    Y_cok, Y_ock, Y_ofk, Y_ork, Y_olk = (handles[k] for k in ("Y_cok", "Y_ock", "Y_ofk", "Y_ork", "Y_olk"))
    Y_frk, Y_flk = handles["Y_frk"], handles["Y_flk"]
    Q_rm, U_pm, W_o, W_f, W_r = handles["Q_rm"], handles["U_pm"], handles["W_o"], handles["W_f"], handles["W_r"]

    total_in = sum(Y_cok[c, o, k].X for c in C for o in O for k in K)

    def share(expr_sum):
        return (expr_sum / total_in) if total_in > 1e-9 else 0.0

    reuse_share = share(sum(Y_ock[o, c, k].X for o in O for c in C for k in K))
    refurb_share = share(sum(Y_ofk[o, f, k].X for o in O for f in F for k in K))
    # Material reaches recycling/landfill via TWO routes each: direct from
    # collection (Y_ork/Y_olk) AND as refurbishment's own waste stream
    # (Y_frk/Y_flk, constraint 3.3). Both must be counted -- an earlier
    # version of this function only counted the direct route, silently
    # undercounting whenever refurbishment waste was the dominant path.
    recycle_share = share(sum(Y_ork[o, r, k].X for o in O for r in R for k in K)
                           + sum(Y_frk[f, r, k].X for f in F for r in R for k in K))
    landfill_share = share(sum(Y_olk[o, l, k].X for o in O for l in L for k in K)
                            + sum(Y_flk[f, l, k].X for f in F for l in L for k in K))

    out = {
        "reuse_share": reuse_share, "refurb_share": refurb_share,
        "recycle_share": recycle_share, "landfill_share": landfill_share,
    }
    for mm in M:
        short = material_short_name(mm)
        out[f"Q_rm_{short}"] = sum(Q_rm[r, mm].X for r in R)
        out[f"virgin_displaced_{short}"] = sum(U_pm[p, mm].X for p in data["P"])

    open_facilities = (
        [o for o in O if W_o[o].X > 0.5] + [f for f in F if W_f[f].X > 0.5] + [r for r in R if W_r[r].X > 0.5]
    )
    out["open_facilities"] = ",".join(open_facilities)
    return out


def run_augmecon2_sweep(m, expr_minimize, expr_cap, eps_values, range_span, cap_col, min_col, max_col, data, handles):
    """
    AUGMECON2: replace 'expr_cap <= eps' with an equality-with-slack and add
    a small penalty on the slack to the minimized objective, so the solver
    is nudged toward the most improving point on the current facet rather
    than an arbitrary alternative optimum. A fresh slack variable is added
    and removed each iteration -- it must never persist with a stale bound
    across iterations.
    """
    rows = []
    for eps in eps_values:
        s = m.addVar(lb=0, name="augmecon_slack")
        con = m.addConstr(expr_cap + s == eps)
        m.setObjective(expr_minimize - AUGMECON2_DELTA * (s / range_span), GRB.MINIMIZE)
        t0 = datetime.datetime.now()
        m.optimize()
        runtime_s = m.Runtime

        if m.Status == GRB.OPTIMAL:
            mass_balance_audit(data, data["C"], data["O"], data["F"], data["L"], data["R"], data["M"], data["P"],
                                data["K"], handles["Y_cok"], handles["Y_ock"], handles["Y_ofk"], handles["Y_ork"],
                                handles["Y_olk"], handles["Y_frk"], handles["Y_flk"], handles["Q_rm"],
                                handles["RES_r"], handles["V_pm"], handles["U_pm"], handles["X_pk"])
            row = {
                cap_col: eps,
                min_col: expr_minimize.getValue(),
                max_col: expr_cap.getValue(),
                "augmecon_slack": s.X,
                "mip_gap": m.MIPGap,
                "runtime_s": runtime_s,
            }
            row.update(summarize_solution(data, handles))
            rows.append(row)
        m.remove(con)
        m.remove(s)
        m.update()
    return rows


def solve_scenario_pareto(country_name, data, scenario_key, scenario_data, out_dir="outputs/pareto_csv",
                           price_materials=True, fix_revenue_units=True, fix_landfill_emission_units=True,
                           fix_refurb_waste_leg=True):
    os.makedirs(out_dir, exist_ok=True)
    s_name = scenario_data["name"]
    log(f"--- {country_name} / SCENARIO {scenario_key}: {s_name} ---")
    log(f"    Params: Reuse Limit={scenario_data['reuse_limit']*100}%, "
        f"Refurb Yield={scenario_data['refurb_yield']*100}%, "
        f"TechClassOverride={scenario_data.get('tech_class_override')}, "
        f"RecyclingAvailable={scenario_data.get('recycling_available', True)}")

    if not scenario_data.get("recycling_available", True):
        data = dict(data)
        data["R"] = []

    m, Expr_Cost, Expr_Env, handles = build_model(data, scenario_data, price_materials=price_materials,
                                                   fix_revenue_units=fix_revenue_units,
                                                   fix_landfill_emission_units=fix_landfill_emission_units,
                                                   fix_refurb_waste_leg=fix_refurb_waste_leg)

    # ---- Payoff table ----
    m.setObjective(Expr_Cost, GRB.MINIMIZE)
    m.optimize()
    if m.Status != GRB.OPTIMAL:
        log(f"  [Error] Infeasible model for {country_name}/{s_name} (Cost Min)")
        return
    mass_balance_audit(data, data["C"], data["O"], data["F"], data["L"], data["R"], data["M"], data["P"], data["K"],
                        handles["Y_cok"], handles["Y_ock"], handles["Y_ofk"], handles["Y_ork"], handles["Y_olk"],
                        handles["Y_frk"], handles["Y_flk"], handles["Q_rm"], handles["RES_r"], handles["V_pm"],
                        handles["U_pm"], handles["X_pk"])
    Zcost_min = m.ObjVal
    Zenv_at_costmin = Expr_Env.getValue()

    m.setObjective(Expr_Env, GRB.MINIMIZE)
    m.optimize()
    if m.Status != GRB.OPTIMAL:
        log(f"  [Error] Infeasible model for {country_name}/{s_name} (Env Min)")
        return
    mass_balance_audit(data, data["C"], data["O"], data["F"], data["L"], data["R"], data["M"], data["P"], data["K"],
                        handles["Y_cok"], handles["Y_ock"], handles["Y_ofk"], handles["Y_ork"], handles["Y_olk"],
                        handles["Y_frk"], handles["Y_flk"], handles["Q_rm"], handles["RES_r"], handles["V_pm"],
                        handles["U_pm"], handles["X_pk"])
    Zenv_min = m.ObjVal
    Zcost_at_envmin = Expr_Cost.getValue()

    log(f"    Payoff Table: Cost Range=[{Zcost_min:,.0f}, {Zcost_at_envmin:,.0f}]")
    log(f"                  Env Range =[{Zenv_min:,.0f}, {Zenv_at_costmin:,.0f}]")

    env_range = max(Zenv_at_costmin - Zenv_min, 1e-9)
    cost_range = max(Zcost_at_envmin - Zcost_min, 1e-9)

    # ---- Curve A: cap Env, minimize Cost (AUGMECON2) ----
    eps_env_values = np.linspace(Zenv_min, Zenv_at_costmin, NUM_STEPS)
    rows_A = run_augmecon2_sweep(m, Expr_Cost, Expr_Env, eps_env_values, env_range,
                                  "epsilon_env", "cost", "env", data, handles)
    df_A = pd.DataFrame(rows_A)
    file_A = f"{out_dir}/Pareto_{country_name}_{s_name}_CostMin.csv"
    df_A.to_csv(file_A, index=False)
    log(f"    Saved Curve A to {file_A}")

    # ---- Curve B: cap Cost, minimize Env (AUGMECON2) ----
    eps_cost_values = np.linspace(Zcost_min, Zcost_at_envmin, NUM_STEPS)
    rows_B = run_augmecon2_sweep(m, Expr_Env, Expr_Cost, eps_cost_values, cost_range,
                                  "epsilon_cost", "env", "cost", data, handles)
    df_B = pd.DataFrame(rows_B)
    file_B = f"{out_dir}/Pareto_{country_name}_{s_name}_EnvMin.csv"
    df_B.to_csv(file_B, index=False)
    log(f"    Saved Curve B to {file_B}")

    return {"Zcost_min": Zcost_min, "Zenv_at_costmin": Zenv_at_costmin,
            "Zenv_min": Zenv_min, "Zcost_at_envmin": Zcost_at_envmin,
            "df_A": df_A, "df_B": df_B}


# ==========================================
# 7.1 -- REGRESSION TEST (R=[], eta=1.0 must reproduce the pre-extension model)
# ==========================================
def run_regression_test():
    log("=== 7.1 REGRESSION TEST: R=[], eta=1.0 on Germany scenario A vs. pre-extension CSVs ===")
    data = load_country_data(COUNTRIES["Germany"]["file"], COUNTRIES["Germany"]["col"])
    data = dict(data)
    data["R"] = []
    data["eta"] = 1.0

    result = solve_scenario_pareto("RegressionTest", data, "A", scenarios["A"],
                                    price_materials=False, fix_revenue_units=False,
                                    fix_landfill_emission_units=False, fix_refurb_waste_leg=False)
    if result is None:
        raise AssertionError("Regression test model was infeasible -- cannot validate.")

    baseline_A = pd.read_csv("outputs/pareto_csv/Pareto_Linear_Like_CostMin.csv")
    baseline_B = pd.read_csv("outputs/pareto_csv/Pareto_Linear_Like_EnvMin.csv")

    def compare(new_df, old_df, cost_col, env_col, label):
        n = min(len(new_df), len(old_df))
        max_rel_diff = 0.0
        for i in range(n):
            for col in (cost_col, env_col):
                new_v, old_v = new_df.iloc[i][col], old_df.iloc[i][col]
                if old_v != 0:
                    rel = abs(new_v - old_v) / abs(old_v)
                    max_rel_diff = max(max_rel_diff, rel)
        log(f"    {label}: max relative diff over {n} matched rows = {max_rel_diff:.2e}")
        if max_rel_diff > 1e-6:
            raise AssertionError(f"Regression test FAILED on {label}: max relative diff {max_rel_diff:.2e} > 1e-6")

    compare(result["df_A"], baseline_A, "cost", "env", "Curve A (CostMin)")
    compare(result["df_B"], baseline_B, "cost", "env", "Curve B (EnvMin)")
    log("    [PASS] Regression test: extended model with R=[], eta=1.0 reproduces pre-extension results.")


# ==========================================
# 7.2 -- EXTREME-VALUE TESTS
# ==========================================
def run_extreme_value_tests():
    log("=== 7.2 EXTREME-VALUE TESTS (Germany) ===")
    base_data = load_country_data(COUNTRIES["Germany"]["file"], COUNTRIES["Germany"]["col"])

    # --- eta = 0: network must collapse to forward-only production, still feasible ---
    data = dict(base_data)
    data["eta"] = 0.0
    m, Expr_Cost, Expr_Env, handles = build_model(data, scenarios["C"])
    m.setObjective(Expr_Cost, GRB.MINIMIZE)
    m.optimize()
    if m.Status != GRB.OPTIMAL:
        raise AssertionError("eta=0 test: model infeasible, expected a forward-only feasible solution.")
    for c in data["C"]:
        for k in data["K"]:
            assert abs(sum(handles["Y_cok"][c, o, k].X for o in data["O"])) < 1e-6, \
                "eta=0 test: expected zero collection, found nonzero Y_cok."
    hand_cost = sum(data["PC"][p] * sum(handles["X_pk"][p, k].X for k in data["K"]) for p in data["P"])
    hand_cost += sum(data["T_cost"] * data["DIST"](p, c) * handles["X_pck"][p, c, k].X * data["omega"][k]
                      for p in data["P"] for c in data["C"] for k in data["K"])
    hand_cost += sum(data["Penalty"][k] * handles["S_ck"][c, k].X for c in data["C"] for k in data["K"])
    # With eta=0, no material is ever collected (Q_rm=U_pm=0), so V_pm = mu*X_pk
    # in full -- the material-level virgin-purchase cost (price_materials=True,
    # the default used here) must be included in the hand-computed baseline too.
    hand_cost += sum(data["MCv"][mm] * data["mu"][mm] * handles["X_pk"][p, k].X
                      for p in data["P"] for mm in data["M"] for k in data["K"])
    solver_cost = m.ObjVal
    log(f"    eta=0: solver cost={solver_cost:,.2f}, hand-computed forward-only cost={hand_cost:,.2f}")
    if not math.isclose(solver_cost, hand_cost, rel_tol=1e-6, abs_tol=1.0):
        raise AssertionError(f"eta=0 test FAILED: solver cost {solver_cost} != hand-computed {hand_cost}")
    log("    [PASS] eta=0 collapses to forward-only production, matches hand-computed baseline.")

    # --- rho = 0 for all materials at R1: recycling must never be selected under cost-min ---
    # Uses R_Bulk, which normally has HIGH recycling usage (77.3% recycle_share) --
    # a much stronger test than a scenario where recycling barely gets used anyway.
    data = dict(base_data)
    data["rho_by_tech"] = {"bulk": {mm: 0.0 for mm in data["M"]}, "highvalue": {mm: 0.0 for mm in data["M"]}}
    m, Expr_Cost, Expr_Env, handles = build_model(data, scenarios["R_Bulk"])
    m.setObjective(Expr_Cost, GRB.MINIMIZE)
    m.optimize()
    if m.Status != GRB.OPTIMAL:
        raise AssertionError("rho=0 test: model infeasible.")
    open_r = [r for r in data["R"] if handles["W_r"][r].X > 0.5]
    log(f"    rho=0: open recycling facilities under cost-min = {open_r}")
    if open_r:
        raise AssertionError(f"rho=0 test FAILED: recycling facility opened ({open_r}) despite zero recovery rate "
                              f"(fixed+processing+disposal cost with no offsetting material value).")
    log("    [PASS] rho=0 => recycling never selected under cost minimization.")

    # --- MVs very large for one material: recycling should become attractive at a lower eps ---
    data_base = dict(base_data)
    data_high = dict(base_data)
    data_high["MVs"] = dict(base_data["MVs"])
    data_high["MVs"]["Aluminium"] = 1e6  # deliberately huge secondary-material value

    def env_at_which_recycling_opens(data_variant):
        # Uses C, which normally has recycle_share=0.0 everywhere -- a clean
        # before/after signal for whether the incentive channel is connected.
        m, Expr_Cost, Expr_Env, handles = build_model(data_variant, scenarios["C"])
        m.setObjective(Expr_Env, GRB.MINIMIZE)
        m.optimize()
        Zenv_min = m.ObjVal
        m.setObjective(Expr_Cost, GRB.MINIMIZE)
        m.optimize()
        Zenv_at_costmin = Expr_Env.getValue()
        for eps in np.linspace(Zenv_min, Zenv_at_costmin, NUM_STEPS):
            con = m.addConstr(Expr_Env <= eps)
            m.setObjective(Expr_Cost, GRB.MINIMIZE)
            m.optimize()
            opened = m.Status == GRB.OPTIMAL and any(handles["W_r"][r].X > 0.5 for r in data_variant["R"])
            m.remove(con)
            m.update()
            if opened:
                return eps
        return None

    eps_base = env_at_which_recycling_opens(data_base)
    eps_high = env_at_which_recycling_opens(data_high)
    log(f"    MVs baseline: recycling first opens (scanning tightest->loosest eps) at eps_env={eps_base}")
    log(f"    MVs x1e6 for Aluminium: recycling first opens at eps_env={eps_high}")
    # "Sooner" means at a STRICTER (lower) emissions cap than baseline: once
    # recycling is highly profitable, the cost-minimizer keeps it open even
    # under tighter environmental targets it wasn't worth using for before --
    # i.e. eps_high should be <= eps_base, not >=.
    base_ok = eps_base is None or eps_high is None or eps_high <= eps_base
    if not base_ok:
        raise AssertionError("MVs test FAILED: higher secondary material value did not make recycling open "
                              "under a stricter emissions cap than baseline.")
    log("    [PASS] Large MVs makes recycling economically attractive under a stricter emissions cap than "
        "baseline -- the economic incentive channel from Section 3.5/3.6 into the objective is connected.")


# ==========================================
# 7.4 -- ONE HAND-COMPUTED INSTANCE (manual trace, printed for review)
# ==========================================
def run_hand_check():
    log("=== 7.4 HAND-CHECK: trace kWp->kg, recovery, and plant material balance by hand ===")
    data = load_country_data(COUNTRIES["Germany"]["file"], COUNTRIES["Germany"]["col"])
    # R_Bulk: chosen because it has substantial recycling flow (77.3%
    # recycle_share) to trace, unlike scenarios where recycling is a thin
    # sliver or unused entirely.
    m, Expr_Cost, Expr_Env, handles = build_model(data, scenarios["R_Bulk"])
    m.setObjective(Expr_Cost, GRB.MINIMIZE)
    m.optimize()
    if m.Status != GRB.OPTIMAL:
        raise AssertionError("Hand-check model infeasible.")

    R, O, F, K, M, P = data["R"], data["O"], data["F"], data["K"], data["M"], data["P"]
    r = R[0]
    k = K[0]
    y_ork_total = sum(handles["Y_ork"][o, r, k].X for o in O)
    y_frk_total = sum(handles["Y_frk"][f, r, k].X for f in F)
    mm = "Aluminium"
    mu_al = data["mu"][mm]
    rho_al = data["rho_by_tech"]["bulk"][mm]  # R_Bulk forces tech_class_override="bulk"

    inflow_kg_hand = mu_al * (y_ork_total + y_frk_total)
    q_rm_hand = rho_al * inflow_kg_hand
    q_rm_solver = handles["Q_rm"][r, mm].X

    log(f"    Y_ork[*,{r},{k}] total={y_ork_total:.6f} kWp, Y_frk[*,{r},{k}] total={y_frk_total:.6f} kWp")
    log(f"    mu[{mm}]={mu_al} kg/kWp, rho_bulk[{mm}]={rho_al}")
    log(f"    Hand: inflow_kg = {mu_al} * ({y_ork_total:.6f}+{y_frk_total:.6f}) = {inflow_kg_hand:.6f} kg")
    log(f"    Hand: Q_rm[{r},{mm}] = {rho_al} * {inflow_kg_hand:.6f} = {q_rm_hand:.6f} kg")
    log(f"    Solver: Q_rm[{r},{mm}] = {q_rm_solver:.6f} kg")
    if not math.isclose(q_rm_hand, q_rm_solver, rel_tol=1e-6, abs_tol=1e-6):
        raise AssertionError(f"Hand-check FAILED: hand={q_rm_hand} vs solver={q_rm_solver}")

    p = P[0]
    v_pm_solver = handles["V_pm"][p, mm].X
    u_pm_solver = handles["U_pm"][p, mm].X
    embodied_hand = mu_al * sum(handles["X_pk"][p, kk].X for kk in K)
    log(f"    Solver: V_pm[{p},{mm}]={v_pm_solver:.6f} + U_pm[{p},{mm}]={u_pm_solver:.6f} "
        f"= {v_pm_solver + u_pm_solver:.6f} kg")
    log(f"    Hand:   mu[{mm}] * sum_k X_pk[{p},k] = {embodied_hand:.6f} kg")
    if not math.isclose(v_pm_solver + u_pm_solver, embodied_hand, rel_tol=1e-6, abs_tol=1e-6):
        raise AssertionError("Hand-check FAILED on plant material balance (3.6).")
    log("    [PASS] Hand-computed values match solver output to the reported tolerance.")


# ==========================================
# DOMINANCE CHECK: High-Value recycling must never cost/emit more than Bulk
# ==========================================
def run_dominance_test():
    """
    rho_highvalue exceeds rho_bulk for every material (Al 0.99 vs 0.90, Si
    0.95 vs 0.50, Ag 0.94 vs 0.20, etc.), while RC/FixR/CAPR are identical
    between the two tech classes -- High-Value recovers strictly more
    material for the same cost, so it should never cost more or emit more
    than Bulk at any matched constraint, in either country. Solved on the
    SHARED epsilon grid (intersection of both scenarios' independently
    derived payoff-table ranges), not each scenario's own grid, so this is
    a true matched-constraint comparison rather than an artifact of two
    different sweeps landing at different eps values.
    """
    log("=== DOMINANCE CHECK: HighValue must never cost/emit more than Bulk at a matched constraint ===")

    def payoff(data, scen_key):
        m, Expr_Cost, Expr_Env, handles = build_model(data, scenarios[scen_key])
        m.setParam("OutputFlag", 0)
        m.setObjective(Expr_Cost, GRB.MINIMIZE)
        m.optimize()
        Zcost_min = m.ObjVal
        Zenv_at_costmin = Expr_Env.getValue()
        m.setObjective(Expr_Env, GRB.MINIMIZE)
        m.optimize()
        Zenv_min = m.ObjVal
        Zcost_at_envmin = Expr_Cost.getValue()
        return m, Expr_Cost, Expr_Env, handles, Zcost_min, Zenv_at_costmin, Zenv_min, Zcost_at_envmin

    for country_name, cfg in COUNTRIES.items():
        data = load_country_data(cfg["file"], cfg["col"])
        m_b, Cost_b, Env_b, h_b, cmin_b, e_at_cmin_b, emin_b, c_at_emin_b = payoff(data, "R_Bulk")
        m_h, Cost_h, Env_h, h_h, cmin_h, e_at_cmin_h, emin_h, c_at_emin_h = payoff(data, "R_HighValue")

        # Curve A: cap env, minimize cost -- on the shared eps_env range
        eps_lo, eps_hi = max(emin_b, emin_h), min(e_at_cmin_b, e_at_cmin_h)
        if eps_lo < eps_hi:
            eps_values = np.linspace(eps_lo, eps_hi, NUM_STEPS)
            rows_b = run_augmecon2_sweep(m_b, Cost_b, Env_b, eps_values, max(e_at_cmin_b - emin_b, 1e-9),
                                          "epsilon_env", "cost", "env", data, h_b)
            rows_h = run_augmecon2_sweep(m_h, Cost_h, Env_h, eps_values, max(e_at_cmin_h - emin_h, 1e-9),
                                          "epsilon_env", "cost", "env", data, h_h)
            n = min(len(rows_b), len(rows_h))
            for i in range(n):
                cb, ch = rows_b[i]["cost"], rows_h[i]["cost"]
                tol = 1e-4 * max(abs(cb), abs(ch), 1.0)
                if ch > cb + tol:
                    raise AssertionError(
                        f"Dominance check FAILED ({country_name}, Curve A, eps_env={eps_values[i]:,.0f}): "
                        f"HighValue cost {ch:,.2f} > Bulk cost {cb:,.2f} "
                        f"(mip_gaps: bulk={rows_b[i]['mip_gap']:.2e}, hv={rows_h[i]['mip_gap']:.2e})")
            log(f"    [PASS] {country_name} Curve A: HighValue cost <= Bulk cost at all {n} matched eps_env points.")
        else:
            log(f"    [SKIP] {country_name} Curve A: no overlapping eps_env range between the two payoff tables.")

        # Curve B: cap cost, minimize env -- on the shared eps_cost range
        eps_lo, eps_hi = max(cmin_b, cmin_h), min(c_at_emin_b, c_at_emin_h)
        if eps_lo < eps_hi:
            eps_values = np.linspace(eps_lo, eps_hi, NUM_STEPS)
            rows_b = run_augmecon2_sweep(m_b, Env_b, Cost_b, eps_values, max(c_at_emin_b - cmin_b, 1e-9),
                                          "epsilon_cost", "env", "cost", data, h_b)
            rows_h = run_augmecon2_sweep(m_h, Env_h, Cost_h, eps_values, max(c_at_emin_h - cmin_h, 1e-9),
                                          "epsilon_cost", "env", "cost", data, h_h)
            n = min(len(rows_b), len(rows_h))
            for i in range(n):
                eb, eh = rows_b[i]["env"], rows_h[i]["env"]
                tol = 1e-4 * max(abs(eb), abs(eh), 1.0)
                if eh > eb + tol:
                    raise AssertionError(
                        f"Dominance check FAILED ({country_name}, Curve B, eps_cost={eps_values[i]:,.0f}): "
                        f"HighValue env {eh:,.2f} > Bulk env {eb:,.2f} "
                        f"(mip_gaps: bulk={rows_b[i]['mip_gap']:.2e}, hv={rows_h[i]['mip_gap']:.2e})")
            log(f"    [PASS] {country_name} Curve B: HighValue env <= Bulk env at all {n} matched eps_cost points.")
        else:
            log(f"    [SKIP] {country_name} Curve B: no overlapping eps_cost range between the two payoff tables.")


# ==========================================
# MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    print("\n=== STARTING EXTENDED MULTI-COUNTRY, MULTI-SCENARIO PARETO GENERATION ===\n")

    log("=== 1.4 ID-CONSISTENCY PRE-FLIGHT (both country workbooks) ===")
    for country_name, cfg in COUNTRIES.items():
        assert_id_consistency(cfg["file"])

    run_regression_test()
    run_extreme_value_tests()
    run_hand_check()
    run_dominance_test()

    print("\n=== VALIDATION PASSED -- GENERATING FULL SCENARIO x COUNTRY SWEEP ===\n")
    for country_name, cfg in COUNTRIES.items():
        data = load_country_data(cfg["file"], cfg["col"])
        for key, sdata in scenarios.items():
            solve_scenario_pareto(country_name, data, key, sdata)

    print("\n=== ALL SCENARIOS COMPLETED ===")
    print(f"Check outputs/pareto_csv/ for {len(COUNTRIES) * len(scenarios) * 2} new CSV files "
          f"(Pareto_<Country>_<Scenario>_{{CostMin,EnvMin}}.csv).")
