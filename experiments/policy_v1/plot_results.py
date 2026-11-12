"""Figure for the policy v1 results, drawn from the committed result files only.

    uv run python experiments/policy_v1/plot_results.py

Reads heldout-200-l1.json and games-200-l1-2026-11-05.json next to this file and writes results-200-l1.png.
Left: held-out top-1 agreement per decision kind against the two non-learned baselines.
Right: win rate over 400 seat-balanced games per matchup, with 95% Wilson intervals.
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

HERE = Path(__file__).parent
HELDOUT = HERE / "heldout-200-l1.json"
GAMES = HERE / "games-200-l1-2026-11-05.json"
OUT = HERE / "results-200-l1.png"

# Same palette as training/plot.py.
POLICY = "#2a78d6"  # blue
PRIOR = "#eb6834"  # orange
BASELINE = "#b5b3aa"  # gray: the random bot / random-legal reference
INK = "#0b0b0b"
MUTED = "#6f6d66"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SURFACE = "#fcfcfb"

KINDS = ["all", "PRIORITY", "ATTACK", "USE", "BLOCK", "TARGET"]
SERIES = [  # (key in results, legend label, color)
    ("uniform", "random legal", BASELINE),
    ("kind+type prior", "most-frequent prior", PRIOR),
    ("policy", "policy v1", POLICY),
]


def _style(ax, title: str) -> None:
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", color=INK, fontsize=11)
    ax.grid(True, axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=MUTED, length=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)


def plot_heldout(ax, heldout: dict) -> None:
    results = heldout["results"]
    height = 0.26
    gap = 0.03
    for i, (key, label, color) in enumerate(SERIES):
        series = results[key]
        for row, kind in enumerate(KINDS):
            y = row + (i - 1) * (height + gap)
            acc = series[kind]["acc"]
            ax.barh(y, acc, height=height, color=color, label=label if row == 0 else None)
            if key == "policy":
                ax.text(acc + 0.012, y, f"{acc:.1%}", va="center", fontsize=8.5, color=INK)
    ax.set_yticks(range(len(KINDS)))
    ax.set_yticklabels([f"{k.lower()}  (n={results['uniform'][k]['n']:,})" for k in KINDS], color=INK, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlim(0, 1.04)
    ax.xaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    _style(ax, "Held-out move agreement (top-1), test split")
    ax.legend(loc="upper center", bbox_to_anchor=(0.45, -0.1), ncol=3, frameon=False, fontsize=9, labelcolor=INK)


def plot_games(ax, games: list) -> None:
    names = {"random": "random bot", "xmage": "XMage AI"}
    rows = []
    for run in games:
        a = "policy v1" if run["policy"] != "random" else "random bot"
        rows.append((f"{a} vs {names[run['opponent']]}", run))
    for y, (label, run) in enumerate(rows):
        lo, hi = run["wilson95"]
        p = run["win_rate"]
        color = POLICY if run["policy"] != "random" else BASELINE
        ax.plot([lo, hi], [y, y], color=color, linewidth=2, solid_capstyle="round")
        ax.plot(p, y, "o", markersize=8, color=color, markeredgecolor=SURFACE, markeredgewidth=2)
        ax.text(hi + 0.015, y, f"{p:.1%}  ({run['wins']}-{run['losses']})", va="center", fontsize=8.5, color=INK)
    ax.axvline(0.5, color=AXIS, linewidth=1, linestyle=(0, (3, 3)))
    ax.text(0.505, len(rows) - 0.55, "even", color=MUTED, fontsize=8, va="bottom")
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in rows], color=INK, fontsize=9)
    ax.invert_yaxis()
    ax.set_ylim(len(rows) - 0.4, -0.6)
    ax.set_xlim(0, 0.65)
    ax.xaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    _style(ax, "Win rate, 400 seat-balanced games each (95% CI)")


def main() -> None:
    heldout = json.loads(HELDOUT.read_text())
    games = json.loads(GAMES.read_text())
    fig, (left, right) = plt.subplots(
        1, 2, figsize=(12.5, 4.8), gridspec_kw={"width_ratios": [1.15, 1]}, facecolor=SURFACE
    )
    plot_heldout(left, heldout)
    plot_games(right, games)
    fig.tight_layout(w_pad=3)
    fig.savefig(OUT, dpi=160, facecolor=SURFACE)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
