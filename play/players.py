"""Players for play/match.py: the biased-random bot and a Claude player (headless Claude Code, one per seat per game)."""
import json, os, random, re, subprocess, tempfile, time
from pathlib import Path

from render import card_text, load_card_text, names_in, render

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
- You cannot see what happened between your decisions except through the state; remember the game from earlier messages.

Reply with exactly one line of JSON and nothing else:
{"choice": <option number>, "reason": "<one short sentence explaining the move>"}"""


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
    """Headless Claude Code (`claude -p`, stream-json) with no tools. One conversation per game, so it remembers the game."""

    def __init__(self, model="claude-opus-5-5", effort="high", timeout_s=600):
        self.model, self.effort, self.timeout_s = model, effort, timeout_s
        self.name = f"claude:{model}:{effort}"
        self.texts = load_card_text()
        self.proc = None

    def start_game(self, game, deck_path):
        self.seen = set()
        self.decisions = 0
        self.cost_so_far = 0.0
        self.workdir = tempfile.mkdtemp(prefix="claude-seat-")
        Path(self.workdir, "system.txt").write_text(system_prompt(deck_path, self.texts))
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_REMOTE_SESSION_ID")}
        env["CLAUDE_EFFORT"] = self.effort  # an inherited default (e.g. a cloud session's "medium") must not compete with --effort
        self.proc = subprocess.Popen(
            ["claude", "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
             "--model", self.model, "--effort", self.effort, "--system-prompt-file", "system.txt",
             "--tools", "", "--strict-mcp-config", "--setting-sources", "", "--no-session-persistence"],
            cwd=self.workdir, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)

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
                return c, str(j.get("reason", ""))
        return None, None

    def choose(self, msg):
        names = names_in(msg["obs"])
        new = [self.texts[x] for x in sorted(names - self.seen) if x in self.texts]
        self.seen |= names
        self.decisions += 1
        text = render(msg, new)
        if self.decisions == 1:
            text = "A new game starts.\n" + text
        info = {"prompt_text": text, "turns": []}
        n = len(msg["options"])
        for attempt in range(2):
            out, usage, cost, secs = self._ask(text if attempt == 0 else
                                               f"That was not a valid reply. Answer with one line of JSON, choice between 0 and {n - 1}.")
            info["turns"].append({"reply": out, "usage": usage, "cost_usd": cost, "seconds": round(secs, 2)})
            choice, reason = self._parse(out, n)
            if choice is not None:
                info["reason"] = reason
                return choice, info
        info["invalid"] = True  # recorded, never hidden: fall back to option 0 (PASS / DONE / first option)
        return 0, info

    def end_game(self, result):
        if self.proc:
            self.proc.stdin.close()
            try:
                self.proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None
