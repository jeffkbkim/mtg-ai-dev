"""Play N DSK games in XMage with both seats driven from Python, and record every decision.

Each seat has its own socket and its own player object, so a player only ever sees its own seat's view.

  python3 play/match.py --runtime ~/xmage/xmage/mage-server --classes /tmp/xmage-cls \\
      --a claude --b random --deck-a engine/xmage/decks/dsk_ug.dck --deck-b engine/xmage/decks/dsk_uw.dck \\
      --games 5 --out /mnt/project-files/claude-games/run1

Writes <out>/game<N>.jsonl (one line per real decision, both seats), <out>/games.jsonl (one line per game),
<out>/jvm.log and <out>/config.json. Seat A starts even games, seat B odd games.
games.jsonl is rewritten after every game, so a crash keeps the finished games. A failure in either seat (model error,
a hidden-information leak reported by the engine) is written to <out>/errors.log and stops the whole run; the
unfinished game's decisions are kept in its game<N>.jsonl but it has no line in games.jsonl.
"""
import argparse, json, shutil, socket, subprocess, sys, tempfile, threading, time, traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from players import ClaudePlayer, RandomPlayer


def make_player(kind, seed, args, lessons=None, plan=False, facts=False, check=False):
    if kind == "random":
        return RandomPlayer(seed)
    if kind == "claude":
        return ClaudePlayer(model=args.model, effort=args.effort, lessons=lessons, plan=plan, facts=facts, check=check,
                            primer=args.primer)
    raise ValueError(kind)


def seat_loop(seat, conn, player, deck, local, out, lock, results, write_games, abort, stopped):
    f = conn.makefile("rw")
    game, idx, started = 0, 0, False
    try:
        for line in f:
            msg = json.loads(line)
            if msg["type"] == "end":
                break
            if msg["type"] == "game_end":
                player.end_game(msg)
                with lock:
                    results.setdefault(msg["game"], msg)
                    if (local / f"game{game}.jsonl").exists():
                        shutil.copyfile(local / f"game{game}.jsonl", out / f"game{game}.jsonl")
                    write_games()
                game, idx, started = msg["game"] + 1, 0, False
                continue
            if msg.get("leaks"):
                # fail closed: a decision the engine flagged as exposing hidden information never reaches a player
                raise RuntimeError(f"hidden-information leak flagged by the engine: {msg['leaks']}")
            if not started:
                player.start_game(game, deck)
                started = True
            t0 = time.time()
            choice, info = player.choose(msg)
            rec = {"game": game, "seat": seat, "player": player.name, "idx": idx, "kind": msg["kind"], "prompt": msg["prompt"],
                   "obs": msg["obs"], "options": msg["options"], "leaks": msg.get("leaks", []), "choice": choice,
                   "seconds": round(time.time() - t0, 3), **info}
            idx += 1
            # record locally first (appends to the network-mounted project folder lost a line once), copied at game end
            with lock, (local / f"game{game}.jsonl").open("a") as g:
                g.write(json.dumps(rec) + "\n")
            f.write(json.dumps({"choice": choice}) + "\n"); f.flush()
    except Exception:
        with lock:
            if not stopped.is_set():  # the first failure stops the run; the other seat then just sees its socket close
                with (out / "errors.log").open("a") as e:
                    e.write(f"seat {seat}, game {game}, decision {idx}:\n{traceback.format_exc()}\n")
        abort()
    finally:
        player.end_game({})
        with lock:
            if (local / f"game{game}.jsonl").exists():  # an unfinished game's decisions, kept for inspection
                shutil.copyfile(local / f"game{game}.jsonl", out / f"game{game}.jsonl")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--runtime", required=True); p.add_argument("--classes", required=True)
    p.add_argument("--a", default="claude"); p.add_argument("--b", default="random")
    p.add_argument("--deck-a", required=True); p.add_argument("--deck-b", required=True)
    p.add_argument("--games", type=int, default=1); p.add_argument("--seed", type=int, default=0)
    p.add_argument("--model", default="claude-opus-5-5"); p.add_argument("--effort", default="high")
    p.add_argument("--lessons-a"); p.add_argument("--lessons-b")  # lessons file for a Claude seat (play/primer/lessons_v*.md)
    p.add_argument("--plan-a", action="store_true"); p.add_argument("--plan-b", action="store_true")  # plan updated in every reply
    p.add_argument("--facts-a", action="store_true"); p.add_argument("--facts-b", action="store_true")  # play/facts.py block
    p.add_argument("--check-a", action="store_true"); p.add_argument("--check-b", action="store_true")  # self-check
    p.add_argument("--primer", choices=("v1", "v2"))  # Claude seats' primer; default $PRIMER, else v1
    p.add_argument("--out", required=True)
    args = p.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=Path(__file__).parent).stdout.strip()
    (out / "config.json").write_text(json.dumps({**vars(args), "code_commit": commit, "xmage": "1.4.62"}, indent=1))

    servers = [socket.socket(), socket.socket()]
    for s in servers:
        s.bind(("127.0.0.1", 0)); s.listen(1)
    ports = [s.getsockname()[1] for s in servers]
    jars = sorted(str(x) for x in Path(args.runtime).rglob("*.jar"))
    cp = ":".join([args.classes] + jars)
    decks = [str(Path(args.deck_a).resolve()), str(Path(args.deck_b).resolve())]
    jvm = subprocess.Popen(["java", "-Xmx3g", "-Djava.awt.headless=true", "--add-opens=java.base/java.lang=ALL-UNNAMED",
                            "-cp", cp, "TwoSeatMatch", str(ports[0]), str(ports[1]), *decks, str(args.games)],
                           cwd=args.runtime, stdout=open(out / "jvm.log", "w"), stderr=subprocess.STDOUT)
    conns = []
    for s in servers:
        c, _ = s.accept()
        c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        conns.append(c)
    players = [make_player(args.a, args.seed, args, args.lessons_a, args.plan_a, args.facts_a, args.check_a),
               make_player(args.b, args.seed + 1, args, args.lessons_b, args.plan_b, args.facts_b, args.check_b)]
    lock, results = threading.Lock(), {}
    local = Path(tempfile.mkdtemp(prefix="match-"))

    def write_games():  # called under the lock after every game
        (local / "games.jsonl").write_text("".join(
            json.dumps({**results[k], "a": players[0].name, "b": players[1].name,
                        "deck_a": Path(decks[0]).name, "deck_b": Path(decks[1]).name}) + "\n" for k in sorted(results)))
        shutil.copyfile(local / "games.jsonl", out / "games.jsonl")

    stopped = threading.Event()

    def abort():
        stopped.set()
        jvm.kill()
        for c in conns:
            try:
                c.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    threads = [threading.Thread(target=seat_loop, args=("AB"[i], conns[i], players[i], decks[i], local, out, lock, results,
                                                        write_games, abort, stopped)) for i in range(2)]
    for t in threads: t.start()
    for t in threads: t.join()
    with lock:
        write_games()
    try:
        jvm.wait(timeout=120)
    except subprocess.TimeoutExpired:
        jvm.kill()
    print(json.dumps([results[k] for k in sorted(results)]))
    if stopped.is_set():
        sys.exit(f"run stopped early, see {out / 'errors.log'}")


if __name__ == "__main__":
    main()
