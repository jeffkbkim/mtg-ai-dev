"""Seat-balanced evaluation games: a trained policy (seat A) against a fixed opponent (seat B), on real 17lands decks.

    uv run --group brain python play/eval_games.py --policy data/policies/200-l1/policy.onnx \\
        --opponent random --pairs 50 --jobs 3 --seed 1 --out <runs>/eval/200-l1-vs-random

Opponents: `random` (play/players.py's RandomPlayer, the project's random bot) and `xmage` (XMage's ComputerPlayer7,
the AI Playmat seats use; --ai-skill, --ai-think). `policy:<onnx>` plays another policy file, e.g. one model against
an older one.

Seat balance. Each deck pair (X, Y), drawn without replacement from --decks with --seed, is played four times:
the policy on X and on Y, each once on the play and once on the draw. So neither side gets a better deck or the
extra card more often, and the win rate reflects the player, not the draw of decks. --pairs 50 = 200 games.

--jobs runs that many engines at once (one JVM each, ~1 core and up to 3 GB). Pairs are dealt to the jobs in turn.

Writes into --out:
  config.json        everything needed to repeat the run: arguments, policy.json of the model, git commit, schedule
  games.jsonl        one line per finished game: decks, who was on the play, winner, turns, decisions, fallbacks
  part<k>/decisions.jsonl   per policy decision: kind, offered action types, each option's card (name, types, and
                     instant/sorcery speed for casts), choice, the policy's probability or fallback reason
  part<k>/jvm.log    the engine's log (leaks, rejected moves, unmapped abilities)
  errors.log         a part that stopped early and why (its finished games are kept)
Then play/eval_report.py <out> prints win rates with 95% intervals.
"""
import argparse, json, random, socket, subprocess, sys, threading, time, traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from policy_player import PolicyPlayer  # noqa: E402

READ_TIMEOUT = 900  # seconds without a message from the engine before a part is declared hung


_FLASH = None


def has_flash(name: str) -> bool:
    """Whether the card's printed rules give it flash (engine/vocab/<set>_card_text.json, as XMage implements it).

    The observation can't say: it lists keywords only for permanents on the battlefield, not for cards in hand.
    """
    global _FLASH
    if _FLASH is None:
        from render import load_card_text
        _FLASH = {n for n, c in load_card_text().items() if any(r.strip() == "Flash" for r in c["rules"])}
    return name in _FLASH


def option_cards(msg: dict) -> list[dict]:
    """Each option's action and, when it comes from a card, that card's name, types and (for casts) its speed.

    speed is "instant" for an instant or a card with flash, else "sorcery": a sorcery-speed cast can only happen in
    one's own main phase, so passing on one is a different mistake from holding a trick for the opponent's turn.
    """
    entries = msg["obs"]["entries"]
    out = []
    for o in msg["options"]:
        d = {"action": o.get("action")}
        i = (o.get("source") or {}).get("entry")
        card = entries[i] if i is not None and i < len(entries) and entries[i].get("kind") == "card" else None
        if card:
            d.update(name=card.get("card_name") or card.get("name"), types=card.get("types"))
            if d["action"] == "CAST":
                flash = has_flash(d["name"]) or any(k.lower() == "flash" for k in card.get("keywords") or [])
                d["speed"] = "instant" if flash or "Instant" in (card.get("types") or "") else "sorcery"
        out.append(d)
    return out


def make_schedule(decks: list[Path], pairs: int, seed: int) -> list[dict]:
    """4 games per deck pair: the policy on each deck, on the play and on the draw."""
    rng = random.Random(seed)
    all_pairs = [(a, b) for i, a in enumerate(decks) for b in decks[i + 1:]]
    if pairs > len(all_pairs):
        sys.exit(f"only {len(all_pairs)} deck pairs in the pool")
    games = []
    for p, (x, y) in enumerate(rng.sample(all_pairs, pairs)):
        for mine, theirs in ((x, y), (y, x)):
            for first in ("A", "B"):
                games.append({"pair": p, "deck_a": str(mine), "deck_b": str(theirs), "first": first})
    return games


def opponent_player(spec: str, seed: int):
    if spec == "random":
        from players import RandomPlayer
        return RandomPlayer(seed)
    if spec.startswith("policy:"):
        return PolicyPlayer(spec.split(":", 1)[1], seed=seed, name="opponent:" + Path(spec.split(":", 1)[1]).parent.name)
    raise ValueError(spec)


