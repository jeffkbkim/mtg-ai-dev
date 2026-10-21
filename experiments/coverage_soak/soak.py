"""DSK card coverage soak: many random-bot games through XMage to find cards that break or misbehave.

Builds two-colour decks that rotate through every DSK card (least-used cards first), plays each pair of decks
with SeatSpike (our random seat vs XMage's AI), and records per run: results, the seat's counters (leaks,
unmapped abilities and choices, rejected moves), JVM exceptions and hangs. Per card it counts how often the card
was in a deck and how often it reached the battlefield or the stack, so a card with no problems but no exposure
is reported as untested, not as fine.

    uv run python experiments/coverage_soak/soak.py --runs 4 --out ~/mtg-data/soak/trial
    uv run python experiments/coverage_soak/report.py ~/mtg-data/soak/trial
"""
import argparse, collections, gzip, itertools, json, os, random, re, socket, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
import threading
from pathlib import Path

HERE = Path(__file__).parent
REPO = HERE.parent.parent
COLORS = "WUBRG"
BASICS = {"W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest"}


def card_colors(c):
    """Colours a card needs to be cast: mana symbols in its cost (both halves for split cards / Rooms)."""
    costs = [c.get("cost", "")] + [c[h]["cost"] for h in ("left", "right") if h in c]
    return {ch for cost in costs for sym in re.findall(r"\{([^}]*)\}", cost) for ch in sym if ch in COLORS}


def land_colors(c):
    """Colours a nonbasic land can make; None when it can make any colour."""
    text = " ".join(c["rules"])
    made = {ch for sym in re.findall(r"Add ((?:\{[^}]*\})+)", text) for ch in sym if ch in COLORS}
    return None if "any color" in text or not made else made  # no mana symbols: fetches or chooses a colour


def load_pool():
    cards = json.loads((REPO / "engine/vocab/dsk_card_text.json").read_text())
    numbers = json.loads((HERE / "dsk_numbers.json").read_text())
    spells, lands = {}, {}
    for c in cards:
        if c["name"] in BASICS.values():
            continue
        if "Land" in c["types"] and "Creature" not in c["types"]:
            lands[c["name"]] = land_colors(c)
        else:
            spells[c["name"]] = card_colors(c)
    return spells, lands, numbers


class DeckBuilder:
    """Two-colour 40-card decks, 23 spells + 17 lands, always picking the cards used least so far."""

    def __init__(self, seed):
        self.spells, self.lands, self.numbers = load_pool()
        self.used = collections.Counter()
        self.rng = random.Random(seed)
        # every two-colour pair, plus the colours of each card that needs three or more
        self.pairs = [set(p) for p in itertools.combinations(COLORS, 2)]
        self.pairs += [cs for cs in {frozenset(cs) for cs in self.spells.values() if len(cs) > 2}]

    def build(self, i):
        pair = self.pairs[i % len(self.pairs)]
        pool = [n for n, cs in self.spells.items() if cs <= pair]
        pool.sort(key=lambda n: (self.used[n], self.rng.random()))
        spells = pool[:23]
        land_pool = [n for n, cs in self.lands.items() if cs is None or cs <= pair]
        land_pool.sort(key=lambda n: (self.used[n], self.rng.random()))
        nonbasic = land_pool[:2]
        self.used.update(spells + nonbasic)
        # basics split by how many coloured symbols each colour has in the chosen spells
        cols = [ch for ch in COLORS if ch in pair]
        weight = {ch: 1 + sum(ch in self.spells[n] for n in spells) for ch in cols}
        n_basic = 17 - len(nonbasic)
        counts = {ch: max(1, int(n_basic * weight[ch] / sum(weight.values()))) for ch in cols}
        counts[max(cols, key=weight.get)] += n_basic - sum(counts.values())
        lines = [f"1 [DSK:{self.numbers[n]}] {n}" for n in spells + nonbasic]
        lines += [f"{counts[ch]} [DSK:{self.numbers[BASICS[ch]]}] {BASICS[ch]}" for ch in cols]
        name = f"soak_{i:04d}_{''.join(cols)}"
        return name, spells + nonbasic, f"NAME:{name}\n" + "\n".join(lines) + "\n"


def choose(msg, rng):
    """Same biased-random policy as engine/xmage/run_games.py: take a non-PASS/DONE option 80% of the time."""
    n = len(msg["options"])
    if n > 1 and msg["options"][0]["label"] in ("PASS", "DONE") and rng.random() < 0.8:
        return rng.randrange(1, n)
    return rng.randrange(n)


# JVMs share XMage's card database (mage-server/db); two opening it at once fail with "Lock file recently
# modified" and never connect, so only one JVM boots at a time
BOOT_LOCK = threading.Lock()

COUNTER_LINES = ("ASKED", "FORCED", "LEAKS", "UNSEEN_REFS", "UNMAPPED_ABILITIES", "UNMAPPED_CHOICES",
                 "GRANTED_ON_BOARD", "UNKEYED_ON_BOARD", "FALLBACK", "REJECTED", "SIMULATED")


