"""Run a big turn replay as many small batches over one sample, on several workers, resumable.

  uv run --group data python seventeenlands/replay_batches.py --name dsk50k --sample 50000 --seed 5001 [--batch 500] [--workers 3]

One seeded sample of --sample games is cut into batches of --batch games; batch b replays games [b*batch, (b+1)*batch)
of the sorted sample (turn_replay.py --sample/--offset), so no game is replayed twice. Workers take the
unfinished batches from one queue. Each batch is its own run directory, turn_replay/<name>/b0000, so a crash costs
one batch; a batch with a summary.json is done and is skipped when the command is run again. Progress goes to
turn_replay/<name>/progress.log. Stop it with `kill <driver pid>`: running batches are killed and rerun next time.
"""
import argparse, signal, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = Path.home() / "mtg-data/17lands/DSK/turn_replay"
RUNNING, STOP, LOCK = set(), threading.Event(), threading.Lock()


def worker(job):
    a, w, todo = job
    nb = -(-a.sample // a.batch)
    while not STOP.is_set():
        with LOCK:
            if not todo:
                return
            b = todo.pop(0)
        run = f"{a.name}/b{b:04d}"
        games = min(a.batch, a.sample - b * a.batch)
        cmd = [sys.executable, str(HERE / "turn_replay.py"), "--games", str(games), "--sample", str(a.sample),
               "--offset", str(b * a.batch), "--seed", str(a.seed), "--run", run, "--classes", a.classes] + a.extra
        t = time.time()
        (DATA / run).mkdir(parents=True, exist_ok=True)
        with open(DATA / run / "stdout.log", "w") as log:
            p = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=HERE.parent, start_new_session=True)
            RUNNING.add(p)
            code = p.wait()
            RUNNING.discard(p)
        with open(DATA / a.name / "progress.log", "a") as p:
            p.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} worker {w} batch {b}/{nb} games {games} exit {code} "
                    f"{time.time() - t:.0f}s\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True)
    ap.add_argument("--sample", type=int, required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--batch", type=int, default=500)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--classes", default=str(Path.home() / "mtg-data/xmage-cls-replay"))
    ap.add_argument("extra", nargs="*", help="passed on to turn_replay.py after --, e.g. -- --probe 30 --rows")
    a = ap.parse_args()
    (DATA / a.name).mkdir(parents=True, exist_ok=True)
    # no heavy jobs alongside each other (AGENTS.md): if the nightly soak (~2.5 h) is running, wait for it to end
    # anchored on the python executable: a shell whose command text merely mentions soak.py must not count
    while subprocess.run(["pgrep", "-f", r"^[^ ]*python[0-9.]* [^ ]*coverage_soak/soak\.py"], capture_output=True).returncode == 0:
        with open(DATA / a.name / "progress.log", "a") as p:
            p.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} waiting: the nightly soak is running\n")
        time.sleep(600)
    def stop(*_):   # kill -TERM <driver pid> stops everything; the unfinished batches rerun next time
        STOP.set()
        for p in list(RUNNING):
            subprocess.run(["pkill", "-TERM", "-g", str(p.pid)])
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    nb = -(-a.sample // a.batch)
    todo = [b for b in range(nb) if not (DATA / f"{a.name}/b{b:04d}" / "summary.json").exists()]
    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(worker, [(a, w, todo) for w in range(a.workers)]))


if __name__ == "__main__":
    main()
