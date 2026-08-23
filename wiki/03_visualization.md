# Visualization — `new_plot_pareto2.py`

## Purpose

Loads the 8 Pareto CSVs produced by `new_model_both3.py` (2 per scenario × 4 scenarios) and
renders **2 cross-scenario comparison charts**, each answering a different framing of the
cost/environment trade-off.

## Input mapping

```python
files = {
  "A": {"name": "Scenario A: Linear (Baseline)",       "color": "#d62728",
        "cost_min_csv": "Pareto_Linear_Like_CostMin.csv",
        "env_min_csv":  "Pareto_Linear_Like_EnvMin.csv"},
  "B": {"name": "Scenario B: Industrial Refurb",        "color": "#1f77b4", ...},
  "C": {"name": "Scenario C: Consumer Reuse",           "color": "#2ca02c", ...},
  "D": {"name": "Scenario D: Ideal Balanced Circular",  "color": "#9467bd", ...},
}
```

`load_data()` reads all 8 CSVs into a dict keyed by scenario letter, each holding:
- `c_min` → the `_CostMin.csv` (Curve A: cost minimized under an emissions cap)
- `e_min` → the `_EnvMin.csv` (Curve B: emissions minimized under a budget cap)
- `meta` → display name and color

If any file is missing, `load_data()` prints an error and returns `None` (plotting is skipped).

## Chart 1 — `plot_perspective_env_on_x()` → `Comparison_1_Env_on_X.png`

**Question answered:** "If we enforce an emission limit (X), what is the minimum cost (Y)?"

- Uses each scenario's `c_min` (Curve A) data, sorted by `epsilon_env`.
- X = `epsilon_env` (emission cap, kg CO2e), Y = `cost` (€), one line per scenario.
- Axis labels formatted in billions (`format_billions`: `x*1e-9` with a "B" suffix).

## Chart 2 — `plot_perspective_cost_on_x()` → `Comparison_2_Cost_on_X.png`

**Question answered:** "If we have a budget limit (X), what is the minimum environmental impact (Y)?"

- Uses each scenario's `e_min` (Curve B) data, sorted by `epsilon_cost`.
- X = `epsilon_cost` (budget cap, €), Y = `env` (kg CO2e), one line per scenario.
- Same billions-formatted axes.

## Why two charts instead of one

The two Pareto curves per scenario (Curve A vs Curve B, see
[02_optimization_model.md](02_optimization_model.md)) are each better suited to answering one
direction of the question — Curve A directly gives cost-as-a-function-of-emission-cap, Curve B
directly gives emissions-as-a-function-of-budget-cap. Plotting both lets a reader pick whichever
framing (environmental regulation vs. budget constraint) matches their decision context.

## Styling
- `seaborn.set_style("whitegrid")` applied globally before plotting.
- Fixed color per scenario (consistent across both charts) for easy visual comparison.
- Saved at 300 DPI via `plt.savefig(..., dpi=300)`.

## See also
- [02_optimization_model.md](02_optimization_model.md) — how the underlying CSVs are generated
- [00_overview.md](00_overview.md) — full pipeline and how to run both scripts
