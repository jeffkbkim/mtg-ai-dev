"""Loss and accuracy curves for one training run.

    uv run python -m training.plot data/runs/2026-10-29_033000     # re-plot a saved run

The trainer calls plot_run() at the end of every run, so curves.png sits next to history.json.
"""

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # write files only, no window
import matplotlib.pyplot as plt
import matplotlib.ticker
from matplotlib.ticker import MaxNLocator

TRAIN = "#2a78d6"  # blue
VAL = "#eb6834"  # orange
INK = "#0b0b0b"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SURFACE = "#fcfcfb"


def _style(ax, title: str, ylabel: str) -> None:
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", color=INK, fontsize=11)
    ax.set_xlabel("epoch", color=MUTED)
    ax.set_ylabel(ylabel, color=MUTED)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=MUTED)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXIS)


def _baseline(ax, y: float, label: str) -> None:
    """A dashed reference line, labelled at its right end."""
    ax.axhline(y, color=MUTED, linewidth=1, linestyle=(0, (4, 3)))
    ax.annotate(label, (1, y), xycoords=("axes fraction", "data"), xytext=(-4, 4), textcoords="offset points",
                ha="right", va="bottom", color=MUTED, fontsize=9)


def settings(c: dict) -> str:
    """The knobs that differ between runs, as one short label."""
    return (f"lr {c['lr']:g}, seed {c.get('seed', 0)}, wd {c.get('weight_decay', 0):g}, "
            f"dropout {c.get('dropout', '?')}")


def plot_run(run_dir: Path) -> Path:
    h = json.loads((Path(run_dir) / "history.json").read_text())
    epochs = [e["epoch"] for e in h["epochs"]]
    best = h["best_epoch"]
    best_row = h["epochs"][best]

    fig, (loss_ax, acc_ax) = plt.subplots(1, 2, figsize=(11, 4.2), facecolor=SURFACE)

    _style(loss_ax, "Loss (lower is better)", "cross-entropy")
    loss_ax.plot(epochs, [e["train_loss"] for e in h["epochs"]], color=TRAIN, linewidth=2, marker="o", markersize=3,
                 label="train")
    loss_ax.plot(epochs, [e["val_loss"] for e in h["epochs"]], color=VAL, linewidth=2, marker="o", markersize=3,
                 label="val")
    for name, b in h["baselines"].items():
        _baseline(loss_ax, b["loss"], f"{name} (val)")

    _style(acc_ax, "Val accuracy (higher is better)", "accuracy")
    acc_ax.plot(epochs, [e["val_acc"] for e in h["epochs"]], color=VAL, linewidth=2, marker="o", markersize=3,
                label="val")
    for name, b in h["baselines"].items():
        _baseline(acc_ax, b["acc"], name)
    acc_ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    for ax in (loss_ax, acc_ax):
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))

    # the checkpoint the run kept
    for ax, y in ((loss_ax, best_row["val_loss"]), (acc_ax, best_row["val_acc"])):
        ax.axvline(best, color=AXIS, linewidth=1)
        ax.plot([best], [y], marker="o", markersize=9, markerfacecolor="none", markeredgecolor=INK,
                markeredgewidth=1.5)
        ax.annotate(f"best epoch {best}", (best, y), xytext=(6, -14), textcoords="offset points", color=INK,
                    fontsize=9)

    loss_ax.legend(frameon=False, loc="lower left", labelcolor=INK)
    c = h["config"]
    fig.suptitle(f"{Path(run_dir).name}   {settings(c)}, {len(epochs)} epochs, {c['parameters']:,} parameters",
                 x=0.01, ha="left", color=MUTED, fontsize=9)
    fig.tight_layout()
    out = Path(run_dir) / "curves.png"
    fig.savefig(out, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    return out


if __name__ == "__main__":
    print(plot_run(Path(sys.argv[1])))
