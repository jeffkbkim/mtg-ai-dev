"""The Claude seats of a Playmat server: one ClaudePlayer (play/players.py) per seated "Computer - claude" player.

Playmat's server creates a ClaudeSeat (engine/playmat/java/ClaudeSeat.java) for each Claude seat at a table; the seat
connects here. Each connection is a thread with its own ClaudePlayer, so a player only ever sees its own seat's view.
Decisions are PySeat's (the same messages play/match.py reads); the first one of each game carries "start" with the
game's folder (written by GameRecorder) and the seat letter. Each decision goes to <folder>/seat-<X>.jsonl in
match.py's record format plus "ts", "source": "claude"; GameRecorder merges the seats into game0.jsonl at game end.

  python3 engine/playmat/claude_service.py [--port 17180] [--model claude-opus-5-5] [--effort high] [--play-draw rule]

The seat's "hello" names the model and effort the player picked in the web client's AI settings (--model and --effort
are for a seat that doesn't say); every decision records both. Its "prewarm" (the game's deck, sent when the game is
dealt) starts the model's process and writes the system prompt to the prompt cache before the first decision. With
--play-draw rule (the default; $PLAY_DRAW in run.sh) Claude always chooses to play first without being asked, and the
record says "source": "rule"; --play-draw claude asks the model.

Settings default to the latest batches' (facts and self-check on, no plan, no lessons). A decision the engine flags as
leaking hidden information never reaches the model: option 0 is played and the record says "leak_blocked" (match.py
stops the run instead; here a person is waiting at the table). A model failure after ClaudePlayer's own retries is
handled the same way ("service_error") and logged to <folder>/errors.log.
"""
import argparse, json, socket, sys, tempfile, threading, time, traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "play"))
from players import ClaudePlayer, read_deck  # noqa: E402

START_PROMPT = "Select a starting player"


def serve_seat(conn, args, log):
    f = conn.makefile("rw")
    model, effort = args.model, args.effort
    make = lambda: ClaudePlayer(model=model, effort=effort, lessons=args.lessons, plan=args.plan,
                                facts=not args.no_facts, check=not args.no_check)
    player = make()
    folder, seat, idx, started = None, None, 0, False
    warmed = None  # (deck cards, prewarm info) of a model started before the game's first decision
    prewarm = None  # that info, until the first decision the model is asked
    try:
        for line in f:
            msg = json.loads(line)
            if msg.get("type") == "end":
                break
            if msg.get("type") == "hello":
                model, effort = msg.get("model") or args.model, msg.get("effort") or args.effort
                player = make()
                log(f"seat connected: {model} {effort}")
                continue
            if msg.get("type") == "prewarm":
                deck = Path(tempfile.mkdtemp(prefix="claude-prewarm-")) / "deck.dck"
                deck.write_text(msg["deck"])
                player.end_game({})
                player.start_game(0, str(deck))
                t0 = time.time()
                player.prewarm()
                warmed = (read_deck(deck), {"spawn_seconds": round(time.time() - t0, 3)})
                log(f"prewarmed {model} {effort}")
                continue
            if msg.get("type") == "game_end":
                player.end_game(msg)
                log(f"seat {seat} game over: {json.dumps({k: msg.get(k) for k in ('winner', 'turns', 'a', 'b')})}")
                folder, started = None, False
                continue
            start = msg.pop("start", None)
            if start:
                folder, seat, idx = Path(start["dir"]), start["seat"], 0
                prewarm = None
                if warmed and warmed[0] == read_deck(start["deck"]):
                    prewarm = warmed[1]  # the started model has this deck: keep it
                else:
                    player.end_game({})
                    player.start_game(0, start["deck"])
                warmed = None
                started = True
                log(f"seat {seat} started in {folder}" + (" (prewarmed)" if prewarm else ""))
            if not started:
                raise RuntimeError("decision before the game's start message")
            t0 = time.time()
            info0 = None
            if args.play_draw == "rule" and msg["kind"] == "CHOOSE" and msg["prompt"] == START_PROMPT and \
                    any(o["target"].get("player") == "me" for o in msg["options"]):
                # a fixed rule: Claude plays first (Limited's usual choice), not a model decision
                choice = next(i for i, o in enumerate(msg["options"]) if o["target"].get("player") == "me")
                info = {"rule": "play_first", "source": "rule"}
            elif msg.get("leaks"):
                choice, info = 0, {"leak_blocked": True}
                (folder / "errors.log").open("a").write(f"seat {seat} decision {idx}: leak flagged, model not asked: {msg['leaks']}\n")
            else:
                if prewarm is not None:  # the first decision the model is asked: how far the prewarm had got
                    info0, prewarm = {**prewarm, **player.warm_info()}, None
                try:
                    choice, info = player.choose(msg)
                except Exception:
                    choice, info = 0, {"service_error": True}
                    (folder / "errors.log").open("a").write(f"seat {seat} decision {idx}:\n{traceback.format_exc()}\n")
                    player.end_game({})  # a fresh conversation for the next decision
                    player.start_game(0, start["deck"] if start else str(folder / f"deck-{seat}.dck"))
            rec = {"game": 0, "seat": seat, "player": player.name, "idx": idx, "kind": msg["kind"], "prompt": msg["prompt"],
                   "obs": msg["obs"], "options": msg["options"], "leaks": msg.get("leaks", []), "choice": choice,
                   "seconds": round(time.time() - t0, 3), "source": "claude", **info, "model": model, "effort": effort,
                   "ts": int(time.time() * 1000)}
            if info0 is not None:
                rec["prewarm"] = info0
            idx += 1
            with (folder / f"seat-{seat}.jsonl").open("a") as g:
                g.write(json.dumps(rec) + "\n")
            f.write(json.dumps({"choice": choice, "player": player.name}) + "\n")
            f.flush()
    except Exception:
        log(f"seat {seat} stopped:\n{traceback.format_exc()}")
    finally:
        player.end_game({})
        conn.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=17180)
    p.add_argument("--model", default="claude-opus-5-5"); p.add_argument("--effort", default="high")
    p.add_argument("--lessons"); p.add_argument("--plan", action="store_true")
    p.add_argument("--no-facts", action="store_true"); p.add_argument("--no-check", action="store_true")
    p.add_argument("--play-draw", choices=("rule", "claude"), default="rule")
    args = p.parse_args()
    lock = threading.Lock()

    def log(text):
        with lock:
            print(time.strftime("%H:%M:%S"), text, flush=True)

    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", args.port))
    server.listen(16)
    log(f"Claude service on 127.0.0.1:{args.port}, default {args.model} {args.effort}, facts={not args.no_facts} "
        f"check={not args.no_check} play_draw={args.play_draw}")
    while True:
        conn, _ = server.accept()
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        threading.Thread(target=serve_seat, args=(conn, args, log), daemon=True).start()


if __name__ == "__main__":
    main()
