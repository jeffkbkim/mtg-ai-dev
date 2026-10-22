"""Players for play/match.py: the biased-random bot and a Claude player (headless Claude Code, one per seat per game)."""
import hashlib, json, os, random, re, subprocess, tempfile, threading, time
from pathlib import Path

from facts import facts_block
from render import BASICS, card_text, clean, events, load_card_text, names_in, option_label, render

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
- Mana is paid automatically. Decisions with only one legal option are answered for you.
- Before the game you decide whether to mulligan (YES: shuffle the hand away and draw a new seven, then put one card
  on the bottom of your library for each mulligan taken).
- PRIORITY: PASS means do nothing now and let the game move on (to the next step, or let the top of the stack resolve).
  Casting a spell and choosing its targets are separate decisions; targets come right after you pick the cast.
- ATTACK and BLOCK are declared one creature at a time; pick DONE when finished. Decide the whole attack (or block)
  before the first declaration and give the plan in that reason.
- "choice" is the option number listed under "Decision:", never an [entry] number from the state.
- You may be asked about the same window several times (e.g. after each spell you cast).
- Each message starts with what changed since your previous decision (life, cards entering or leaving zones).
  At the start of each of your turns the conversation is restarted with a log of the game so far and your recent
  decisions, so keep your reasons informative: they are your notes to yourself.
- Keywords a permanent currently has (including ones granted by Auras) are listed after "has".

Reply with exactly one line of JSON and nothing else:
{"choice": <option number>, "reason": "<one or two sentences: your plan and the main risk you checked>"}
When you PASS priority and want to keep passing while nothing happens, add "pass_until": "end_of_turn" (you will
be asked again at the end step of the opponent's turn, e.g. to cast an instant then) or "my_turn" (asked again at
your next turn). You are always asked again when anything goes on the stack, in your own main phases, during combat,
and for attacks, blocks and other choices."""


PLAN_RULES = """## Your plan
Keep a plan and update it in every reply. Each message shows your current plan. Before choosing, check the plan against
everything that changed since your previous decision, above all what the opponent did (spells, attacks, blocks, cards
revealed), then write the updated plan: revise what the new information changes, keep what still holds. Your choice
should follow the plan; when it doesn't, the reason says why.
In this game every reply is one line of JSON with the plan first:
{"plan": {"role": "...", "win_condition": "...", "race": "...", "opponent_read": "...", "this_turn": "...", "next_turn": "..."}, "choice": <option number>, "reason": "..."}
- role: beatdown or control in this matchup right now, and why.
- win_condition: how you expect to win this game.
- race: turns until you can kill them and until they can kill you, from the board and life totals (libraries too in a long game).
- opponent_read: their colors and likely archetype from what you have seen, and the tricks, removal or flash plays to
  expect and the mana they need.
- this_turn: what you intend for the rest of this turn.
- next_turn: what you intend for your next turn.
Keep each field to one short sentence."""


FACTS_RULES = """## Facts
Some messages end with "Facts:", lines the game computes from the board you see: your untapped mana and that lands
only untap in your own untap step, which of your creatures can block on the opponent's next turn, how much damage at
least gets through if every creature attacks and the defender blocks as well as possible, and how each possible block
or attack ends if nothing else happens. They are exact for the board as it is, but they know nothing that isn't on
the board: tricks, instant-speed removal, flash creatures, face-down creatures being turned up, and abilities that
aren't listed keywords (e.g. "can't block", or a trigger that taps a blocker). Use them as a check on your own reading."""


def gih_table(stats_path=PRIMER_DIR / "dsk_17lands_stats.json", min_games=2000):
    s = json.loads(Path(stats_path).read_text())
    rows = sorted(((v["gih_wr"], k) for k, v in s["cards"].items()
                   if v["gih_wr"] and v["gih_games"] >= min_games and k not in BASICS), reverse=True)
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


