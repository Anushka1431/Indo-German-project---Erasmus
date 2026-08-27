# Project Overview — Circular PV Supply Chain Optimization (Germany + India)

## What this project does

This codebase models the **solar photovoltaic (PV) panel supply chain**, for **both Germany and
India**, including end-of-life flows (reuse, refurbishment, recycling, landfill), and solves a
**bi-objective optimization problem**: minimize total **cost (€)** vs. minimize total
**environmental impact (kg CO2e)**.

It compares **5 circular-economy scenarios** — see [02_optimization_model.md](02_optimization_model.md)
for the full rationale — that isolate two different questions: how much of the returned/end-of-life
volume should go to reuse vs. refurbishment (scenarios `A`, `C`), and, independently, whether adding
a **recycling** echelon helps at all and which recycling *technology* to use (scenarios `R_None`,
`R_Bulk`, `R_HighValue`, a controlled triplet at fixed reuse/refurb levels). For each scenario ×
country it traces out a **Pareto frontier** (the cost/environment trade-off curve) using the
**AUGMECON2** refinement of the ε-constraint method, and produces comparison plots.

## Files in this repo

| File | Role |
|---|---|
| `new_model_both3.py` | Core optimization model. Builds and solves the Gurobi MILP for each (country, scenario) pair, generates Pareto curves, runs a mandatory validation suite, writes CSVs. |
| `plot_pareto_curated.py` | Reads the current 5-scenario CSVs from `outputs/pareto_csv/` and renders the primary Germany-vs-India comparison chart. |
| `new_plot_pareto2.py` | Original Germany-only, 4-scenario (A–D) plotting script — reads the historical 8 CSVs still sitting in `outputs/pareto_csv/` from before the recycling-echelon extension. Kept for reference; not part of the current pipeline. |
| `Germany_data_v3_extended.xlsx` | Germany input data — sets, costs, demand, capacities, revenues, transportation, environmental factors, supplier BOM, plus the recycling-echelon sheets (materials, recycling facilities, country levers). Has a `0. README - Data Provenance` sheet documenting exactly which values are sourced vs. assumed. |
| `India_data_v1_starter.xlsx` | India input data, same sheet layout as the Germany workbook (so the same code loops over both) — some values are real (city/plant locations, demand-share weights, distances via haversine), others are the Germany value × a labour/transport multiplier (flagged in its own README sheet). |
| `Germany_data_v2_1512.xlsx` | The original, pre-extension Germany workbook (no recycling echelon). Kept only so the regression test (§7.1, below) has a ground truth to compare against. |
| `outputs/pareto_csv/*.csv` | Model outputs. Current: `Pareto_<Country>_<Scenario>_{CostMin,EnvMin}.csv`, 2 countries × 5 scenarios × 2 curves = 20 files. Also still holds 8 historical Germany-only files (no country prefix) from before the extension. |
| `outputs/plots/*.png` | Comparison charts. `Comparison_Curated_Germany_vs_India.png` is the current primary figure; `Comparison_1_Env_on_X.png` / `Comparison_2_Cost_on_X.png` are the historical Germany-only ones. |
| `requirenments.txt` | Python dependencies (filename is misspelled "requirenments" in the original repo). |

## How the pieces connect (pipeline)

```
Germany_data_v3_extended.xlsx  ─┐
                                 ├─→  new_model_both3.py
India_data_v1_starter.xlsx     ─┘         │
                                           │  1. ID-consistency pre-flight (both workbooks)
                                           │  2. Regression test (vs. Germany_data_v2_1512.xlsx)
                                           │  3. Extreme-value tests
                                           │  4. Hand-check
                                           │  5. Dominance check (HighValue never worse than Bulk)
                                           │  6. Full sweep: per (country, scenario), build MILP,
                                           │     solve payoff table, trace 2 AUGMECON2 Pareto curves
                                           ▼
                    outputs/pareto_csv/Pareto_<Country>_<Scenario>_{CostMin,EnvMin}.csv
                                           │
                                           ▼
                              plot_pareto_curated.py
                                           │
                                           ▼
                  outputs/plots/Comparison_Curated_Germany_vs_India.png
```

## Running it

```bash
python3 -m venv .venv && source .venv/bin/activate   # Homebrew/system Python is externally managed
pip install pandas openpyxl numpy matplotlib seaborn gurobipy
python new_model_both3.py          # validates, then produces 20 CSVs in outputs/pareto_csv/
python plot_pareto_curated.py      # produces outputs/plots/Comparison_Curated_Germany_vs_India.png
```

`gurobipy` requires a valid Gurobi license (a free academic license works fine for this model's
size — a handful of binaries, a few hundred continuous variables).

**`requirenments.txt` is stale** — it lists `math` (a Python stdlib module, not installable — a
no-op line, harmless) and is missing `openpyxl` and `numpy`, both hard runtime dependencies now.
Install via the command above rather than that file until it's fixed.

## Validation the model runs on every execution

Every run of `new_model_both3.py` re-validates before touching production output — see
[02_optimization_model.md](02_optimization_model.md) for what each check actually verifies:

1. **ID-consistency pre-flight** — every ID referenced in cost/capacity/transport sheets must be
   declared in `1. Sets`, and vice versa, for both workbooks.
2. **Regression test** — with recycling structurally disabled (`R=[]`) and collection efficiency
   forced to 100% (`eta=1.0`), the extended model must reproduce the pre-extension
   `Germany_data_v2_1512.xlsx` results to ~1e-16 relative tolerance.
3. **Extreme-value tests** — collection efficiency at 0%, recovery rate at 0%, and an inflated
   secondary-material price, each checked against the behavior theory predicts.
4. **Hand-check** — one recycling flow traced by calculator against the solver's own output.
5. **Dominance check** — the high-value recycling technology must never cost or emit more than
   the bulk technology at any matched constraint, in either country (both have identical
   facility economics, only recovery rates differ, so this is a hard, testable property).
6. **Mass-balance audit** — runs on every single solved point in the full sweep (not just the
   validation suite), independently recomputing every flow-balance constraint from the raw
   solution values and hard-raising on any discrepancy.

If any of these fail, the script raises rather than silently producing a plausible-looking wrong
number — see [02_optimization_model.md](02_optimization_model.md) for the reasoning.

## Known data-quality caveats (see workbook READMEs for full detail)

- Two real bugs were found and fixed this pass: reuse/refurbishment revenue was priced per
  physical module but applied as if per kWp (understated by ~2.3×), and landfill emissions were
  treated per-kg via an `omega`-multiplication that didn't match the per-kWp convention used
  everywhere else (~49× inflated). Both are gated behind flags defaulting to the corrected
  behavior; the regression test uses the old (buggy) behavior deliberately, since that's what the
  pre-extension baseline CSVs were generated with.
- Several assumptions (India's labour-cost multiplier, the recycling facility's processing cost)
  are documented with the best citations found this session but are not fully sourced —
  see each workbook's `0. README - Data Provenance` sheet for the complete list of what's real,
  what's assumption, and what's explicitly deferred as future work.

## See also
- [01_data_schema.md](01_data_schema.md) — Excel input schema, both workbooks, and how columns map to model symbols
- [02_optimization_model.md](02_optimization_model.md) — deep dive on the MILP: sets, variables, constraints, objectives, scenario matrix, AUGMECON2, validation suite
- [03_visualization.md](03_visualization.md) — how the comparison plots are built