class Part:
    """One engine (JVM) playing its share of the schedule, in order."""

    def __init__(self, k, games, args, out, lock, policy_meta):
        self.k, self.games, self.args, self.lock = k, games, args, lock
        self.dir = out / f"part{k:02d}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.out = out
        self.meta = policy_meta
        self.finished = 0

    def run(self):
        args = self.args
        (self.dir / "schedule.tsv").write_text(
            "".join(f"{g['deck_a']}\t{g['deck_b']}\t{g['first']}\n" for g in self.games))
        ai = args.opponent == "xmage"
        servers = [socket.socket() for _ in range(1 if ai else 2)]
        for s in servers:
            s.bind(("127.0.0.1", 0)); s.listen(1)
        ports = [str(s.getsockname()[1]) for s in servers]
        jars = sorted(str(x) for x in Path(args.runtime).rglob("*.jar"))
        cmd = ["java", "-Xmx3g", "-Djava.awt.headless=true", "--add-opens=java.base/java.lang=ALL-UNNAMED",
               "-cp", ":".join([args.classes] + jars), "EvalMatch", str((self.dir / "schedule.tsv").resolve()),
               ports[0], "ai" if ai else ports[1], str(args.ai_skill), str(args.ai_think)]
        self.jvm = subprocess.Popen(cmd, cwd=args.runtime, stdout=open(self.dir / "jvm.log", "w"),
                                    stderr=subprocess.STDOUT)
        conns = []
        for s in servers:
            s.settimeout(5)
            while True:  # an engine that dies before connecting must not leave this waiting forever
                try:
                    c, _ = s.accept()
                    break
                except socket.timeout:
                    if self.jvm.poll() is not None:
                        self.fail(f"engine exited with code {self.jvm.returncode} before connecting")
                        return
            c.settimeout(READ_TIMEOUT)
            c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            conns.append(c)
        self.conns = conns
        if args.policy == "random":  # the random bot in seat A: the floor a policy's numbers are compared with
            from players import RandomPlayer
            policy = RandomPlayer(args.seed * 1000 + self.k)
        else:
            policy = PolicyPlayer(args.policy, seed=args.seed * 1000 + self.k, temperature=args.temperature)
        seats = [("A", conns[0], policy)]
        if not ai:
            seats.append(("B", conns[1], opponent_player(args.opponent, args.seed * 1000 + 500 + self.k)))
        self.stopped = threading.Event()
        threads = [threading.Thread(target=self.seat_loop, args=s) for s in seats]
        for t in threads: t.start()
        for t in threads: t.join()
        try:
            self.jvm.wait(timeout=120)
        except subprocess.TimeoutExpired:
            self.jvm.kill()

    def fail(self, why):
        with self.lock, (self.out / "errors.log").open("a") as e:
            e.write(f"part {self.k:02d} after {self.finished} games: {why}\n")

    def abort(self):
        self.stopped.set()
        self.jvm.kill()
        for c in getattr(self, "conns", []):
            try:
                c.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def seat_loop(self, seat, conn, player):
        f = conn.makefile("rw")
        game, idx = 0, 0
        counts = {"decisions": 0, "fallbacks": 0}
        log = (self.dir / "decisions.jsonl").open("a") if seat == "A" else None
        try:
            for line in f:
                msg = json.loads(line)
                if msg["type"] == "end":
                    break
                if msg["type"] == "game_end":
                    if seat == "A":
                        g = self.games[msg["game"]]
                        rec = {"part": self.k, "game": msg["game"], "pair": g["pair"], "opponent": self.args.opponent,
                               "policy": self.meta.get("name"), **{k: msg.get(k) for k in (
                                   "deck_a", "deck_b", "first", "winner", "turns", "seconds", "life_a", "life_b",
                                   "error")}, **counts}
                        with self.lock, (self.out / "games.jsonl").open("a") as out:
                            out.write(json.dumps(rec) + "\n")
                        self.finished += 1
                    game, idx = msg["game"] + 1, 0
                    counts = {"decisions": 0, "fallbacks": 0}
                    continue
                if msg.get("leaks"):
                    # fail closed: a decision the engine flagged as exposing hidden information never reaches a player
                    raise RuntimeError(f"hidden-information leak flagged by the engine: {msg['leaks']}")
                choice, info = player.choose(msg)
                if log:
                    pol = info.get("policy", {})
                    counts["decisions"] += 1
                    counts["fallbacks"] += "fallback" in pol
                    g0 = msg["obs"]["entries"][0]
                    log.write(json.dumps({
                        "game": game, "idx": idx, "turn": g0.get("turn"), "step": g0.get("step"),
                        "my_turn": g0.get("my_turn"), "lands_played": g0.get("lands_played"), "kind": msg["kind"],
                        "offered": sorted({o.get("action") for o in msg["options"]}), "choice": choice,
                        "label": msg["options"][choice].get("label", "")[:60], "options": option_cards(msg),
                        **pol}) + "\n")
                idx += 1
                f.write(json.dumps({"choice": choice}) + "\n"); f.flush()
        except Exception:
            if not self.stopped.is_set():  # the first failure stops the part; the other seat just sees its socket close
                self.fail(f"seat {seat}, game {game}, decision {idx}:\n{traceback.format_exc()}")
            self.abort()
        finally:
            if log:
                log.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--policy", required=True,
                    help="policy.onnx from play/export_policy.py, or `random` for the random bot (a reference run)")
    ap.add_argument("--opponent", required=True, help="random | xmage | policy:<onnx>")
    ap.add_argument("--pairs", type=int, default=25, help="deck pairs; 4 games each")
    ap.add_argument("--decks", type=Path, default=ROOT / "engine/xmage/decks/17lands-good-v2")
    ap.add_argument("--seed", type=int, default=1, help="deck pairs, the random bot, the policy's fallback picks")
    ap.add_argument("--temperature", type=float, default=0.0, help="0 = always the policy's best option")
    ap.add_argument("--jobs", type=int, default=1, help="engines at once")
    ap.add_argument("--ai-skill", type=int, default=2, help="ComputerPlayer7 skill (search depth), as in our checks")
    ap.add_argument("--ai-think", type=int, default=1, help="ComputerPlayer7 max think seconds per decision")
    ap.add_argument("--runtime", default=str(Path.home() / "xmage/xmage/mage-server"))
    ap.add_argument("--classes", default="/tmp/xmage-cls")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    out = args.out
    if (out / "games.jsonl").exists():
        sys.exit(f"{out} already has games; pick a new --out")
    out.mkdir(parents=True, exist_ok=True)
    # the engine plays copies: XMage's deck importer rewrites a file it reads (the NAME line's encoding), and the
    # copies record exactly which decks this run used
    (out / "decks").mkdir(exist_ok=True)
    decks = []
    for d in sorted(args.decks.glob("*.dck")):
        decks.append((out / "decks" / d.name).resolve())
        decks[-1].write_bytes(d.read_bytes())
    schedule = make_schedule(decks, args.pairs, args.seed)
    meta_path = Path(args.policy).with_suffix(".json")
    policy_meta = json.loads(meta_path.read_text()) if meta_path.exists() else {"name": Path(args.policy).stem}
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain", "--", "play", "engine"], capture_output=True,
                                text=True, cwd=ROOT).stdout.strip())
    (out / "config.json").write_text(json.dumps({
        **{k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
        "games": len(schedule), "code_commit": commit, "code_uncommitted": dirty, "xmage": "1.4.62",
        "policy_meta": policy_meta, "schedule": schedule, "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }, indent=1))

    # deal whole deck pairs to the jobs in turn, so each part keeps its pair's four games together
    pair_ids = sorted({g["pair"] for g in schedule})
    lock = threading.Lock()
    parts = []
    for k in range(min(args.jobs, len(pair_ids))):
        mine = set(pair_ids[k::args.jobs])
        parts.append(Part(k, [g for g in schedule if g["pair"] in mine], args, out, lock, policy_meta))
    t0 = time.time()
    threads = []
    for i, p in enumerate(parts):
        threads.append(threading.Thread(target=p.run))
        threads[-1].start()
        time.sleep(5 if i < len(parts) - 1 else 0)  # stagger JVM boots (they share the card database)
    for t in threads: t.join()
    done = sum(p.finished for p in parts)
    print(f"{done}/{len(schedule)} games in {(time.time() - t0) / 60:.1f} min -> {out / 'games.jsonl'}")
    if (out / "errors.log").exists():
        print(f"some parts stopped early, see {out / 'errors.log'}")


if __name__ == "__main__":
    main()
