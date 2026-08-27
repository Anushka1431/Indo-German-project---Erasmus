"""
Cross-country Pareto comparison for the 5-scenario matrix (see the
`scenarios` dict in new_model_both3.py for the full rationale). Facets by
country so each panel stays readable: 5 scenario lines x 2 countries x 2
chart framings (cost-under-emissions-cap, emissions-under-budget-cap).

A = linear baseline, C = reuse-led (best overall strategy) -- both now have
recycling structurally disabled (recycling_available=False), so they
represent what reuse/refurbishment policy alone can achieve. R_None /
R_Bulk / R_HighValue are a controlled triplet at fixed low reuse/refurb
levels (5%/20%): R_None has no recycling facility at all, R_Bulk and
R_HighValue add it back at two technology levels. R_None->R_Bulk isolates
whether recycling helps at all (verified: ~17.5% cost reduction at Germany
cost-min); R_Bulk->R_HighValue isolates the technology choice specifically
(~9.9% further reduction).
"""
import os
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

CSV_DIR = "outputs/pareto_csv"
PLOTS_DIR = "outputs/plots"
COUNTRIES = ["Germany", "India"]

SCENARIOS = {
    "A":           {"label": "A: Linear (Baseline)",         "file_key": "Linear_Like",          "color": "#d62728"},
    "C":           {"label": "C: Consumer Reuse",             "file_key": "Consumer_Reuse",       "color": "#2ca02c"},
    "R_None":      {"label": "Recycling: None (control)",     "file_key": "Recycling_None",       "color": "#7f7f7f"},
    "R_Bulk":      {"label": "Recycling: Bulk Tech",          "file_key": "Recycling_Bulk",       "color": "#1f77b4"},
    "R_HighValue": {"label": "Recycling: High-Value Tech",    "file_key": "Recycling_HighValue",  "color": "#ff7f0e"},
}


def format_billions(x, pos):
    return f"{x*1e-9:.1f}B"


def load_curated_data():
    data = {}
    missing = []
    for country in COUNTRIES:
        for key, meta in SCENARIOS.items():
            cost_path = f"{CSV_DIR}/Pareto_{country}_{meta['file_key']}_CostMin.csv"
            env_path = f"{CSV_DIR}/Pareto_{country}_{meta['file_key']}_EnvMin.csv"
            if not (os.path.exists(cost_path) and os.path.exists(env_path)):
                missing.append((country, key))
                continue
            data[(country, key)] = {
                "c_min": pd.read_csv(cost_path).sort_values("epsilon_env"),
                "e_min": pd.read_csv(env_path).sort_values("epsilon_cost"),
            }
    if missing:
        print(f"Warning: missing CSVs for {missing} -- run new_model_both3.py first.")
    return data


def plot_curated_grid(data):
    fig, axes = plt.subplots(2, len(COUNTRIES), figsize=(7 * len(COUNTRIES), 11), sharex=False, sharey=False)

    for col, country in enumerate(COUNTRIES):
        # Row 0: cost-minimising curve -- "if we cap emissions at eps, what's the cheapest cost?"
        ax = axes[0, col]
        for key, meta in SCENARIOS.items():
            if (country, key) not in data:
                continue
            df = data[(country, key)]["c_min"]
            ax.plot(df["epsilon_env"], df["cost"], marker="o", linewidth=2.5, markersize=5,
                    label=meta["label"], color=meta["color"])
        ax.xaxis.set_major_formatter(plt.FuncFormatter(format_billions))
        ax.yaxis.set_major_formatter(plt.FuncFormatter(format_billions))
        ax.set_xlabel("Emission Limit (kg CO2e) [Constraint]", fontsize=10, fontweight="bold")
        ax.set_ylabel("Minimum Total Cost (EUR) [Objective]", fontsize=10, fontweight="bold")
        ax.set_title(f"{country}: Cost of Sustainability", fontsize=12)
        ax.grid(True, linestyle="--", alpha=0.6)

        # Row 1: env-minimising curve -- "if we cap budget at eps, what's the lowest emissions?"
        ax = axes[1, col]
        for key, meta in SCENARIOS.items():
            if (country, key) not in data:
                continue
            df = data[(country, key)]["e_min"]
            ax.plot(df["epsilon_cost"], df["env"], marker="s", linewidth=2.5, markersize=5,
                    label=meta["label"], color=meta["color"])
        ax.xaxis.set_major_formatter(plt.FuncFormatter(format_billions))
        ax.yaxis.set_major_formatter(plt.FuncFormatter(format_billions))
        ax.set_xlabel("Budget Limit (EUR) [Constraint]", fontsize=10, fontweight="bold")
        ax.set_ylabel("Minimum Emissions (kg CO2e) [Objective]", fontsize=10, fontweight="bold")
        ax.set_title(f"{country}: Environmental Efficiency of Budget", fontsize=12)
        ax.grid(True, linestyle="--", alpha=0.6)

    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=len(SCENARIOS), fontsize=11,
               bbox_to_anchor=(0.5, -0.02))
    fig.suptitle("Circular PV Supply Chain: Cost-Environment Trade-offs, Germany vs. India",
                 fontsize=14, y=0.995)
    fig.tight_layout(rect=[0, 0.04, 1, 0.97])

    out_path = f"{PLOTS_DIR}/Comparison_Curated_Germany_vs_India.png"
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    sns.set_style("whitegrid")
    os.makedirs(PLOTS_DIR, exist_ok=True)
    data = load_curated_data()
    plot_curated_grid(data)
