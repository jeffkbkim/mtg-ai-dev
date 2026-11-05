
import argparse
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
import time

import torch
from torch.utils.tensorboard import SummaryWriter

from engine.baselines import ActionTypePrior, evaluate, report, uniform_logits
from engine.batch_config import BatchConfig
from engine.dataset import make_loaders
from model.batch import Batch
from model.model import Model, ModelConfig
from torch.nn import functional as F
from training.plot import plot_run

@dataclass
class TrainerConfig:
    data_loader_path: Path
    epochs: int
    lr: float
    run_dir: Path  # this run's history.json, curves.png and best.pt
    seed: int = 0
    weight_decay: float = 0.0
    dropout: float | None = None  # None: keep the model's own dropout rates
    log_every: int = 500  # print the recent train loss every this many batches (0: never)
    workers: int = 4  # loader processes building batches in the background (0: the training loop builds them)

class Trainer:
    def __init__(self, trainer_config: TrainerConfig, model_config: ModelConfig) -> None:
        self.trainer_config = trainer_config
        self.model_config = model_config

        torch.manual_seed(trainer_config.seed)  # same seed -> same initial weights
        self.model = Model(
            model_config.emb_dim,
            model_config.card_feature_dim,
            model_config.ability_feature_dim,
            model_config.vocab_card,
            model_config.vocab_ability,
            model_config.vocab_actions,
            model_config.global_state_dim,
            model_config.hidden_dim,
            model_config.ffn_dim,
            model_config.num_edges,
            model_config.num_blocks
        )

        if trainer_config.dropout is not None:
            # every Dropout layer in the model, without touching the model code
            for m in self.model.modules():
                if isinstance(m, torch.nn.Dropout):
                    m.p = trainer_config.dropout

        # AdamW = Adam + weight decay applied directly to the weights; with weight_decay 0 it is plain Adam
        self.optim = torch.optim.AdamW(self.model.parameters(), lr=trainer_config.lr,
                                       weight_decay=trainer_config.weight_decay)
        self.step = 0  # batches trained so far, over all epochs
        # TensorBoard event files go in the run's own folder, so `tensorboard --logdir data/runs` shows every run
        self.tb = SummaryWriter(log_dir=str(trainer_config.run_dir))
        self.steps: list[dict] = []  # one row per periodic log, for history.json
        self.epoch_times: list[dict[str, float]] = []  # seconds per bucket (data, forward, ...), one row per epoch

    def loop(self) -> None:
        cfg = self.trainer_config
        run_start = time.perf_counter()
        loaders = make_loaders(cfg.data_loader_path, batch_size=64, seed=cfg.seed,
                               workers=cfg.workers)  # seed: train shuffle order

        # the two numbers to beat, on the same val decisions
        baselines = {"uniform": evaluate(uniform_logits, loaders["val"]),
                     "type prior": evaluate(ActionTypePrior(loaders["train"]), loaders["val"])}
        setup = time.perf_counter() - run_start  # loaders + baselines; the type prior's pass over train is most of it
        params = sum(p.numel() for p in self.model.parameters())
        self.config_lines = self.describe(params, loaders, baselines)  # printed again at the end of the run
        print("\n".join(self.config_lines))
        print()
        print(f"{'epoch':>8} | {'train loss':>10} | {'val loss':>8} | {'val acc':>7} | {'gap':>5} | {'time':>12} | "
              f"{'grad':>6} | {'weights':>7} | {'logit rms':>9} | {'lr':>7}")
        self.tb.add_text("config", "  \n".join(self.config_lines))

        best, best_epoch, best_r = float("inf"), -1, None
        history, seconds = [], []
        for epoch in range(cfg.epochs):
            start = time.time()
            train_loss, times = self.train(loaders["train"], epoch)
            val_start = time.perf_counter()
            r = self.eval(loaders["val"])
            times["val"] = time.perf_counter() - val_start
            self.epoch_times.append(times)
            val = r["all"]
            history.append((train_loss, val["loss"], val["acc"]))
            seconds.append(time.time() - start)

            mark = ""
            if val["loss"] < best:
                best, best_epoch, best_r = val["loss"], epoch, r
                self.save(epoch, r)
                mark = "  * best"
            gap = val["loss"] - train_loss  # how much worse on unseen games than on the ones it trains on
            # x axis = batches trained, the same as the periodic train points, so the curves line up
            self.tb.add_scalar("loss/train (epoch mean)", train_loss, self.step)
            self.tb.add_scalar("loss/val", val["loss"], self.step)
            self.tb.add_scalar("loss/type prior (val)", baselines["type prior"]["all"]["loss"], self.step)
            self.tb.add_scalar("val/accuracy", val["acc"], self.step)
            for kind, k in r.items():
                if kind != "all":
                    self.tb.add_scalar(f"val loss by kind/{kind}", k["loss"], self.step)
            for bucket, t in times.items():
                self.tb.add_scalar(f"time/{bucket} (s per epoch)", t, self.step)
            self.tb.flush()
            print(f"{epoch:>8} | {train_loss:>10.3f} | {val['loss']:>8.3f} | {val['acc']:>7.1%} | {gap:>5.2f} | "
                  f"{f'{time.time() - start:.1f}s':>12} | {'':>6} | {'':>7} | {'':>9} | {'':>7}{mark}")
            print(f"{'':>8}   time: " + " | ".join(f"{b} {t:.1f}s" for b, t in times.items()))

        self.summary(history, best_epoch, best_r, baselines, time.perf_counter() - run_start, setup)
        self.write_history(history, seconds, best_epoch, best_r, baselines, params)
        self.tb.close()
        print(f"curves: {plot_run(cfg.run_dir)}")

    def describe(self, params, loaders, baselines) -> list[str]:
        """The run's setup in three lines: data and training knobs, model sizes, and the baselines to beat."""
        cfg, m = self.trainer_config, self.model_config
        return [
            f"run {cfg.run_dir.name} | cache {cfg.data_loader_path} | train {len(loaders['train'].dataset):,} / "
            f"val {len(loaders['val'].dataset):,} decisions | batch {loaders['val'].batch_size} | "
            f"loader workers {cfg.workers} | lr {cfg.lr:g} | "
            f"{cfg.epochs} epochs | seed {cfg.seed} | {type(self.optim).__name__} | weight decay "
            f"{cfg.weight_decay:g} | constant lr, no grad clipping | dropout {self.dropout_label()}",
            f"model {params:,} parameters | layers {m.num_blocks} | heads 1 | hidden {m.hidden_dim} | "
            f"ffn {m.ffn_dim} | emb {m.emb_dim}",
            "parameters by part: " + " | ".join(f"{part} {n:,}" for part, n in self.params_by_part()),
            "val to beat: " + " | ".join(f"{name} {b['all']['loss']:.3f} ({b['all']['acc']:.1%})"
                                         for name, b in baselines.items()),
        ]

    def params_by_part(self) -> list[tuple[str, int]]:
        """Parameter counts per top-level module (transformer blocks one by one), largest first."""
        parts: Counter = Counter()
        for name, q in self.model.named_parameters():
            top = name.split(".")
            parts[".".join(top[:3]) if top[:2] == ["transformer", "blocks"] else top[0]] += q.numel()
        return parts.most_common()

    def write_history(self, history, seconds, best_epoch, best_r, baselines, params) -> None:
        # everything the plot needs, so an old run can be re-plotted or compared later
        cfg = self.trainer_config
        (cfg.run_dir / "history.json").write_text(json.dumps({
            "config": {"lr": cfg.lr, "epochs": cfg.epochs, "seed": cfg.seed, "weight_decay": cfg.weight_decay,
                       "dropout": self.dropout_label(), "cache": str(cfg.data_loader_path), "workers": cfg.workers,
                       "parameters": params,
                       "model": asdict(self.model_config)},
            "baselines": {name: b["all"] for name, b in baselines.items()},
            "epochs": [{"epoch": i, "train_loss": t, "val_loss": v, "val_acc": a, "seconds": s, "time": times}
                       for i, ((t, v, a), s, times) in enumerate(zip(history, seconds, self.epoch_times))],
            "steps": self.steps,
            "best_epoch": best_epoch,
            "best_val_by_kind": best_r,
        }, indent=1) + "\n")

    def summary(self, history, best_epoch, best_r, baselines, seconds, setup) -> None:
        last_train, last_val, last_acc = history[-1]
        prior = baselines["type prior"]["all"]
        print()
        print(f"done in {duration(seconds)}")
        totals = {"setup": setup}
        for times in self.epoch_times:
            for bucket, t in times.items():
                totals[bucket] = totals.get(bucket, 0.0) + t
        totals["other"] = seconds - sum(totals.values())  # logging, checkpoints, TensorBoard writes
        print(f"time: total {duration(seconds)} | " +
              " | ".join(f"{b} {duration(t)} ({t / seconds:.0%})" for b, t in totals.items()))
        print(f"best epoch {best_epoch}: val loss {best_r['all']['loss']:.3f}, acc {best_r['all']['acc']:.1%} "
              f"(type prior {prior['loss']:.3f}, {prior['acc']:.1%})")
        print(f"last epoch {len(history) - 1}: val loss {last_val:.3f}, acc {last_acc:.1%}, train loss {last_train:.3f}")
        rise = last_val - best_r["all"]["loss"]
        if rise > 0.02 and last_train < history[best_epoch][0]:
            print(f"val loss rose {rise:.3f} after epoch {best_epoch} while train loss kept falling: "
                  f"later epochs memorised, the checkpoint keeps epoch {best_epoch}")
        print()
        print("val by decision kind, best epoch:")
        print(report({**baselines, "model": best_r}))
        print()
        print(f"checkpoint: {self.trainer_config.run_dir / 'best.pt'}")
        print()
        print("\n".join(self.config_lines))  # the run's setup again: on a long run the top has scrolled away


    def train(self, batches, epoch: int) -> tuple[float, dict[str, float]]:
        
        self.model.train()
        total, n = 0.0, 0
        recent, recent_n, recent_start = 0.0, 0, time.time()  # since the last periodic log
        every = self.trainer_config.log_every
        # seconds per stage, summed over the epoch. On CPU each op finishes before the next line runs, so the
        # clock is honest; on a GPU/MPS the ops run async and these would need a synchronize before each read.
        times = {"data": 0.0, "forward": 0.0, "backward": 0.0, "stats": 0.0, "optimizer": 0.0}
        # health stats, summed per batch since the last log: gradient norm and logit RMS
        grad_sum, logit_sum, stat_n = 0.0, 0.0, 0

        t = time.perf_counter()
        for i, batch in enumerate(batches, 1):
            t0 = time.perf_counter()
            times["data"] += t0 - t  # waiting on the loader: collate, plus a new pool of files every ~1,000 batches
            logits = self.model(Batch(**batch))
            loss = F.cross_entropy(logits, batch["label"])
            t1 = time.perf_counter()
            self.optim.zero_grad()
            t2 = time.perf_counter()
            loss.backward()
            t3 = time.perf_counter()
            # before the step, so it is the gradient this update uses. One L2 norm over every parameter's gradient
            grad_sum += torch.linalg.vector_norm(
                torch.stack([q.grad.norm() for q in self.model.parameters() if q.grad is not None])).item()
            # legal actions only: the masked ones are -inf (or never scored) and would make the RMS meaningless
            logit_sum += logits.detach()[batch["action_mask"]].square().mean().sqrt().item()
            stat_n += 1
            t3s = time.perf_counter()
            self.optim.step()
            t4 = time.perf_counter()
            times["forward"] += t1 - t0
            times["optimizer"] += (t2 - t1) + (t4 - t3s)
            times["backward"] += t3 - t2
            times["stats"] += t3s - t3

            total += loss.item() * len(batch["label"])
            n += len(batch["label"])
            recent += loss.item() * len(batch["label"])
            recent_n += len(batch["label"])
            self.step += 1

            if every and self.step % every == 0:  # on the run's step, so logs land on 500, 1,000, ... every epoch
                # the mean since the last log (or the epoch's start): the epoch mean hides how the loss moves inside it
                rate = recent_n / (time.time() - recent_start)
                grad, logit_rms = grad_sum / stat_n, logit_sum / stat_n
                weights = self.weight_norm()
                lr = self.optim.param_groups[0]["lr"]  # constant today; shows a schedule if one is added
                # same columns as the epoch rows: "<epoch> <pct>" | recent train loss | blank val/acc/gap | speed
                print(f"{f'{epoch} {i / len(batches):.0%}':>8} | {recent / recent_n:>10.3f} | {'':>8} | {'':>7} | "
                      f"{'':>5} | {f'{rate:,.0f} dec/s':>12} | {grad:>6.3f} | {weights:>7.2f} | {logit_rms:>9.3f} | "
                      f"{lr:>7.0e}", flush=True)
                self.steps.append({"step": self.step, "epoch": epoch + i / len(batches),
                                   "train_loss": recent / recent_n, "grad_norm": grad, "weight_norm": weights,
                                   "logit_rms": logit_rms, "lr": lr})
                self.tb.add_scalar("loss/train (recent)", recent / recent_n, self.step)
                self.tb.add_scalar("speed/decisions per s", rate, self.step)
                self.tb.add_scalar("health/grad norm (mean per batch)", grad, self.step)
                self.tb.add_scalar("health/weight norm", weights, self.step)
                self.tb.add_scalar("health/logit rms (legal actions)", logit_rms, self.step)
                self.tb.add_scalar("health/lr", lr, self.step)
                recent, recent_n, recent_start = 0.0, 0, time.time()
                grad_sum, logit_sum, stat_n = 0.0, 0.0, 0
            t = time.perf_counter()

        return total / n, times

    @torch.no_grad()
    def weight_norm(self) -> float:
        """One L2 norm over every parameter: steady growth = weights drifting, a jump = instability."""
        return torch.linalg.vector_norm(torch.stack([q.norm() for q in self.model.parameters()])).item()

    def eval(self, loader) -> dict[str, dict[str, float]]:
        self.model.eval()
        return evaluate(lambda b: self.model(Batch(**b)), loader)

    def dropout_label(self) -> str:
        rates = sorted({m.p for m in self.model.modules() if isinstance(m, torch.nn.Dropout)})
        return "/".join(f"{p:g}" for p in rates) or "none"

    def save(self, epoch: int, r: dict[str, dict[str, float]]) -> None:
        # the weights plus what's needed to rebuild the model and know which epoch this was
        path = self.trainer_config.run_dir / "best.pt"
        torch.save({
            "model": self.model.state_dict(),
            "model_config": asdict(self.model_config),
            "epoch": epoch,
            "val": r["all"],
        }, path)


