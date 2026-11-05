"""Several runs on one chart, plus a table of their best epochs.

    uv run python -m training.compare data/runs/*_seed*            # e.g. the 3 seed runs
    uv run python -m training.compare data/runs/A data/runs/B --out data/runs/wd-vs-base.png

Each run keeps one colour in both panels: val loss on the left, train loss on the right.
"""

import argparse
import json
import statistics
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

from training.plot import INK, MUTED, SURFACE, _baseline, _style, settings

# fixed order, one per run; more than 8 runs on one chart is unreadable anyway
COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]


def load(run_dir: Path) -> dict:
    h = json.loads((run_dir / "history.json").read_text())
    h["name"] = run_dir.name
    h["label"] = run_dir.name[18:] or run_dir.name  # drop the "2026-10-29_133259_" prefix when the run has a --name
    return h


def compare(run_dirs: list[Path], out: Path) -> Path:
    runs = [load(d) for d in run_dirs][: len(COLORS)]
    fig, (val_ax, train_ax) = plt.subplots(1, 2, figsize=(11, 4.2), facecolor=SURFACE, sharey=True)
    _style(val_ax, "Val loss", "cross-entropy")
    _style(train_ax, "Train loss", "")
    for color, h in zip(COLORS, runs):
        epochs = [e["epoch"] for e in h["epochs"]]
        val_ax.plot(epochs, [e["val_loss"] for e in h["epochs"]], color=color, linewidth=2, label=h["label"])
        train_ax.plot(epochs, [e["train_loss"] for e in h["epochs"]], color=color, linewidth=2)
        b = h["epochs"][h["best_epoch"]]
        val_ax.plot([h["best_epoch"]], [b["val_loss"]], marker="o", markersize=7, markerfacecolor=color,
                    markeredgecolor=SURFACE, markeredgewidth=2)
    _baseline(val_ax, runs[0]["baselines"]["type prior"]["loss"], "type prior")
    for ax in (val_ax, train_ax):
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    fig.legend(*val_ax.get_legend_handles_labels(), frameon=False, loc="lower center", ncol=min(len(runs), 4),
               labelcolor=INK, fontsize=9)
    fig.suptitle("dots: each run's best epoch (its checkpoint)", x=0.01, ha="left", color=MUTED, fontsize=9)
    fig.tight_layout(rect=(0, 0.08 * ((len(runs) + 3) // 4), 1, 1))  # room for the legend rows
    fig.savefig(out, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    return out


def table(run_dirs: list[Path]) -> str:
    rows = [f"{'run':<40} {'best epoch':>10} {'val loss':>9} {'val acc':>8}   settings"]
    bests = []
    for d in run_dirs:
        h = load(d)
        b = h["epochs"][h["best_epoch"]]
        bests.append(b["val_loss"])
        rows.append(f"{h['name']:<40} {h['best_epoch']:>10} {b['val_loss']:>9.3f} {b['val_acc']:>8.1%}   "
                    f"{settings(h['config'])}")
    if len(bests) > 1:
        rows.append(f"best val loss: mean {statistics.mean(bests):.3f}, spread (max - min) {max(bests) - min(bests):.3f}, "
                    f"std {statistics.stdev(bests):.3f}")
    return "\n".join(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, default=Path("data/runs/compare.png"))
    args = ap.parse_args()
    print(table(args.runs))
    print(f"chart: {compare(args.runs, args.out)}")
