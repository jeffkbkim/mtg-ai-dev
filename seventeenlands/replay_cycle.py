"""Keep the 17lands DSK turn replay going on the mini, one 50k-game run after another (for a scheduled task).

  uv run --group data python seventeenlands/replay_cycle.py status    # JSON: the current run and anything wrong
  uv run --group data python seventeenlands/replay_cycle.py report    # summary of the newest finished run, as markdown
  uv run --group data python seventeenlands/replay_cycle.py resume    # restart the current run's driver (skips done batches)
  uv run --group data python seventeenlands/replay_cycle.py next      # start the next run: new seed, skips every game done

Runs live in ~/mtg-data/17lands/DSK/turn_replay/dsk50k, dsk50k-2, dsk50k-3, ... Run n uses seed 5000+n and excludes
every game of the runs before it, so no game is replayed twice. Each run dir has README.txt (command, code, how to
stop), progress.log (one line per finished batch), metrics.log (memory, swap, load each minute, from monitor.sh).
"""
import json, re, subprocess, sys, time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TR = Path.home() / "mtg-data/17lands/DSK/turn_replay"
BATCHES = 100
SLOW_HOURS = 2.5          # a batch normally takes about an hour
JAVA = "/opt/homebrew/opt/openjdk@21/bin"


def runs():
    def n(p):
        m = re.fullmatch(r"dsk50k(?:-(\d+))?", p.name)
        return int(m.group(1) or 1) if m else None
    return sorted((n(p), p) for p in TR.glob("dsk50k*") if p.is_dir() and n(p))


def done(d: Path) -> int:
    return len(list(d.glob("b*/summary.json")))


def driver_running(name: str) -> bool:
    return subprocess.run(["pgrep", "-f", f"replay_batches.py --name {name}( |$)"], capture_output=True).returncode == 0


def etimes() -> list[tuple[int, str]]:
    """(seconds running, run/offset) for each running turn_replay.py."""
    out = subprocess.run(["ps", "-axo", "etime=,command="], capture_output=True, text=True).stdout
    res = []
    for line in out.splitlines():
        if "turn_replay.py" not in line or "grep" in line:
            continue
        et, cmd = line.strip().split(" ", 1)
        d, _, hms = et.rpartition("-")
        parts = [int(x) for x in hms.split(":")]
        while len(parts) < 3:
            parts.insert(0, 0)
        secs = (int(d) if d else 0) * 86400 + parts[0] * 3600 + parts[1] * 60 + parts[2]
        m = re.search(r"--run (\S+)", cmd)
        res.append((secs, m.group(1) if m else cmd[:80]))
    return res


def last_metrics(d: Path) -> dict:
    f = d / "metrics.log"
    if not f.exists():
        return {}
    lines = f.read_text().splitlines()
    last = next((l for l in reversed(lines) if "free=" in l), "")
    m = dict(re.findall(r"(\w+)=([\d.]+)", last))
    first = next((l for l in lines if "swap=" in l), "")
    m0 = dict(re.findall(r"(\w+)=([\d.]+)", first))
    return {"line": last, "free": int(m.get("free", 100)), "swap_mb": int(m.get("swap", 0)),
            "swap_growth_mb": int(m.get("swap", 0)) - int(m0.get("swap", 0) or 0)}


def status() -> dict:
    n, d = runs()[-1]
    s = {"run": d.name, "n": n, "batches_done": done(d), "batches": BATCHES, "driver_running": driver_running(d.name),
         "problems": []}
    s.update(metrics=last_metrics(d))
    prog = (d / "progress.log").read_text().splitlines() if (d / "progress.log").exists() else []
    s["last_progress"] = prog[-1] if prog else None
    s["failed_batches"] = sorted({int(m.group(1)) for l in prog if (m := re.search(r"batch (\d+)/\d+ .* exit (-?\d+)", l))
                                  and m.group(2) != "0"} - {int(p.parent.name[1:]) for p in d.glob("b*/summary.json")})
    slow = [(t, r) for t, r in etimes() if t > SLOW_HOURS * 3600]
    if slow:
        s["problems"].append(f"batch running over {SLOW_HOURS} h (stall?): {slow}")
    if not s["driver_running"] and s["batches_done"] < BATCHES:
        s["problems"].append(f"driver not running with {BATCHES - s['batches_done']} batches left")
    if s["metrics"] and s["metrics"]["free"] < 20:
        s["problems"].append(f"free memory {s['metrics']['free']}%")
    if s["metrics"] and s["metrics"]["swap_growth_mb"] > 2048:
        s["problems"].append(f"swap grew {s['metrics']['swap_growth_mb']} MB since the run started")
    s["finished"] = s["batches_done"] >= BATCHES and not s["driver_running"]
    s["reported"] = (d / "REPORTED").exists()
    return s


