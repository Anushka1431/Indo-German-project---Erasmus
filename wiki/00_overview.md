# Project Overview — Germany PV Circular Economy Optimization

## What this project does

This codebase models the **solar photovoltaic (PV) panel supply chain in Germany**, including
end-of-life flows (reuse, refurbishment, landfill), and solves a **bi-objective optimization
problem**: minimize total **cost (€)** vs. minimize total **environmental impact (kg CO2e)**.

It compares **4 circular-economy scenarios** that differ in how much of the returned/end-of-life
panel volume can be reused vs. refurbished, and how efficient refurbishment is. For each
scenario it traces out a **Pareto frontier** (the cost/environment trade-off curve) using the
ε-constraint method, and produces comparison plots across scenarios.

## Files in this repo

| File | Role |
|---|---|
| `new_model_both3.py` | Core optimization model. Builds and solves the Gurobi MILP for each scenario, generates Pareto curves, writes CSVs. |
| `new_plot_pareto2.py` | Reads the CSVs produced by the model script and renders comparison charts (PNG). |
| `Germany_data_v2_1512.xlsx` | All input data: network sets, costs, demand, capacities, revenues, transportation distances, environmental factors, supplier bill-of-materials. |
| `Pareto_*_CostMin.csv`, `Pareto_*_EnvMin.csv` | Model outputs — 2 CSVs per scenario × 4 scenarios = 8 files. |
| `Comparison_1_Env_on_X.png`, `Comparison_2_Cost_on_X.png` | Final charts comparing all scenarios. |
| `requirenments.txt` | Python dependencies (note: filename is misspelled "requirenments"). |

> Note: `requirenments.txt` lists `math` as a pip dependency — `math` is a Python standard-library
> module, not an installable package, so that line is a no-op/mistake and can be ignored or removed.

## How the pieces connect (pipeline)

```
Germany_data_v2_1512.xlsx
        │
        ▼
new_model_both3.py   (per scenario: build MILP, solve payoff table, trace 2 Pareto curves)
        │
        ▼
Pareto_<Scenario>_CostMin.csv   +   Pareto_<Scenario>_EnvMin.csv     (one pair per scenario)
        │
        ▼
new_plot_pareto2.py   (loads all scenario CSVs, draws 2 cross-scenario comparison plots)
        │
        ▼
Comparison_1_Env_on_X.png   +   Comparison_2_Cost_on_X.png
```

## Running it

```bash
pip install -r requirenments.txt   # (fix "math" line first / gurobipy needs a license)
python new_model_both3.py          # produces 8 CSVs (2 per scenario x 4 scenarios)
python new_plot_pareto2.py         # produces 2 PNG comparison charts
```

`gurobipy` requires a valid Gurobi license (free academic licenses available) to solve anything
beyond trivial model sizes.

## See also
- [01_data_schema.md](01_data_schema.md) — Excel input schema and how columns map to model symbols
- [02_optimization_model.md](02_optimization_model.md) — deep dive on the MILP: sets, variables, constraints, objectives, Pareto method
- [03_visualization.md](03_visualization.md) — how the comparison plots are built
