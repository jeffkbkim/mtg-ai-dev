"""Keep the 17lands DSK turn replay going on the mini, one 50k-game run after another (for a scheduled task).

  uv run --group data python seventeenlands/replay_cycle.py status    # JSON: the current run and anything wrong
  uv run --group data python seventeenlands/replay_cycle.py report    # summary of the newest finished run, as markdown
  uv run --group data python seventeenlands/replay_cycle.py resume    # restart the current run's driver (skips done batches)
  uv run --group data python seventeenlands/replay_cycle.py next      # start the next run: new seed, skips every game done
  uv run --group data python seventeenlands/replay_cycle.py auto      # all of the above as needed (launchd, every 30 min)

`auto` is what keeps runs going back to back with no one watching: it resumes a run whose driver stopped, and when a
run finishes it appends the report to seventeenlands/TURN_REPLAY.md, commits and pushes it, and starts the next run.
A file turn_replay/NO_NEXT_RUN pauses it after the current run (the run is still finished and reported).
Anything worth knowing goes to ~/mtg-data/17lands/DSK/turn_replay/NOTES.md (newest last), once per message.

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
WORKERS = 4                                                   # 4 with the faster engine build (2026-11-07 speedups)
CLASSES = Path.home() / "mtg-data/xmage-cls-fast"             # engine classes built from ad543a1 or later
STATUS = REPO / "seventeenlands/replay_status.md"              # notes, committed and pushed so the project can post them


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
    labels = sorted(k[len("rows_"):] for k in tot if k.startswith("rows_"))
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
           f"--batch 500 --workers {WORKERS} --classes {CLASSES} -- --probe 30 --rows --chunk 25"
           + (f" --exclude {exclude}" if exclude else ""))
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


def note(text: str):
    f = TR / "NOTES.md"
    old = f.read_text() if f.exists() else ""
    if text in old:
        return
    line = f"- {time.strftime('%Y-%m-%d %H:%M')} {text}\n"
    with open(f, "a") as out:
        out.write(line)
    # the same line in the repo, so a project check reading GitHub can post it to Jeff (a scheduled task on the mini
    # can't reach the project thread, and its push notifications only show on the mini)
    git("pull", "-q", "--no-rebase", "origin", "main")
    with open(STATUS, "a") as out:
        out.write(line)
    git("add", str(STATUS))
    if git("commit", "-q", "-m", "Replay status: " + text[:60] + "\n\nCo-Authored-By: Claude <noreply@anthropic.com>").returncode == 0:
        git("push", "-q", "origin", "main")


def git(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True)


def auto():
    s = status()
    n, d = runs()[-1]
    if s["finished"] and not s["reported"]:
        rep = report()
        md = REPO / "seventeenlands/TURN_REPLAY.md"
        md.write_text(md.read_text().rstrip("\n") + "\n\n" + rep.replace("## ", "## Run ", 1) + "\n")
        git("add", "seventeenlands/TURN_REPLAY.md")
        c = git("commit", "-m", f"Turn replay: {d.name} results\n\nCo-Authored-By: Claude <noreply@anthropic.com>")
        pushed = "not committed: " + c.stderr.strip()[:200] if c.returncode else ""
        if not c.returncode:
            pl = git("pull", "--no-rebase", "origin", "main")
            if pl.returncode:
                git("merge", "--abort")
                pushed = "committed locally, pull failed: " + (pl.stderr or pl.stdout).strip()[:200]
            else:
                ps = git("push", "origin", "main")
                pushed = "pushed" if not ps.returncode else "committed locally, push failed: " + ps.stderr.strip()[:200]
        (d / "REPORTED").touch()
        first = rep.splitlines()[0].lstrip("# ")
        if s["failed_batches"]:
            launch(d.name, 5000 + n, None if "--exclude" not in (d / "README.txt").read_text()
                   else Path(re.search(r"--exclude (\S+)", (d / "README.txt").read_text()).group(1).rstrip(";")))
            note(f"{first}. Batches {s['failed_batches']} failed, so it was resumed to redo them. Report {pushed}.")
        elif (TR / "NO_NEXT_RUN").exists():
            note(f"{first}. Report {pushed}. No next run: replay is paused (turn_replay/NO_NEXT_RUN).")
        else:
            subprocess.run([sys.executable, __file__, "next"], cwd=REPO)
            note(f"{first}. Report {pushed}. Started dsk50k-{n + 1}.")
        return
    if not s["driver_running"] and s["batches_done"] < BATCHES:
        subprocess.run([sys.executable, __file__, "resume"], cwd=REPO)
        note(f"{d.name}: the driver had stopped with {BATCHES - s['batches_done']} batches left; resumed.")
    for p in s["problems"]:
        if "driver not running" not in p:
            note(f"{d.name}: {p}")


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
    elif what == "auto":
        auto()
    elif what == "next":
        if (TR / "NO_NEXT_RUN").exists():
            sys.exit("paused: turn_replay/NO_NEXT_RUN exists (" + (TR / "NO_NEXT_RUN").read_text().strip() + ")")
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