def system_prompt(deck_path, texts, lessons=None, plan=False, facts=False):
    """lessons: text of a lessons file (play/primer/lessons_v*.md) placed right after the rules, or None.
    plan: ask for a plan that is updated in every reply (PLAN_RULES). facts: explain the "Facts:" block (FACTS_RULES)."""
    deck = read_deck(deck_path)
    deck_lines = [f"{n}x {card_text(texts[name])}" if name in texts else f"{n}x {name}" for n, name in deck]
    return "\n\n".join([RULES] + ([PLAN_RULES] if plan else []) + ([FACTS_RULES] if facts else []) + ([lessons] if lessons else []) + [(PRIMER_DIR / "dsk_meta.md").read_text(), gih_table(),
                        "Your deck (the opponent's deck is unknown to you):\n" + "\n".join(deck_lines)])


class ClaudeError(RuntimeError):
    """A failed model turn (API error, crash or timeout); cost is what the failed turn still cost."""
    def __init__(self, msg, cost=0.0):
        super().__init__(msg)
        self.cost = cost


class ClaudePlayer:
    """Headless Claude Code (`claude -p`, stream-json) with no tools.

    The conversation restarts at the start of each of the player's own turns with a log of the game so far, so a
    long game doesn't re-read its whole history on every move. "pass_until" lets the player skip empty priority
    windows; those auto-passes are recorded with "auto" and no tokens. A failed or hung model turn is retried in a
    fresh conversation; if that keeps failing the error is raised and match.py stops the run.
    """

    LOG_LINES = 80
    PASS_TARGETS = ("end_of_turn", "my_turn")
    MAX_ERRORS = 2

    def __init__(self, model="claude-opus-5-5", effort="high", lessons=None, plan=False, facts=False, check=False,
                 timeout_s=600):
        self.model, self.effort, self.timeout_s = model, effort, timeout_s
        self.lessons = Path(lessons).read_text() if lessons else None
        self.plan_mode = plan
        self.facts = facts
        self.check = check  # a second look at combat and near-lethal decisions (_check_gate)
        self.name = f"claude:{model}:{effort}" + (f":{Path(lessons).stem}" if lessons else "") + (":plan" if plan else "") + (":facts" if facts else "") + (":check" if check else "")
        self.texts = load_card_text()
        self.proc = None

    def start_game(self, game, deck_path):
        self.seen = set()
        self.log = []          # game log lines this seat can see, plus its own decisions
        self.pending = []      # changes since the last decision the player was actually asked (auto-passes in between)
        self.prev_obs = None
        self.round_turn = None
        self.pass_until = None  # {"target", "turn", "my_turn"} at the time it was set
        self.asked_any = False
        self.conv_pregame = False  # the current conversation has only seen pre-game (mulligan) decisions
        self.plan = None           # latest plan from the player's replies (plan mode)
        self.checked_combat = None  # (turn, ATTACK/BLOCK) of the last combat that got its self-check
        self.workdir = tempfile.mkdtemp(prefix="claude-seat-")
        system = system_prompt(deck_path, self.texts, self.lessons, self.plan_mode, self.facts)
        self.prompt_sha = hashlib.sha256(system.encode()).hexdigest()[:12]  # recorded per decision: prompt versions must not be pooled
        Path(self.workdir, "system.txt").write_text(system)

    def _spawn(self):
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_REMOTE_SESSION_ID")}
        env["CLAUDE_EFFORT"] = self.effort  # an inherited default (e.g. a cloud session's "medium") must not compete with --effort
        self.proc = subprocess.Popen(
            ["claude", "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
             "--model", self.model, "--effort", self.effort, "--system-prompt-file", "system.txt",
             "--tools", "", "--strict-mcp-config", "--setting-sources", "", "--no-session-persistence"],
            cwd=self.workdir, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=open(Path(self.workdir, "stderr.log"), "a"), text=True, bufsize=1)
        self.cost_so_far = 0.0
        self.conv_decisions = 0

    def _close(self):
        if self.proc:
            try:
                self.proc.stdin.close()
                self.proc.wait(timeout=30)
            except (OSError, subprocess.TimeoutExpired):
                self.proc.kill()
            self.proc = None

    def _ask(self, text):
        """Send one user turn, return (result text, per-turn usage, cost of this turn, seconds)."""
        t0 = time.time()
        timer = threading.Timer(self.timeout_s, self.proc.kill)  # a hung turn ends the process, which ends the read loop
        timer.start()
        try:
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
                        raise ClaudeError(f"claude error: {ev.get('result')}", delta)
                    return ev.get("result") or "", ev.get("usage", {}), delta, time.time() - t0
        except OSError as e:
            raise ClaudeError(f"claude process pipe failed: {e}")
        finally:
            timer.cancel()
        err = Path(self.workdir, "stderr.log").read_text()[-500:]
        raise ClaudeError(f"claude process ended (crash or {self.timeout_s} s timeout); stderr: {err}")

    @staticmethod
    def _parse(text, n):
        """(choice, reason, pass_until, plan) from the reply, or Nones."""
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
                return c, str(j.get("reason", "")), j.get("pass_until"), j.get("plan")
        return None, None, None, None

    def _auto_pass(self, msg, g):
        """True if this decision is an empty priority window the player asked to skip."""
        if not self.pass_until:
            return False
        if msg["kind"] != "PRIORITY" or msg["options"][0]["label"] != "PASS":
            return False  # attacks, blocks, targets... are always asked; pass_until stays for later windows
        if g["my_turn"] and g["step"] in ("Precombat Main", "Postcombat Main"):
            return False  # never skip my own main phases (land drops, sorcery-speed plays); pass_until stays
        if any(e.get("attacking") for e in msg["obs"]["entries"]):
            return False  # combat-trick windows (before and after blocks) are always asked
        # Windows where PASS is the only option are answered in Java and never reach us, so the target step may be
        # missed: expire by turn number too (turns are numbered across both players: mine, theirs, mine, ...).
        p = self.pass_until
        if p["target"] == "my_turn":
            reached = g["my_turn"] and g["turn"] != p["turn"]
        else:  # end_of_turn: the end step of the opponent's current turn, or of their next one if set on my turn
            last = p["turn"] + (1 if p["my_turn"] else 0)
            reached = g["turn"] > last or (not g["my_turn"] and g["step"] == "End Turn")
        if reached or g["stack_size"] > 0:
            self.pass_until = None
            return False
        return True

    def _prompt(self, msg, g):
        """This decision's text; starts a conversation (with the game log) if none is running."""
        names = names_in(msg["obs"])
        if self.proc is None:
            self._spawn()
            self.seen = set()  # a new conversation hasn't seen any card text yet
            self.conv_pregame = True
            head = ("A new game starts." if not self.asked_any else
                    "The game continues (your conversation was restarted to keep it short). Game log so far:\n"
                    + "\n".join(self.log[-self.LOG_LINES:]))
        else:
            head = "Since your previous decision: " + ("; ".join(self.pending) if self.pending else "nothing visible changed.")
        self.pending = []
        self.asked_any = True
        self.conv_pregame = self.conv_pregame and g["step"] == "null"
        new = [self.texts[x] for x in sorted(names - self.seen) if x in self.texts]
        self.seen |= names
        self.conv_decisions += 1
        plan = ""
        if self.plan_mode:
            plan = ("Your current plan: " + json.dumps(self.plan) if self.plan else "You have no plan yet: write one.") + "\n"
        return head + "\n" + plan + render(msg, new, facts_block(msg) if self.facts else ())

    def choose(self, msg):
        g = msg["obs"]["entries"][0]
        changes = events(self.prev_obs, msg["obs"])
        self.prev_obs = msg["obs"]
        self.log += [f"turn {g['turn']}: {line}" for line in changes]
        self.pending += changes
        if self._auto_pass(msg, g):
            return 0, {"auto": f"pass_until:{self.pass_until['target']}"}

        # restart the conversation at the start of each of my turns (unless it has only held the mulligan)
        if g["my_turn"] and g["turn"] != self.round_turn:
            self.round_turn = g["turn"]
            if not self.conv_pregame:
                self._close()
        text = self._prompt(msg, g)
        info = {"prompt_text": text, "turns": [], "conversation_decision": self.conv_decisions, "prompt_sha": self.prompt_sha}
        n = len(msg["options"])
        ask, errors, invalid = text, 0, 0
        while True:
            t0 = time.time()
            try:
                out, usage, cost, secs = self._ask(ask)
            except ClaudeError as e:
                info["turns"].append({"error": str(e), "usage": {}, "cost_usd": e.cost, "seconds": round(time.time() - t0, 2)})
                errors += 1
                if errors > self.MAX_ERRORS:
                    raise
                self._close()  # retry in a fresh conversation that carries the game log
                ask = info["prompt_text"] = self._prompt(msg, g)
                continue
            info["turns"].append({"reply": out, "usage": usage, "cost_usd": cost, "seconds": round(secs, 2)})
            choice, reason, until, plan = self._parse(out, n)
            if choice is not None and self.check and self._check_gate(msg, g, choice):
                choice, reason, until, plan = self._self_check(msg, info, choice, reason, until, plan)
            if choice is not None:
                info["reason"] = reason
                if self.plan_mode:
                    if isinstance(plan, dict) and plan:
                        self.plan = info["plan"] = plan
                    else:
                        info["plan_missing"] = True  # the previous plan stays
                if until in self.PASS_TARGETS and msg["kind"] == "PRIORITY" and msg["options"][choice]["label"] == "PASS":
                    self.pass_until = {"target": until, "turn": g["turn"], "my_turn": g["my_turn"]}
                    info["pass_until"] = until
                self.log.append(f"turn {g['turn']}: you chose \"{option_label(msg['options'][choice], msg['obs']['entries'])}\" ({reason})")
                return choice, info
            invalid += 1
            if invalid == 2:
                break
            ask = f"That was not a valid reply. Answer with one line of JSON, choice between 0 and {n - 1}."
        info["invalid"] = True  # recorded, never hidden: fall back to option 0 (PASS / DONE / first option)
        return 0, info

    CHECK_LIFE = 8
    CHECK_TEXT = ("Before this is played, check it once. What is the opponent's best answer: their blocks or attacks, "
                  "tricks or removal they could cast with their untapped mana, and their swing back on their next turn? "
                  "Does anything in the state or Facts contradict your reason? Is there a better line, including lethal "
                  "for you? Then reply with the final one line of JSON, the same choice or a different one.")

    def _check_gate(self, msg, g, choice):
        """The decisions that get a second look: the first attack or block declaration of a combat (the whole
        attack or block is planned there), and any non-PASS choice while either player is at CHECK_LIFE or less."""
        if msg["kind"] in ("ATTACK", "BLOCK"):
            key = (g["turn"], msg["kind"])
            first = key != self.checked_combat
            self.checked_combat = key
            return first
        low = min(g["my_life"], g["opp_life"]) <= self.CHECK_LIFE
        return low and msg["options"][choice]["label"] not in ("PASS", "DONE")

    def _self_check(self, msg, info, choice, reason, until, plan):
        """One more model turn in the same conversation; keeps the first answer if the check fails or is invalid."""
        info["self_check"] = {"first_choice": choice, "first_reason": reason}
        t0 = time.time()
        try:
            out, usage, cost, secs = self._ask(self.CHECK_TEXT)
        except ClaudeError as e:
            info["turns"].append({"error": str(e), "usage": {}, "cost_usd": e.cost, "seconds": round(time.time() - t0, 2),
                                  "self_check": True})
            self._close()  # the next decision starts a fresh conversation with the game log
            info["self_check"]["error"] = True
            return choice, reason, until, plan
        info["turns"].append({"reply": out, "usage": usage, "cost_usd": cost, "seconds": round(secs, 2), "self_check": True})
        c2, r2, u2, p2 = self._parse(out, len(msg["options"]))
        if c2 is None:
            info["self_check"]["invalid"] = True
            return choice, reason, until, plan
        info["self_check"]["changed"] = c2 != choice
        return c2, r2, u2, (p2 if p2 else plan)

    def end_game(self, result):
        self._close()