def parse_jvm_log(text):
    out = {"results": [], "counters": {}, "exceptions": []}
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("RESULT "):
            out["results"].append(dict(re.findall(r"(\w+)=(.*?)(?= \w+=|$)", line)))
        elif line.split(" ", 1)[0] in COUNTER_LINES:
            k, _, v = line.partition(" ")
            out["counters"][k] = v
        elif re.search(r"(Exception|Error)\b", line) and not line.startswith(("INFO", "DEBUG")) and not re.search(r"h2|SQLException|[Dd]atabase", line):
            # the exception line plus the frames under it, so the card class (mage.cards.x.Name) is kept
            frames = [l.strip() for l in lines[i + 1:i + 40] if l.strip().startswith("at ")]
            out["exceptions"].append({"line": line.strip()[:400], "card_frames": sorted({m for f in frames for m in re.findall(r"mage\.cards\.[a-z]\.(\w+)", f)}), "frames": frames[:12]})
    return out


def play_run(run_id, deck_a, deck_b, args):
    """One JVM: SeatSpike with our random seat on deck_a vs XMage's AI on deck_b for args.games games."""
    out = Path(args.out) / "runs" / f"{run_id:04d}"
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, cards, text in (deck_a, deck_b):
        p = out / f"{name}.dck"; p.write_text(text); paths.append(str(p))
    rng = random.Random(args.seed * 100003 + run_id)
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1); srv.settimeout(args.timeout)
    jars = sorted(str(p) for p in Path(args.runtime).rglob("*.jar"))
    jvm_log = out / "jvm.log"
    BOOT_LOCK.acquire()
    jvm = subprocess.Popen(["java", f"-Xmx{args.heap}", "-Djava.awt.headless=true", "--add-opens=java.base/java.lang=ALL-UNNAMED",
                            "-cp", ":".join([args.classes] + jars), "SeatSpike", str(srv.getsockname()[1]), *paths, str(args.games)],
                           cwd=args.runtime, stdout=open(jvm_log, "w"), stderr=subprocess.STDOUT)
    status, decisions, seen = "ok", 0, collections.Counter()
    started = time.time()
    try:
        try:
            conn, _ = srv.accept()
        finally:
            BOOT_LOCK.release()
        conn.settimeout(args.timeout)
        f = conn.makefile("rw")
        with gzip.open(out / "decisions.jsonl.gz", "wt") as log:
            game_seen = set()
            while True:
                line = f.readline()
                if not line:
                    status = "jvm_closed"; break
                msg = json.loads(line)
                if msg["type"] == "end":
                    break
                for e in msg.get("obs", {}).get("entries", []):
                    if e.get("kind") == "card" and e.get("zone") in ("BATTLEFIELD", "STACK") and not e.get("face_down"):
                        game_seen.add(e.get("card_name") or e.get("name"))
                c = choose(msg, rng)
                decisions += 1
                log.write(json.dumps({**msg, "choice": c}) + "\n")
                f.write(json.dumps({"choice": c}) + "\n"); f.flush()
                if time.time() - started > args.run_limit:
                    status = "run_limit"; break
            seen.update(game_seen)
    except (socket.timeout, TimeoutError):
        status = "hang"
    except (ConnectionError, json.JSONDecodeError) as e:
        status = f"io_error: {e!r}"[:200]
    finally:
        try:
            jvm.wait(timeout=30)
        except subprocess.TimeoutExpired:
            jvm.kill(); jvm.wait()
            if status == "ok":
                status = "jvm_stuck_after_end"
        srv.close()
    parsed = parse_jvm_log(jvm_log.read_text(errors="replace"))
    record = {"run": run_id, "status": status, "jvm_exit": jvm.returncode, "seconds": round(time.time() - started, 1),
              "decisions": decisions, "decks": {"py": deck_a[0], "ai": deck_b[0]},
              "cards": {"py": deck_a[1], "ai": deck_b[1]}, "seen_in_play": sorted(c for c in seen if c), **parsed}
    (out / "run.json").write_text(json.dumps(record, indent=1))
    return record


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=4, help="JVM runs; each plays --games games with a fresh pair of decks")
    ap.add_argument("--games", type=int, default=4)
    ap.add_argument("--jobs", type=int, default=3, help="JVMs in parallel")
    ap.add_argument("--heap", default="2g")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=180, help="seconds with no decision before a run counts as hung")
    ap.add_argument("--run-limit", type=float, default=1800, help="max seconds for one run")
    ap.add_argument("--runtime", default=os.path.expanduser("~/xmage/xmage/mage-server"))
    ap.add_argument("--classes", default="/tmp/xmage-cls")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=REPO).stdout.strip()
    (out / "config.json").write_text(json.dumps({**vars(args), "commit": commit, "started": time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=1))
    builder = DeckBuilder(args.seed)
    plans = [(r, builder.build(2 * r), builder.build(2 * r + 1)) for r in range(args.runs)]
    done = 0
    with ThreadPoolExecutor(args.jobs) as pool, (out / "runs.jsonl").open("a") as summary:
        for rec in pool.map(lambda p: play_run(*p, args), plans):
            done += 1
            summary.write(json.dumps({k: rec[k] for k in ("run", "status", "jvm_exit", "seconds", "decisions", "decks", "results", "counters", "exceptions")}) + "\n"); summary.flush()
            print(f"[{done}/{args.runs}] run {rec['run']} {rec['status']} games={len(rec['results'])} exceptions={len(rec['exceptions'])} {rec['seconds']}s", flush=True)


if __name__ == "__main__":
    main()
