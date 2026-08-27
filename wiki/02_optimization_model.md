# Optimization Model — `new_model_both3.py`

## Purpose

For each of **5 scenarios** × **2 countries** (Germany, India), build a mixed-integer linear
program (MILP) of the PV supply chain (production → market → returns → collection →
reuse/refurbish/recycle/landfill, with material recovered from recycling reducing virgin material
purchases), then trace out the **cost vs. environmental-impact Pareto frontier** using
**AUGMECON2**. A mandatory validation suite runs before any production output is trusted. Results
are written to CSV per (country, scenario).

## Scenarios

```python
scenarios = {
    "A":           {"reuse_limit": 0.10, "refurb_yield": 0.30, "tech_class_override": None,       "recycling_available": False},
    "C":           {"reuse_limit": 0.60, "refurb_yield": 0.50, "tech_class_override": None,       "recycling_available": False},
    "R_None":      {"reuse_limit": 0.05, "refurb_yield": 0.20, "tech_class_override": None,       "recycling_available": False},
    "R_Bulk":      {"reuse_limit": 0.05, "refurb_yield": 0.20, "tech_class_override": "bulk",      "recycling_available": True},
    "R_HighValue": {"reuse_limit": 0.05, "refurb_yield": 0.20, "tech_class_override": "highvalue", "recycling_available": True},
}
```

- **`reuse_limit`** — max fraction of collected end-of-life material routed straight back to
  market as "reused."
- **`refurb_yield`** (`alpha`) — fraction of material sent to refurbishment that comes out
  successfully as usable product; the rest becomes waste routed to recycling or landfill.
- **`tech_class_override`** — forces `rho[r,m]` (material recovery rate) to resolve against
  the `"bulk"` or `"highvalue"` column of sheet 14, regardless of what `Tech_Class` the facility
  is literally tagged with in sheet 15.
- **`recycling_available`** — when `False`, `solve_scenario_pareto()` forces `R=[]` for that
  scenario's solve, structurally removing recycling as an option (not just making it
  uneconomical). Only consulted by the production sweep; the validation/test functions call
  `build_model()` directly and always see the full `R`, since they're testing the recycling
  mechanism itself, not a named scenario's policy intent.

**This scenario set replaced two earlier, flawed designs — worth understanding why, since it's
the actual methodological finding of this section of the project:**

