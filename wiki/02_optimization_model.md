# Optimization Model — `new_model_both3.py`

## Purpose

For each of 4 circular-economy **scenarios**, build a mixed-integer linear program (MILP) of
the PV supply chain (production → market → returns → collection → reuse/refurbish/landfill),
then trace out the **cost vs. environmental-impact Pareto frontier** using the ε-constraint
method. Results are written to CSV per scenario.

## Scenarios

```python
scenarios = {
    "A": {"name": "Linear_Like",             "reuse_limit": 0.10, "refurb_yield": 0.30},
    "B": {"name": "Industrial_Refurb",        "reuse_limit": 0.20, "refurb_yield": 0.85},
    "C": {"name": "Consumer_Reuse",           "reuse_limit": 0.60, "refurb_yield": 0.50},
    "D": {"name": "Ideal_Balanced_Circular",  "reuse_limit": 0.50, "refurb_yield": 0.50},
}
```

- **`reuse_limit`** — max fraction of collected end-of-life material that can be routed
  straight back to market as "reused" (rather than to refurbishment or landfill).
- **`refurb_yield`** (`alpha`) — fraction of material sent to a refurbishment center that comes
  out successfully as usable product; the rest becomes waste sent to landfill.

Scenario A = mostly-linear/wasteful baseline; B = high-yield industrial refurbishment; C =
consumer-driven high reuse but mediocre refurb yield; D = a balanced circular-economy ideal.

`NUM_STEPS = 10` — number of points sampled along each Pareto curve.

## Sets

| Set | Meaning | Source |
|---|---|---|
| `P` | Plants | Sheet "1. Sets" |
| `C` | Customer/market zones | Sheet "1. Sets" |
| `O` | Collection centers | Sheet "1. Sets" |
| `F` | Refurbish centers | Sheet "1. Sets" |
| `L` | Landfills | Sheet "1. Sets" |
| `S` | Suppliers | Sheet "1. Sets" |
| `K` | Module types | Sheet "7. Module Weights" |

## Decision variables

| Variable | Domain | Meaning |
|---|---|---|
| `X_pk[p,k]` | ≥0 | production at plant `p` of module `k` |
| `X_pck[p,c,k]` | ≥0 | shipment plant → market |
| `Y_cok[c,o,k]` | ≥0 | returns flow: market → collection center |
| `Y_ock[o,c,k]` | ≥0 | **reuse** flow: collection center → market (direct resale) |
| `Y_ofk[o,f,k]` | ≥0 | collection center → refurbish center |
| `Y_olk[o,l,k]` | ≥0 | collection center → landfill (direct disposal) |
| `Y_fpk[f,p,k]` | ≥0 | refurbish center → plant (**successfully refurbished** output re-enters supply) |
| `Y_flk[f,l,k]` | ≥0 | refurbish center → landfill (**refurbishment waste**) |
| `S_ck[c,k]` | ≥0 | unmet demand (shortfall) at market `c` |
| `W_o[o]` | binary | is collection center `o` open? |
| `W_f[f]` | binary | is refurbish center `f` open? |
| `Z_sp[s,p]` | ≥0 | raw material flow supplier → plant |

## Constraints

1. **Bill of materials**: `Z_sp[s,p] == (total production at p) * BOM[s]` — material draw is
   proportional to production, per supplier.
2. **Demand satisfaction**: `X_pck + Y_ock + S_ck == DEM[c,k]` for every market/module — demand
   is met by fresh production, reused units, or counted as shortfall (penalized).
3. **Returns balance**: `sum_o Y_cok[c,o,k] == RET[c,k]` — all end-of-life returns are
   collected (fully allocated to some collection center).
4. **Plant flow balance**: `X_pk + sum_f Y_fpk == sum_c X_pck` — a plant's saleable output
   (own production + inbound refurbished units) equals what it ships to markets.
5. **Collection center balance**: inflow (`Y_cok` from markets) == outflow (`Y_ock` reuse +
   `Y_ofk` to refurb + `Y_olk` to landfill). Nothing accumulates at a collection center.
6. **Reuse limit (scenario lever)**: `Y_ock <= reuse_lim * In` — caps the fraction of a
   collection center's inflow that can be resold directly as "reuse", per scenario.
7. **Refurbishment yield/waste split (scenario lever)**:
   - success: `Y_fpk == alpha[f] * Y_ofk_in`
   - waste: `Y_flk == (1 - alpha[f]) * Y_ofk_in`
   where `alpha[f]` is set to the scenario's `refurb_yield` for every refurbish center.
8. **Capacities**: plant output ≤ `CAP[p]` always; collection/refurbish throughput ≤
   `CAP[o]/CAP[f]` **only if** that facility is open (`W_o`/`W_f` gate the capacity via
   big-M-style multiplication).

## Objectives

Two linear expressions are built (not simultaneously optimized — see Pareto method below):

### `Expr_Cost` (€, to minimize)
Sum of: fixed facility-opening costs + production cost + collection/refurb/landfill handling
costs + refurbishment-waste disposal cost + raw material cost + transportation cost for every
leg of the network (production→market, market→collection, collection→reuse-market,
collection→refurb, collection→landfill, refurb→landfill waste [fixed 50 km leg], refurb→plant)
+ shortfall penalty − reuse revenue − refurbishment revenue.

### `Expr_Env` (kg CO2e, to minimize)
Sum of: production emissions (`E_p`), collection emissions (`E_co`), refurbishment emissions
(`E_f`), landfill emissions (`E_l`) for both direct-landfill and refurb-waste-landfill flows,
plus transportation emissions for the same set of legs as the cost objective (using `T_emit`
instead of `T_cost`).

Both objectives share the same decision variables/constraints — this is what makes them a true
multi-objective trade-off rather than two independent problems.

## Pareto frontier method — ε-constraint

For each scenario, `solve_scenario_pareto()`:

1. **Payoff table** (the 2 extreme points):
   - Minimize `Expr_Cost` alone → `Zcost_min`, and record `Expr_Env` at that solution.
   - Minimize `Expr_Env` alone → `Zenv_min`, and record `Expr_Cost` at that solution.
   - This brackets the achievable range for each objective.
2. **Curve A — "if we cap emissions at ε, what's the cheapest cost?"**
   - Sweep `eps` linearly from `Zenv_min` to `Zenv_at_costmin` (`NUM_STEPS=10` points).
   - For each `eps`: add constraint `Expr_Env <= eps`, minimize `Expr_Cost`, record
     `(eps, cost, env)`, then remove the constraint before the next iteration.
   - Saved to `Pareto_<ScenarioName>_CostMin.csv` (columns: `epsilon_env, cost, env`).
3. **Curve B — "if we cap budget at ε, what's the lowest emissions?"**
   - Sweep `eps` linearly from `Zcost_min` to `Zcost_at_envmin`.
   - For each `eps`: add constraint `Expr_Cost <= eps`, minimize `Expr_Env`, record
     `(eps, cost, env)`, remove constraint.
   - Saved to `Pareto_<ScenarioName>_EnvMin.csv` (columns: `epsilon_cost, cost, env`).

Running both curves per scenario gives a denser/cross-validated Pareto front than either
sweep alone, and answers both framings of the trade-off question (see
[03_visualization.md](03_visualization.md)).

## Output files (per scenario, `s_name` = scenario's `name` field)
- `Pareto_<s_name>_CostMin.csv`
- `Pareto_<s_name>_EnvMin.csv`

8 files total across 4 scenarios (A–D).

## See also
- [01_data_schema.md](01_data_schema.md) — where every input symbol comes from
- [03_visualization.md](03_visualization.md) — how these CSVs become comparison charts
