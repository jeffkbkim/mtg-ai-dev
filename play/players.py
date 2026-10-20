"""Players for play/match.py: the biased-random bot and a Claude player (headless Claude Code, one per seat per game)."""
import json, os, random, re, subprocess, tempfile, time
from pathlib import Path

from render import card_text, clean, events, load_card_text, names_in, render

PRIMER_DIR = Path(__file__).resolve().parent / "primer"


class RandomPlayer:
    """Same policy as engine/xmage/run_games.py: take a non-PASS/DONE option 80% of the time when there is one."""
    name = "random"

    def __init__(self, seed):
        self.rng = random.Random(seed)

    def start_game(self, game, deck_path):
        pass

    def choose(self, msg):
        n = len(msg["options"])
        if n > 1 and msg["options"][0]["label"] in ("PASS", "DONE") and self.rng.random() < 0.8:
            return self.rng.randrange(1, n), {}
        return self.rng.randrange(n), {}

    def end_game(self, result):
        pass


RULES = """You are playing a game of Magic: The Gathering, Duskmourn (DSK) Limited, 40-card decks, best of one.
You control one seat. You see exactly what a player at the table would see: your hand, both battlefields,
graveyards, exile, the stack, and counts of the opponent's hand and library. Play to win.

How the game talks to you:
- Each message is one decision: the current state as numbered entries, then numbered options.
- Mana is paid automatically. Decisions with only one legal option are answered for you. Mulligans are automatic.
- PRIORITY: PASS means do nothing now and let the game move on (to the next step, or let the top of the stack resolve).
  Casting a spell and choosing its targets are separate decisions; targets come right after you pick the cast.
- ATTACK and BLOCK are declared one creature at a time; pick DONE when finished.
- You may be asked about the same window several times (e.g. after each spell you cast).
- Each message starts with what changed since your previous decision (life, cards entering or leaving zones).
  At the start of each of your turns the conversation is restarted with a log of the game so far and your recent
  decisions, so keep your reasons informative: they are your notes to yourself.
- Keywords a permanent currently has (including ones granted by Auras) are listed after "has".

Reply with exactly one line of JSON and nothing else:
{"choice": <option number>, "reason": "<one short sentence explaining the move>"}
When you PASS priority and want to keep passing while nothing happens, add "pass_until": "end_of_turn" (you will
be asked again at the end step of the opponent's turn, e.g. to cast an instant then) or "my_turn". You are always
asked again when anything goes on the stack and for attacks, blocks and other choices."""


def gih_table(stats_path=PRIMER_DIR / "dsk_17lands_stats.json", min_games=2000):
    s = json.loads(Path(stats_path).read_text())
    rows = sorted(((v["gih_wr"], k) for k, v in s["cards"].items() if v["gih_wr"] and v["gih_games"] >= min_games), reverse=True)
    return (f"17lands 'games in hand' win rate per card (DSK Premier Draft, {s['games']} games, average {s['win_rate']:.1%}; "
            f"higher means the card wins more when drawn; cards with under {min_games} games omitted):\n"
            + "\n".join(f"{wr:.1%} {k}" for wr, k in rows))


def read_deck(deck_path):
    out = []
    for line in Path(deck_path).read_text().splitlines():
        m = re.match(r"(\d+) \[[^\]]*\] (.+)", line.strip())
        if m:
            out.append((int(m.group(1)), m.group(2)))
    return out


def system_prompt(deck_path, texts):
    deck = read_deck(deck_path)
    deck_lines = [f"{n}x {card_text(texts[name])}" if name in texts else f"{n}x {name}" for n, name in deck]
    return "\n\n".join([RULES, (PRIMER_DIR / "dsk_meta.md").read_text(), gih_table(),
                        "Your deck (the opponent's deck is unknown to you):\n" + "\n".join(deck_lines)])