1. *First design (A–D + a bulk/high-value recycling pair at B's reuse/refurb levels)*: the two
   recycling-tech scenarios came out nearly identical (max ~4% cost gap). Root cause: refurbishment
   center F1 has a hard 1,000,000 kWp/year capacity, and at 85% refurb yield it fills that cap and
   absorbs 76.22% of collected material on its own — leaving only 3.78% as overflow for recycling
   to compete over. A better recycling *technology* can only move the needle on that leftover
   3.78% slice. Verified via the `open_facilities`/`recycle_share`/`Q_rm_*` output columns, not
   assumed — this was capacity-starvation, not an uneconomical technology.
2. *Second design (moved the bulk/high-value pair to low reuse/refurb levels — 5%/20% — where F1's
   waste stream is much bigger)*: the tech gap became real (~9.9% cost gap at Germany cost-min),
   but scenario `A` (meant to be the linear/no-circularity baseline) was found to opportunistically
   use recycling at up to 58.6% of collected material once the emissions cap tightened, since
   recycling was structurally available to every scenario by default — contaminating what "A" was
   supposed to represent, and leaving no scenario that isolates "does recycling help at all" from
   "does the reuse/refurb policy help" (any gap between the recycling pair and `A`/`C` was
   confounded by the reuse/refurb levels differing too).
3. **Current design**: `A` and `C` now force `recycling_available=False`, so they represent what
   reuse/refurbishment policy *alone* can achieve. `R_None`/`R_Bulk`/`R_HighValue` form a
   **controlled triplet** — identical reuse (5%) and refurb yield (20%), varying only whether/which
   recycling exists. `R_None→R_Bulk` isolates whether recycling helps at all (verified: ~17.5%
   cost reduction at Germany cost-min); `R_Bulk→R_HighValue` isolates the technology choice
   specifically (~9.9% further reduction, matching finding 2 above). A **dominance check** (§7.5)
   now asserts `R_HighValue` never costs or emits more than `R_Bulk` at any matched constraint, in
   either country — passes cleanly.

`NUM_STEPS = 10` — points sampled along each Pareto curve. `MODULE_KWP = 0.435` — the reference
module rating used to convert revenue figures from €/module to €/kWp (see data schema §10).

## Sets

| Set | Meaning | Source |
|---|---|---|
| `P` | Plants | Sheet "1. Sets" |
| `C` | Customer/market zones | Sheet "1. Sets" |
| `O` | Collection centers | Sheet "1. Sets" |
| `F` | Refurbish centers | Sheet "1. Sets" |
| `L` | Landfills | Sheet "1. Sets" |
| `S` | Suppliers | Sheet "1. Sets" |
| `R` | **Recycling facilities** | Sheet "1. Sets" |
| `K` | Module types | Sheet "7. Module Weights" |
| `M` | **Tracked materials** | Sheet "14. Materials" |

## Decision variables

| Variable | Domain | Meaning |
|---|---|---|
| `X_pk[p,k]` | ≥0 | production at plant `p` of module `k` |
| `X_pck[p,c,k]` | ≥0 | shipment plant → market |
| `Y_cok[c,o,k]` | ≥0 | returns flow: market → collection center (gated by `eta`, see 3.1) |
| `Y_ock[o,c,k]` | ≥0 | reuse flow: collection center → market |
| `Y_ofk[o,f,k]` | ≥0 | collection center → refurbish center |
| `Y_olk[o,l,k]` | ≥0 | collection center → landfill (direct disposal) |
| `Y_ork[o,r,k]` | ≥0 | **collection center → recycling facility** |
| `Y_fpk[f,p,k]` | ≥0 | refurbish center → plant (successfully refurbished output re-enters supply) |
| `Y_flk[f,l,k]` | ≥0 | refurbish center → landfill (refurb waste, landfill-bound share) |
| `Y_frk[f,r,k]` | ≥0 | **refurbish center → recycling facility (refurb waste, recycling-bound share)** |
| `S_ck[c,k]` | ≥0 | unmet demand (shortfall) — empirically always 0, see data schema §5 |
| `W_o[o]`, `W_f[f]` | binary | is collection/refurbish center open? |
| `W_r[r]` | binary | **is recycling facility open?** |
| `Z_sp[s,p]` | ≥0 | raw material flow supplier → plant — kept for bookkeeping, **not priced in either objective** (see Objectives, `price_materials`) |
| `Q_rm[r,m]` | ≥0 | **recovered mass of material `m` at facility `r` (kg)** |
| `U_pm[p,m]` | ≥0 | **recovered material `m` consumed at plant `p` (kg)** |
| `V_pm[p,m]` | ≥0 | **virgin material `m` purchased for plant `p` (kg)** |
| `G_m[m]` | ≥0 | **recovered material `m` sold externally (kg)** |
| `RES_r[r]` | ≥0 | **residue mass at recycling facility `r` (kg)** |

## Constraints

1. **Bill of materials**: `Z_sp[s,p] == (total production at p) * BOM[s]` — unchanged, informational only now.
2. **Demand satisfaction**: `X_pck + Y_ock + S_ck == DEM[c,k]`.
3. **3.1 — Collection with formal-collection efficiency**: `sum_o Y_cok[c,o,k] == eta * RET[c,k]`
   (replaces the old "all returns collected" balance — only `eta` fraction of returns ever reach
   the formal system; the rest is uncollected leakage, priced via `E_leak` in the environmental
   objective, not modeled as a flow variable).
4. **Plant flow balance**: `X_pk + sum_f Y_fpk == sum_c X_pck` — unchanged.
5. **3.2 — Collection center 4-way balance**: inflow (`Y_cok`) == `Y_ock` (reuse) + `Y_ofk`
   (refurb) + `Y_ork` (**recycle, new**) + `Y_olk` (landfill). Plus the reuse-limit cap:
   `Y_ock <= reuse_lim * inflow`.
6. **Refurbishment yield (unchanged) + 3.3 residue split (new)**: success `Y_fpk == alpha[f] *
   Y_ofk_in`; residue `Y_frk + Y_flk == (1-alpha[f]) * Y_ofk_in` — refurbishment's own waste now
   splits between recycling and landfill (previously landfill-only).
7. **3.4 — Material recovery**: `Q_rm[r,m] == rho[r,m] * (mu[m] * (Y_ork inflow + Y_frk inflow),
   in kg)` — the kWp→kg conversion via `mu[m]` (already pre-multiplied by `omega`, do not
   re-multiply) is the single most error-prone step here; verified against a hand-computed trace
   in the validation suite (§7.4).
8. **3.5 — Recovered-material disposition**: two separate constraints (deliberately not merged,
   they bind at different times) — `U_pm + G_m == Q_rm` (every recovered kg is used internally or
   sold, not both, not neither) and `U_pm <= beta[m] * Q_rm` (quality-substitution cap — e.g.
   recovered silicon can cover at most 30% of a plant's silicon need, since it's only
   metallurgical- not solar-grade).
9. **3.6 — Plant material balance**: `V_pm[p,m] + U_pm[p,m] == mu[m] * X_pk[p,k]` (summed over
   `k`). **This is the sole recovery-credit mechanism** — recovered material's economic/emissions
   benefit flows entirely through reducing `V_pm` (virgin purchase), never as a separate
   credit/revenue term anywhere else. Verified by grep after every change to the objectives.
10. **3.7 — Recycling residue**: `RES_r[r] == (total mass inflow to r, kg) - sum_m Q_rm[r,m]`.
11. **Capacities**: plant/collection/refurbish unchanged (kWp, gated by `W_o`/`W_f` where
    applicable). **3.8 — recycling capacity**: `(Y_ork + Y_frk inflow, kWp) <= CAPR[r] * W_r[r]`
    — kept in kWp units (see data schema §9's note on why).

## Objectives

Two linear expressions, built with several correctness-critical toggles (all default to the
*fixed*/correct behavior for production; the regression test flips them to reproduce the original
model's behavior exactly — see §7.1):

- **`price_materials`** (default `True`): the material-level `V_pm`/`U_pm` mechanism *replaces*
  the old component-level `Mat_Cost[s]*Z_sp[s,p]` cost term (material `M` already includes an
  "Other" bucket absorbing the non-tracked-component cost, so this is a clean replacement, not
  double-counting) and adds `EMv[m]*V_pm` to the environmental objective (never priced before).
- **`fix_revenue_units`** (default `True`): converts `Rev_reuse`/`Rev_refurb` from €/module to
  €/kWp (data schema §10's bug fix).
- **`fix_landfill_emission_units`** (default `True`): treats `E_l` per-kWp like `E_o`/`E_f`
  instead of per-kg via `omega` (data schema §12's bug fix).
- **`fix_refurb_waste_leg`** (default `True`): uses the real `F1→L1` transport distance instead of
  a hardcoded 50km fallback.

### `Expr_Cost` (€, to minimize)
Fixed facility-opening costs (now including `FixR[r]*W_r[r]`) + production cost + collection/
refurb/landfill/**recycling** handling costs (`RC[r]` per kg, converted via `omega[k]`) + transport
for every leg including the new `O1↔R1`, `F1↔R1`, `R1↔L1` legs (the last two use `strict=True`
`DIST()` lookups — no silent 500km fallback) + shortfall penalty − reuse/refurb revenue (unit-fixed)
+ `MCv[m]*V_pm` (virgin material, replacing `Mat_Cost*Z_sp`) − `MVs[m]*G_m` (recovered-material
sale revenue).

### `Expr_Env` (kg CO2e, to minimize)
Production/collection/refurb/landfill emissions (`E_l` unit-fixed) + **recycling processing
emissions** (`E_r`, per kWp, both flows) + transport emissions (same leg set as cost, `E_l`-derived
per-kg rate applied to the mass-only `RES_r` residue term) + `EMv[m]*V_pm` (embodied virgin-material
emissions) + `E_leak * (1-eta) * total returns` (uncollected-material leakage, a constant term —
zero for Germany, since `E_leak` isn't numeric there). **No credit term for `U_pm` or `Q_rm`
anywhere** — the avoided-burden credit is carried entirely by the reduced `V_pm` in constraint 3.6.

## AUGMECON2

Both sweep directions replace the plain `expr_cap <= eps` inequality with an equality-with-slack
(`expr_cap + s == eps`) and add a small penalty on the slack (`delta=1e-3`, a named constant —
Mavrotas & Florios 2013) to the minimized objective, nudging the solver toward the most-improving
point on the current facet rather than an arbitrary alternate optimum. A fresh slack variable is
added and removed every iteration (`run_augmecon2_sweep()`) — never persisted across iterations.
`augmecon_slack`, `mip_gap`, and `runtime_s` are recorded per output row.

## Pareto frontier method

`solve_scenario_pareto()`, per (country, scenario):

1. **Payoff table**: minimize `Expr_Cost` alone → `Zcost_min`, record `Expr_Env` there; minimize
   `Expr_Env` alone → `Zenv_min`, record `Expr_Cost` there. Brackets the achievable range.
2. **Curve A ("CostMin")** — cap emissions at `eps` (swept `Zenv_min → Zenv_at_costmin`,
   `NUM_STEPS` points via AUGMECON2), minimize cost. → `Pareto_<Country>_<Scenario>_CostMin.csv`
   (`epsilon_env, cost, env, augmecon_slack, mip_gap, runtime_s, <shares>, <Q_rm/virgin_displaced
   per material>, open_facilities`).
3. **Curve B ("EnvMin")** — cap cost at `eps`, minimize emissions. → `..._EnvMin.csv`
   (`epsilon_cost, cost, env, ...` same extended columns).

`summarize_solution()` computes the extended columns. **Note**: `reuse_share`/`refurb_share`/
`recycle_share`/`landfill_share` are fractions of formal-collection inflow. A bug was found and
fixed this pass — `recycle_share`/`landfill_share` originally only counted the *direct* collection
routes (`Y_ork`/`Y_olk`), silently missing the *refurbishment-waste* routes (`Y_frk`/`Y_flk`).
This never affected any `cost`/`env` number (those were always computed correctly from the full
constraint set) — only the diagnostic percentage columns, which is what made India's recycling
usage initially look like it was near-zero when it was actually reaching 76% share once corrected.

## Mandatory validation suite (§7, runs on every execution before production output)

All in `new_model_both3.py`, run unconditionally in `__main__` before the full sweep:

1. **§1.4 ID-consistency pre-flight** (`assert_id_consistency()`) — both workbooks, hard-raises
   on any declared-but-unreferenced or referenced-but-undeclared ID.
2. **§7.1 Regression test** (`run_regression_test()`) — Germany scenario A with `R=[]`, `eta=1.0`,
   and all four "fix" flags set to `False` (legacy/buggy behavior), compared against the
   already-committed `Germany_data_v2_1512.xlsx`-derived baseline CSVs. Passes to ~1e-16 relative
   tolerance. The four fix flags must all be off here specifically because none of them are
   vacuous under `R=[]` — e.g. the revenue-unit fix and material-costing replacement change
   absolute € numbers regardless of whether any recycling facility exists.
3. **§7.2 Extreme-value tests** (`run_extreme_value_tests()`) — `eta=0` (network collapses to
   forward-only, matches a hand-computed baseline exactly); `rho=0` (recycling never selected
   under cost-min); `MVs×1e6` for one material (recycling activates under a *stricter* emissions
   cap than baseline — confirms the economic incentive channel is genuinely connected, not just
   structurally present).
4. **§7.4 Hand-check** (`run_hand_check()`) — one recycling flow (`Q_rm[R1,Aluminium]`) traced by
   calculator against the solver's own output, using the `R_Bulk` scenario specifically because it
   has substantial (not thin-sliver) recycling flow to trace.
5. **Dominance check** (`run_dominance_test()`) — `R_HighValue` must never cost or emit more than
   `R_Bulk` at any matched constraint (both have identical `RC`/`FixR`/`CAPR`, only `rho` differs,
   and `rho_highvalue > rho_bulk` for every material — so this is a hard, testable property, not
   a heuristic). Solved on the *shared* ε-grid (intersection of both scenarios' independently
   derived payoff-table ranges), not each scenario's own grid, so it's a true matched-constraint
   comparison.
6. **§7.3 Mass-balance audit** (`mass_balance_audit()`) — runs on *every* solved point in the full
   production sweep, not just the validation suite. Independently recomputes the collection-center
   balance, the recycling-facility mass balance, the plant material balance, and a system-level
   aggregate check from raw solution values (not trusting the solver's own "feasible" status), and
   hard-raises rather than silently dropping a point on any violation beyond tolerance
   (`math.isclose`, `rel_tol=1e-6`, `abs_tol=1e-3`).

If any check fails, the script raises and stops — no result is written to CSV from a run that
didn't pass validation.

## Output files
Per (country, scenario): `Pareto_<Country>_<ScenarioName>_CostMin.csv`,
`Pareto_<Country>_<ScenarioName>_EnvMin.csv`. Current: 2 countries × 5 scenarios × 2 curves = 20
files in `outputs/pareto_csv/`. 8 historical Germany-only files (no country prefix, from before
this extension) remain alongside them for reference.

## See also
- [01_data_schema.md](01_data_schema.md) — where every input symbol comes from
- [03_visualization.md](03_visualization.md) — how these CSVs become comparison charts
