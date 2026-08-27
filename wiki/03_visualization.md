# Visualization — `plot_pareto_curated.py` (current) and `new_plot_pareto2.py` (historical)

## Current: `plot_pareto_curated.py`

### Purpose

Reads the current 20 CSVs (`outputs/pareto_csv/Pareto_<Country>_<Scenario>_{CostMin,EnvMin}.csv`,
2 countries × 5 scenarios × 2 curves) and renders **one 2×2 comparison figure**
(`outputs/plots/Comparison_Curated_Germany_vs_India.png`): rows = chart framing (cost-under-
emissions-cap vs. emissions-under-budget-cap), columns = country (Germany, India). Each panel
overlays all 5 scenario lines.

### Why all 5 scenarios, not a subset

Earlier passes tried showing only 4 (dropping one as visually redundant), but once the scenario
matrix was corrected to the current controlled-triplet design (`A`, `C`, `R_None`, `R_Bulk`,
`R_HighValue` — see [02_optimization_model.md](02_optimization_model.md) for the full story of why
the *previous* 4-scenario sets had redundant or confounded lines), none of the 5 remaining
scenarios are redundant with each other, so all 5 are shown.

### Input mapping

```python
SCENARIOS = {
    "A":           {"label": "A: Linear (Baseline)",      "file_key": "Linear_Like",         "color": "#d62728"},
    "C":           {"label": "C: Consumer Reuse",          "file_key": "Consumer_Reuse",      "color": "#2ca02c"},
    "R_None":      {"label": "Recycling: None (control)",  "file_key": "Recycling_None",      "color": "#7f7f7f"},
    "R_Bulk":      {"label": "Recycling: Bulk Tech",       "file_key": "Recycling_Bulk",      "color": "#1f77b4"},
    "R_HighValue": {"label": "Recycling: High-Value Tech", "file_key": "Recycling_HighValue", "color": "#ff7f0e"},
}
```

`load_curated_data()` reads, per (country, scenario), the `_CostMin.csv` (`c_min`, sorted by
`epsilon_env`) and `_EnvMin.csv` (`e_min`, sorted by `epsilon_cost`). Missing files are logged as
a warning, not a hard failure (unlike the model script's validation suite) — this script assumes
`new_model_both3.py` has already been run successfully.

### Layout — `plot_curated_grid()`

- **Row 0** (`ax = axes[0, col]`): `c_min` data, X = `epsilon_env` (emission cap), Y = `cost`.
  "If we enforce an emission limit, what's the minimum cost?"
- **Row 1** (`ax = axes[1, col]`): `e_min` data, X = `epsilon_cost` (budget cap), Y = `env`.
  "If we have a budget limit, what's the minimum environmental impact?"
- One column per country, shared legend at the figure bottom (`fig.legend`, deduplicated from the
  top-left panel's handles).
- Axis labels in billions (`format_billions`: `x*1e-9` + `"B"` suffix) — every axis in this model
  is in the billions given the ~3.2 GWp instance size.

### What the current chart actually shows (as of the latest run)

In Germany's panels, the intended ordering from the controlled triplet is visible in the
mid-range: `R_None` (gray, no recycling) sits worst, `R_Bulk` (blue) better, `R_HighValue`
(orange) best — converging together only at the tightest emissions cap, where all three get
forced into the same aggressive configuration regardless of technology. `C` (green) remains the
overall best performer; `A` (red) is a separate reference point at different reuse/refurb levels,
not meant to align with the triplet.

India's panels show the same lines much closer together — not a bug (see
[02_optimization_model.md](02_optimization_model.md)'s note on the `recycle_share` diagnostic bug
that initially made this look more dramatic than it is): recycling activates to a comparable
~76% share in India too, and the technology-choice gap is real (~4.4% at the loosest constraint)
but proportionally smaller than Germany's (~9.9%), because India's overall cost/emissions baseline
is larger, compressing the visual separation on the same axes. A follow-up worth doing if this
matters for the paper: normalize each country's curves to its own scenario-`A` value so the
proportionally-similar-but-numerically-smaller effect doesn't read as "nothing happening."

### Styling
`seaborn.set_style("whitegrid")`, fixed color per scenario (consistent across both rows/columns),
saved at 300 DPI, `bbox_inches="tight"`.

---

## Historical: `new_plot_pareto2.py`

Original Germany-only, 4-scenario (A–D, pre-recycling-echelon) plotting script. Reads the 8
historical CSVs (`Pareto_Linear_Like_*.csv` etc., no country prefix) still sitting in
`outputs/pareto_csv/` alongside the current 20. Produces `Comparison_1_Env_on_X.png` (cost vs.
emission cap) and `Comparison_2_Cost_on_X.png` (emissions vs. budget cap) in `outputs/plots/`.
Kept for reference/reproducibility of the original thesis figures — **not part of the current
pipeline**, and its 4-scenario matrix (`Linear_Like`, `Industrial_Refurb`, `Consumer_Reuse`,
`Ideal_Balanced_Circular`) no longer matches `new_model_both3.py`'s current scenario dict.

## See also
- [02_optimization_model.md](02_optimization_model.md) — how the underlying CSVs are generated, the current scenario matrix, and why it changed
- [00_overview.md](00_overview.md) — full pipeline and how to run both scripts