class ClaudePlayer:
    """Headless Claude Code (`claude -p`, stream-json) with no tools.

    The conversation restarts at the start of each of the player's own turns with a log of the game so far, so a
    long game doesn't re-read its whole history on every move. "pass_until" lets the player skip empty priority
    windows; those auto-passes are recorded with "auto" and no tokens.
    """

    LOG_LINES = 80
    PASS_TARGETS = ("end_of_turn", "my_turn")

    def __init__(self, model="claude-opus-5-5", effort="high", timeout_s=600):
        self.model, self.effort, self.timeout_s = model, effort, timeout_s
        self.name = f"claude:{model}:{effort}"
        self.texts = load_card_text()
        self.proc = None

    def start_game(self, game, deck_path):
        self.seen = set()
        self.log = []          # game log lines this seat can see, plus its own decisions
        self.prev_obs = None
        self.round_turn = None
        self.pass_until = None
        self.workdir = tempfile.mkdtemp(prefix="claude-seat-")
        Path(self.workdir, "system.txt").write_text(system_prompt(deck_path, self.texts))

    def _spawn(self):
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_REMOTE_SESSION_ID")}
        env["CLAUDE_EFFORT"] = self.effort  # an inherited default (e.g. a cloud session's "medium") must not compete with --effort
        self.proc = subprocess.Popen(
            ["claude", "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
             "--model", self.model, "--effort", self.effort, "--system-prompt-file", "system.txt",
             "--tools", "", "--strict-mcp-config", "--setting-sources", "", "--no-session-persistence"],
            cwd=self.workdir, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self.cost_so_far = 0.0
        self.conv_decisions = 0

    def _close(self):
        if self.proc:
            self.proc.stdin.close()
            try:
                self.proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None

    def _ask(self, text):
        """Send one user turn, return (result text, per-turn usage, cost of this turn, seconds)."""
        t0 = time.time()
        self.proc.stdin.write(json.dumps({"type": "user", "message": {"role": "user", "content": text}}) + "\n")
        self.proc.stdin.flush()
        for line in self.proc.stdout:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "result":
                cost = ev.get("total_cost_usd") or 0.0  # cumulative for the process
                delta, self.cost_so_far = cost - self.cost_so_far, cost
                if ev.get("is_error"):
                    raise RuntimeError(f"claude error: {ev.get('result')}")
                return ev.get("result") or "", ev.get("usage", {}), delta, time.time() - t0
        raise RuntimeError("claude process ended")

    @staticmethod
    def _parse(text, n):
        """(choice, reason, pass_until) from the reply, or (None, None, None)."""
        # whole reply, then each line, from the last; reasons can hold mana symbols like {3}{G}, so no brace regex
        candidates = [text.strip()] + [l.strip() for l in reversed(text.splitlines())]
        for cand in candidates:
            start, end = cand.find("{"), cand.rfind("}")
            if start < 0 or end < start:
                continue
            try:
                j = json.loads(cand[start:end + 1])
            except json.JSONDecodeError:
                continue
            c = j.get("choice") if isinstance(j, dict) else None
            if isinstance(c, int) and 0 <= c < n:
                return c, str(j.get("reason", "")), j.get("pass_until")
        return None, None, None

    def _auto_pass(self, msg, g):
        """True if this decision is an empty priority window the player asked to skip."""
        if not self.pass_until:
            return False
        if msg["kind"] != "PRIORITY" or msg["options"][0]["label"] != "PASS":
            return False  # attacks, blocks, targets... are always asked; pass_until stays for later windows
        reached = g["my_turn"] if self.pass_until == "my_turn" else (not g["my_turn"] and g["step"] == "End Turn")
        if reached or g["stack_size"] > 0:
            self.pass_until = None
            return False
        return True

    def choose(self, msg):
        g = msg["obs"]["entries"][0]
        for line in events(self.prev_obs, msg["obs"]):
            self.log.append(f"turn {g['turn']}: {line}")
        changes = events(self.prev_obs, msg["obs"])
        self.prev_obs = msg["obs"]
        if self._auto_pass(msg, g):
            return 0, {"auto": f"pass_until:{self.pass_until}"}

        # restart the conversation at the start of each of my turns, carrying the game log
        if g["my_turn"] and g["turn"] != self.round_turn:
            self.round_turn = g["turn"]
            self._close()
        names = names_in(msg["obs"])
        if self.proc is None:
            fresh = not self.log or self.seen == set()
            self._spawn()
            self.seen = set()  # a new conversation hasn't seen any card text yet
            head = ("A new game starts." if fresh else
                    "The game continues (your conversation was restarted at the start of your turn). Game log so far:\n"
                    + "\n".join(self.log[-self.LOG_LINES:]))
        else:
            head = "Since your previous decision: " + ("; ".join(changes) if changes else "nothing visible changed.")
        new = [self.texts[x] for x in sorted(names - self.seen) if x in self.texts]
        self.seen |= names
        self.conv_decisions += 1
        text = head + "\n" + render(msg, new)
        info = {"prompt_text": text, "turns": [], "conversation_decision": self.conv_decisions}
        n = len(msg["options"])
        for attempt in range(2):
            out, usage, cost, secs = self._ask(text if attempt == 0 else
                                               f"That was not a valid reply. Answer with one line of JSON, choice between 0 and {n - 1}.")
            info["turns"].append({"reply": out, "usage": usage, "cost_usd": cost, "seconds": round(secs, 2)})
            choice, reason, until = self._parse(out, n)
            if choice is not None:
                info["reason"] = reason
                if until in self.PASS_TARGETS and msg["kind"] == "PRIORITY" and msg["options"][choice]["label"] == "PASS":
                    self.pass_until = info["pass_until"] = until
                self.log.append(f"turn {g['turn']}: you chose \"{clean(msg['options'][choice]['label'])}\" ({reason})")
                return choice, info
        info["invalid"] = True  # recorded, never hidden: fall back to option 0 (PASS / DONE / first option)
        return 0, info

    def end_game(self, result):
        self._close()