def report() -> str:
    _, d = [r for r in runs() if done(r[1]) >= BATCHES][-1]
    tot = {}
    for f in sorted(d.glob("b*/summary.json")):
        for k, v in json.loads(f.read_text()).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                tot[k] = tot.get(k, 0) + v
    rate = lambda k: f"{tot.get(k + '_ok', 0) / max(1, tot.get(k + '_turns', 0)):.1%} (n = {tot.get(k + '_turns', 0):,})"
    labels = ["recorded", "unique", "ambiguous", "not_recorded"]
    rows = sum(tot.get(f"rows_{l}", 0) for l in labels)
    mb = sum(p.stat().st_size for p in d.glob("b*/decisions.jsonl.gz")) / 1e6
    free = [int(m) for m in re.findall(r"free=(\d+)%", (d / "metrics.log").read_text())] if (d / "metrics.log").exists() else []
    return "\n".join([
        f"## {d.name}: {tot.get('games', 0):,} games, {rows:,} decision rows ({mb:.0f} MB gz)",
        "",
        f"- Turns reproduced: clean {rate('clean')}, from an exact start {rate('exact_start')}, after a reset {rate('after_resync')}",
        "- Rows: " + ", ".join(f"{l} {tot.get('rows_' + l, 0):,} ({tot.get('rows_' + l, 0) / max(1, rows):.1%})" for l in labels),
        f"- Stalls {tot.get('stalls', 0)}, games lost {tot.get('games_lost', 0)}, games conceded at record end {tot.get('games_conceded', 0):,}",
        f"- Lowest free memory {min(free) if free else '?'}%",
    ])


def launch(name: str, seed: int, exclude: Path | None):
    d = TR / name
    d.mkdir(parents=True, exist_ok=True)
    cmd = (f"uv run --group data python seventeenlands/replay_batches.py --name {name} --sample 50000 --seed {seed} "
           f"--batch 500 --workers 3 -- --probe 30 --rows" + (f" --exclude {exclude}" if exclude else ""))
    if not (d / "README.txt").exists():
        code = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
        (d / "README.txt").write_text(
            f"code {code} (engine classes ~/mtg-data/xmage-cls-replay); {cmd}; started {time.ctime()} by replay_cycle.py\n"
            f"stop: kill $(pgrep -f 'replay_batches.py --name {name}' | head -1); "
            f"resume: uv run --group data python seventeenlands/replay_cycle.py resume\n")
    else:
        with open(d / "progress.log", "a") as p:
            p.write(f"{time.ctime()} resumed by replay_cycle.py\n")
    monitor = (TR / "dsk50k-2" / "monitor.sh").read_text().replace("--name dsk50k-2", f"--name {name}")
    (d / "monitor.sh").write_text(monitor)
    (d / "monitor.sh").chmod(0o755)
    env = f"export PATH={JAVA}:$PATH; cd {REPO}; "
    subprocess.Popen(["zsh", "-c", env + f"nohup caffeinate -i {cmd} >> {d}/driver.log 2>&1 &"
                      f" sleep 45; nohup {d}/monitor.sh >/dev/null 2>&1 &"], start_new_session=True)
    return cmd


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "status"
    if what == "status":
        print(json.dumps(status(), indent=1))
    elif what == "report":
        print(report())
    elif what == "resume":
        n, d = runs()[-1]
        if driver_running(d.name):
            sys.exit(f"{d.name} is already running")
        cmd = (d / "README.txt").read_text()
        ex = re.search(r"--exclude (\S+)", cmd)
        print(launch(d.name, 5000 + n, Path(ex.group(1).rstrip(";")) if ex else None))
    elif what == "next":
        n, d = runs()[-1]
        if driver_running(d.name) or done(d) < BATCHES:
            sys.exit(f"{d.name} isn't finished")
        ids = set()
        for _, p in runs():
            for g in p.glob("b*/games.jsonl"):
                ids |= {int(json.loads(l)["id"][1:]) for l in g.read_text().splitlines() if l.strip()}
        ex = TR / f"rows_done_{len(ids) // 1000}k.txt"
        ex.write_text("\n".join(map(str, sorted(ids))) + "\n")
        name = f"dsk50k-{n + 1}"
        print(launch(name, 5000 + n + 1, ex))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
