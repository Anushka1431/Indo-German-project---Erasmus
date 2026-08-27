# Data Schema — `Germany_data_v3_extended.xlsx` / `India_data_v1_starter.xlsx`

Both workbooks have the same 16 (Germany) or 17 (India, plus a derivations sheet) sheets, loaded
by the same code path in `load_country_data(xlsx_path, country_col)`, so the model can loop over
both countries identically. Sheet names are matched by literal string (with one fallback: the
"Production Costs" sheet is actually named `" Prod"` with a leading space, so the code searches
for any sheet name containing `"Prod"` if the expected names aren't found).

Both workbooks carry a **`0. README - Data Provenance`** sheet (read this before trusting any
number) with a colour-legend convention — blue/real-sourced, yellow/new-structural-parameter,
orange/assumption-treat-as-sensitivity-parameter — and an explicit list of what's still missing
or not yet real, per country.

## 1. Sets — network nodes

Sheet **"1. Sets"**, columns: `Plants (P)`, `CustomerZones/Market (C)`, `Collection Centers (O)`,
`Refurbish Centers (F)`, `Landfills (L)`, `Suppliers (S)`, and now **`Recycling Facilities (R)`**.
Each column lists the IDs for one node type (ragged — short columns are padded with blanks,
dropped via `.dropna()`).

Maps to code sets: `P`, `C`, `O`, `F`, `L`, `S`, `R` (Germany: P1–P2, C1–C4, O1, F1, L1, S1–S5, R1;
India: P1–P2, C1–C5, O1, F1, L1, S1–S5, R1). `K` (module types, currently just `"Monocrystalline"`)
is derived from sheet **"7. Module Weights"**, and `M` (the five tracked materials plus an "Other"
bucket) from the new **"14. Materials"** sheet.

**Mandatory pre-flight check**: `assert_id_consistency()` cross-checks every ID declared here
against every ID actually referenced in the cost/capacity/transportation/BOM sheets, and hard-
raises on any mismatch — this caught a real bug during data prep (an earlier India workbook draft
declared `"P1 (Mundra, GJ)"` in Sets while every other sheet used plain `"P1"`).

## 2. Production Costs — sheet `" Prod"`
Unchanged: `Plant_ID` → `PC[p]` (€/kWp), already country-baked (India ≈ Germany × 0.38 labour
multiplier).

## 3. Operational Costs
`Facility_ID`, `Cost_per_Unit (CC_o/FC_f/RC_r for KWp or kg)` → split into `CC` (collection, €/kWp),
`FC` (refurbish, €/kWp), `DC` (landfill disposal, €/kg — the only one of the three that's per-kg,
matching real-world tipping-fee billing conventions).

**R1's row in this sheet is deliberately NOT used.** A real unit inconsistency was found between
the two workbooks here: Germany's R1 value is stated per-kWp, India's is stated per-kg, despite
the identical column header — see §15 below for where `RC`/`FixR` are actually sourced instead.

## 4. Fixed Costs
Unchanged structure: `Facility_ID` → `Fixed_Operational_Cost (Fix)` → `FixO`/`FixF`. R1's row here
is also not used (see §15).

## 5. Penalty Costs
`Module_Type_ID` → `Penalty_Cost_per_KWp (Pen_k)` → `Penalty[k]`, applied to shortfall `S_ck`.
The sheet's own note confirms this is *"not independently sourced; retained as a modelling
device, not a real penalty tariff"* — and empirically it never binds: total plant capacity
(3.5M kWp) comfortably exceeds total demand (3.2M kWp) in both countries, so `S_ck = 0` in every
solved scenario. It exists purely as a safety valve against infeasibility, not as a real cost
driver in any reported number.

## 6. Demand & Returns
Unchanged: `DEM[(c,k)]`, `RET[(c,k)]`. India's demand is deliberately scaled to the same ~3.2 GWp
order of magnitude as Germany's for comparability, not India's real (much larger, >100 GWp)
market size — flagged explicitly in India's README sheet.

## 7. Module Weights
Unchanged: `omega[k]` (kg/kWp), 49.3 for both countries (a technology property, not regional).

## 8. Yield Rates
Still not read by the code — the scenario matrix (§`02_optimization_model.md`) overrides
`reuse_limit`/`refurb_yield` per scenario instead. Kept for reference only.

## 9. Capacities
`Facility_ID` → `Capacity_Value_kWp`, now including an **R1** row. `CAPR[r]` is deliberately
sourced from *this* sheet (kWp) rather than sheet 15's kg figure — sheet 9's R1 value was
precomputed as the kWp-equivalent of sheet 15's kg capacity specifically so the recycling
capacity constraint can stay in kWp units like the P/O/F capacity constraints, no `omega`
conversion needed there.

## 10. Revenues
`Revenue_Stream`, `Item_ID`, `Revenue_per_Unit (Rev)_EUR` (column renamed from the original
`..._€` to plain `_EUR` in the v3 workbook — the loader matches by prefix, not exact string, to
survive this). **Bug found and fixed**: these figures (50/80) are priced per *physical module*
(cross-checked against the cited SecondSol €0.08–0.2/Wp range × the 435 Wp reference module —
35–87 €/module, consistent with 50/80), not per kWp, but the original model multiplied them
directly against kWp-flow variables, understating reuse/refurb revenue by `1/0.435 ≈ 2.3×`.
Fixed via `fix_revenue_units` (default `True`, divides by `MODULE_KWP=0.435`); the regression test
uses `fix_revenue_units=False` since the old baseline CSVs were generated with the bug present.

## 11. Transportation
`Origin_ID`, `Destination_ID`, `Distance_km`, `Cost_per_kg_km` (`T_cost`), `Emission_per_kg_km`
(`T_emit`, both taken from the first row as global constants). Germany's distances are AI-
generated placeholders (geographically plausible, not real coordinates); India's are real —
haversine great-circle distance between real city coordinates × a 1.3 road-detour factor.

New recycling-echelon legs: `O1↔R1`, `R1↔S1..S5`, `F1↔R1`, `R1↔L1` — all real rows in both
workbooks. `F1→L1` (refurbishment waste → landfill) was also added as a real row this pass
(previously a hardcoded 50km fallback in code, because the leg was simply missing from the
sheet); India's value (806.2 km) equals its existing `F1→O1` distance since `L1` is co-located
with `O1` (both Nagpur, per the README's node-ID list) — not a new guess. The `DIST()` lookup
function takes a `strict=True` flag for every recycling-echelon leg: it hard-raises instead of
silently falling back to a 500 km default if a required leg is ever missing.

## 12. Environmental
`Parameter_Name` → `Value_kg_CO2e`: `E_p`, `E_o`, `E_f`, `E_l`, and now **`E_r`** (recycling
processing emissions, per kWp — already country-baked: India = Germany × 1.2, same convention
as `E_o`/`E_f`/`E_l`). India's sheet also carries an `E_leak` row (15 kg CO2e/kWp); Germany's
doesn't have one at all — its value in sheet 16 is the literal string `"n/a (eta high)"`, parsed
as `0.0` with a log note, matching the modeler's own annotation that leakage is negligible given
Germany's high formal-collection rate.

**Bug found and fixed**: `E_l` was being multiplied by `omega[k]` (treated as per-kg) while
`E_o`/`E_f`/`E_p` were not (treated as per-kWp) — despite the source data setting `E_o == E_l`
and the thesis prose describing both identically as *"~5 kg CO2e per kWp."* That asymmetry made
`E_l`'s effective contribution ~49× larger than `E_o`'s for the same stated value, and the
inflated magnitude (~246 kgCO2e/kWp) isn't physically plausible for landfilling largely-inert
module material (glass/aluminium/silicon don't decompose the way organic waste does — unlike
disposal *cost*, which legitimately is per-kg since real tipping fees are billed by weight).
Fixed via `fix_landfill_emission_units` (default `True`, treats `E_l` per-kWp like `E_o`/`E_f`;
for the mass-only `RES_r` residue term, an effective per-kg rate is derived as `E_l / omega[K[0]]`
— exact for today's single-module-type data). Regression test uses the old (buggy) behavior.

## 13. Supplier_BOM
Unchanged structure (`BOM[s]`, `Mat_Cost[s]`, `Em_Supplier[s]`). Every component's
`Qty_per_Module = 1`, so `Z_sp[s,p]` never conveyed real distinct bill-of-materials granularity —
it's just a copy of total production repeated once per supplier. Kept for bookkeeping only; no
longer priced in either objective (see §14's note on the replace-vs-coexist decision).

## 14. Materials — new
Pure-material (not component) composition, indexed by `Material` ∈ {Aluminium, Glass, Silicon,
Copper, Silver, "Other (polymer/backsheet/EVA/junction box)"}. Identical in both workbooks
(global commodity data). Columns:

| Column | Symbol | Notes |
|---|---|---|
| `Mass_fraction_of_module` | — | sums to 1.0 |
| `mu_kg_per_kWp (omega=49.3)` | `mu[m]` | **already pre-multiplied by `omega_k`** — do not multiply by `omega[k]` again |
| `rho_bulk (mechanical, Reiling-type)` | `rho[r,m]` when `r`'s tech class resolves to `bulk` |
| `rho_highvalue (FRELP-type)` | `rho[r,m]` when resolved to `highvalue` |
| `MCv_virgin_EUR_per_kg` | `MCv[m]` | virgin material purchase price |
| `MVs_secondary_EUR_per_kg` | `MVs[m]` | secondary/recovered material sale price |
| `EMv_virgin_kgCO2e_per_kg` | `EMv[m]` | embodied emissions of virgin material |
| `beta_quality_substitution` | `beta[m]` | max fraction of a plant's material need coverable by recovered material (e.g. Silicon `beta=0.30`: recovered PV silicon is only metallurgical grade, can't fully substitute for solar-grade virgin input) |

"Other" has `rho=0`, `beta=0` by construction (not targeted for material recovery by either
recycling technology; folded into the residue stream). **`EMv[Silver]` was updated this pass**
from an unsourced ~2000 kgCO2e/kg placeholder to 114 kgCO2e/kg (midpoint of a 104–123.7 kgCO2e/kg
range for primary silver production, cited from a peer-reviewed embodied-carbon review and
cross-checked against precious-metals-refiner carbon-footprint disclosures) — see the cell's own
note for the full citation.

`mu[m]` internally verified consistent: mass fractions sum to 1.0, and `mu[m]` values sum to
49.3 = `omega`, confirming it's genuinely pre-multiplied as the header warns.

## 15. Recycling Facilities — new
`Facility_ID`, `Tech_Class`, `RC_per_kg_EUR`, `FixR_EUR`, `CAPR_kg_per_year`, `ER_per_kg_kgCO2e`.
**This sheet is a shared, deliberately-unscaled Germany-baseline row in *both* workbooks** — its
own "Country note" cell instructs computing India's R1 economics as this row × the country's
labour multiplier, not trusting any other sheet (see §3's note on why sheet 3's R1 row can't be
trusted for this either). Accordingly: `RC[r]` and `FixR[r]` are sourced *only* from here,
multiplied in code by the country's labour multiplier from sheet 16. `ER_per_kg` is **not used**
at all — see §12's note on why `E_r` (sheet 12, already country-correct) is the canonical
recycling-emissions parameter instead.

`rho[r,m]` is resolved by matching this sheet's `Tech_Class` string against sheet 14's
`rho_bulk`/`rho_highvalue` columns (substring match on "bulk" vs "high"), with a per-scenario
`tech_class_override` hook (`"bulk"` or `"highvalue"`) that forces the resolution regardless of
what's literally in this cell — used by the `R_Bulk`/`R_HighValue` scenarios.

## 16. Country Levers — new
`Parameter`, `Germany`, `India` columns (both countries' values side by side in both workbooks,
for consistency). Rows: `eta` (formal collection efficiency: DE 0.82, IN 0.30), `E_p`,
grid carbon intensity, `E_leak`, **labour/handling cost multiplier** (DE 1, IN 0.38 — applied only
to `RC`/`FixR` per §15, since everything else that's country-varying is already baked into its
own sheet), transport cost multiplier, EU ETS carbon price (Germany-only benchmark, not applied
to India). Only `eta`, the labour multiplier (for R1), and `E_leak` (Germany fallback) are
actually read at runtime — the rest exist for documentation/derivation traceability.

The labour multiplier's cell was updated this pass with a real citable wage-ratio cross-check
(Reshoring Institute 2022 production-worker wage data puts India at ~6% of Germany's, considerably
lower than the 0.38 used) — the 0.38 figure is kept as-is since it's meant to represent a
*blended* facility operating-cost ratio (labour + capital/overhead, which don't discount as
steeply as raw wages), not a pure wage ratio; both numbers are now visible in the cell for a
reviewer to judge.

## 17. India Derivations (India workbook only)
Documents the full grid-intensity-scaling calculation behind India's `E_p ≈ 1045 kgCO2e/kWp`
(derived from Germany's sourced 580, scaled by the ratio of grid carbon intensities under a
70%-grid-dependent/30%-fixed split assumption), plus a plausibility cross-check against a
published China/Germany footprint ratio. Explicitly flagged as *"Claude's derived estimate...
not a published India-specific PV manufacturing LCA figure."*

## See also
- [02_optimization_model.md](02_optimization_model.md) — how every symbol above is used in constraints and objectives, the full scenario matrix, and the validation suite