def duration(seconds: float) -> str:
    """12.3s under a minute, else 17m31s."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}m{secs:02d}s"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=Path("data/cache/claude-v1"))
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--runs", type=Path, default=Path("data/runs"), help="each run gets its own folder here")
    parser.add_argument("--name", default="", help="added to the run folder's name, e.g. wd0.01")
    parser.add_argument("--seed", type=int, default=0, help="initial weights and train shuffle order")
    parser.add_argument("--weight-decay", type=float, default=0.0)
    parser.add_argument("--dropout", type=float, default=None, help="set every Dropout layer to this rate")
    parser.add_argument("--workers", type=int, default=4,
                        help="loader processes that build batches in the background (0: none)")
    parser.add_argument("--layers", type=int, default=1, help="transformer layers (blocks)")
    parser.add_argument("--log-every", type=int, default=500, help="print the recent train loss every N batches (0: off)")
    args = parser.parse_args()

    # sizes that must match the cache come from the vocab and the encoder, so they can't drift apart
    cfg = BatchConfig.from_vocab()
    model_config = ModelConfig(
        emb_dim=16,
        card_feature_dim=cfg.card_feature_dim,
        ability_feature_dim=cfg.ability_feature_dim,
        vocab_card=cfg.vocab_card,
        vocab_ability=cfg.vocab_ability,
        vocab_actions=cfg.vocab_action,
        global_state_dim=cfg.global_state_dim,
        hidden_dim=32,
        ffn_dim=64,
        num_edges=cfg.num_edge_types,
        num_blocks=args.layers,
    )
    run_dir = args.runs / (datetime.now().strftime("%Y-%m-%d_%H%M%S") + (f"_{args.name}" if args.name else ""))
    run_dir.mkdir(parents=True)
    trainer_config = TrainerConfig(args.cache, args.epochs, args.lr, run_dir, args.seed, args.weight_decay,
                                   args.dropout, args.log_every, args.workers)
    Trainer(trainer_config, model_config).loop()


if __name__ == "__main__":
    main()
