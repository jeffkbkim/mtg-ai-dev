"""Players for play/match.py: the biased-random bot and a Claude player (headless Claude Code, one per seat per game)."""
import hashlib, json, os, random, re, subprocess, tempfile, threading, time
from pathlib import Path

import batch
from facts import facts_block
from functools import lru_cache
from render import BASICS, card_text, clean, events, load_card_text, names_in, option_label, render

PRIMER_DIR = Path(__file__).resolve().parent / "primer"



@lru_cache(maxsize=None)
def _card_texts():
    return load_card_text()

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
- Before the game you decide whether to mulligan (YES: shuffle the hand away and draw a new seven). After a mulligan
  you decide again on the new seven; when you keep, you then put one card on the bottom of your library for each
  mulligan taken, one decision per card.
- PRIORITY: PASS means do nothing now and let the game move on (to the next step, or let the top of the stack resolve).
  Casting a spell and choosing its targets are separate decisions; targets come right after you pick the cast.
- ATTACK and BLOCK are declared one creature at a time; pick DONE when finished. Decide the whole attack (or block)
  before the first declaration, give the plan in that reason, and list it all in that reply (see Batching).
- DAMAGE: when your attacking creature is blocked by two or more creatures (or by one, if it has trample), you divide
  its combat damage, one decision per blocker: how much that blocker gets ("(lethal)" marks enough to destroy it).
  Without trample any split is allowed. With trample each blocker must get lethal damage first, and whatever is not
  assigned to blockers goes to the defending player.
- X: a spell or ability with {X} in its cost asks for X once you choose it; the options go up to the most your
  untapped mana can pay.
- "choice" is the option number listed under "Decision:", never an [entry] number from the state.
- You may be asked about the same window several times (e.g. after each spell you cast resolves).
- Each message starts with what changed since your previous decision (life, cards entering or leaving zones).
  At the start of each of your turns the conversation is restarted with a log of the game so far and your recent
  decisions, so keep your reasons informative: they are your notes to yourself.
- Keywords a permanent currently has (including ones granted by Auras) are listed after "has".

Reply with exactly one line of JSON and nothing else:
{"choice": <option number>, "reason": "<one or two sentences: your plan and the main risk you checked>"}
When you PASS priority, say how far to keep passing while nothing happens: "pass_until": "my_main" (asked again in
your next main phase), "end_of_turn" (asked again at the end step of the
opponent's turn, e.g. to cast an instant then) or "my_turn" (asked again at your next turn). Add one to every PASS
unless you mean to act at the very next window; each extra question costs time. You are always asked again when
anything goes on the stack (except your own, on your turn: see below), in your own main phases, during combat, and for attacks, blocks and other choices. Your
own upkeep and draw step are passed for you unless something is on the stack. On your own turn, while only your own
spells and abilities are on the stack, you pass for them: they resolve unless the opponent responds (you are then
asked), so do anything you want done in response before you cast.

Batching: one reply may also cover the decisions that follow it, so you are not asked each one. Add any of these keys
to the same JSON line (entry numbers are the [n] of the current state):
- ATTACK: "attack": [every creature that attacks]. Your choice is one of them (or DONE for no attack); the others are
  declared for you, then DONE.
- BLOCK: "blocks": [[your blocker, the attacker it blocks], ...] for every block. Your choice is one of them.
- A spell or ability you choose that will ask for targets: "targets": [each target in the order asked; "opp" or "me"
  for a player].
- PRIORITY in your own main phase with nothing on the stack: "then": the plays after this one, in order, e.g.
  [{"do": "Cast Murder", "source": 5, "targets": [12]}, {"do": "PASS", "pass_until": "my_turn"}]. "do" is the
  option's text exactly as listed ("Play Swamp", "Cast Murder", an ability's text, or PASS); "source" is the card.
  Leave out "then" when what you do next depends on what happens.
Planned decisions are made only while everything goes as planned: you are asked again as soon as anything differs
(the opponent responds, a trigger or a choice you didn't plan comes up, a card or option is gone), and every trigger's
targets are asked."""


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


PRIMERS = ("v1", "v2")


def card_roles(path=PRIMER_DIR / "dsk_card_roles.json"):
    """One-line playing role per card (play/primer/card_roles.py writes it)."""
    return json.loads(Path(path).read_text())


SET_NAMES = {"DSK": "Duskmourn", "FDN": "Foundations", "CUBE": "Arena Powered Cube"}


def deck_set(deck_path):
    """The set a .dck file is from: the set code its cards are listed under ("4 [FDN:276] Swamp"), Special Guests
    (SPG) aside. DSK when nothing else is found. Cube decks (cards from many sets) say so in their name line
    ("NAME:cube_07 ...", play/cube_deck_pool.py)."""
    text = Path(deck_path).read_text()
    if re.search(r"^NAME:cube", text, re.M | re.I):
        return "CUBE"
    codes = re.findall(r"^\d+ \[(\w+):", text, re.M)
    sets = {c for c in codes if c in SET_NAMES}
    if len(sets) > 1:
        raise ValueError(f"deck mixes sets {sorted(sets)}: {deck_path}")
    return sets.pop() if sets else "DSK"


def system_prompt(deck_path, texts, lessons=None, plan=False, facts=False, primer=None):
    """lessons: text of a lessons file (play/primer/lessons_v*.md) placed right after the rules, or None.
    plan: ask for a plan that is updated in every reply (PLAN_RULES). facts: explain the "Facts:" block (FACTS_RULES).
    primer: "v1" (dsk_meta.md + the 17lands GIH table) or "v2" (dsk_meta_v2.md: archetypes, checks, cards to respect;
    each card in the deck gets its role from dsk_card_roles.json). None: v1 for DSK, v2 for other sets (only v2 exists)."""
    s = deck_set(deck_path)
    primer = primer or ("v1" if s == "DSK" else "v2")
    if primer not in PRIMERS:
        raise ValueError(f"primer must be one of {PRIMERS}, not {primer!r}")
    deck = read_deck(deck_path)
    rules = RULES.replace("Duskmourn (DSK)", f"{SET_NAMES[s]} ({s})")
    if s == "CUBE":
        rules += "\n\n" + CUBE_RULES
    if s != "DSK" and primer != "v2":
        raise ValueError(f"{s} has only primer v2 (play/primer/{s.lower()}_meta_v2.md), not {primer!r}")
    if primer == "v2":
        roles_path = PRIMER_DIR / f"{s.lower()}_card_roles.json"
        roles = card_roles(roles_path) if roles_path.exists() or s != "CUBE" else {}  # the Cube has deck plans instead
        plan_text = deck_plan(deck_path)
        # reminder text in parentheses is dropped: the primer explains the set's mechanics (the Cube's are too many
        # for its primer, so its reminder text stays)
        strip = (lambda t: t) if s == "CUBE" else (lambda t: re.sub(r' ?[(][^()]*[)]', '', t))
        deck_lines = [f"{n}x {strip(card_text(texts[name])) if name in texts else name}"
                      + (f" -- role: {roles[name]}" if name in roles else "") for n, name in deck]
        return "\n\n".join([rules] + ([PLAN_RULES] if plan else []) + ([FACTS_RULES] if facts else []) + ([lessons] if lessons else [])
                            + [(PRIMER_DIR / f"{s.lower()}_meta_v2.md").read_text().strip(),
                               "Your deck (the opponent's deck is unknown to you):\n" + "\n".join(deck_lines)]
                            + ([f"Your deck's plan (written before the game from the deck list):\n{plan_text}"] if plan_text else []))
    deck_lines = [f"{n}x {card_text(texts[name])}" if name in texts else f"{n}x {name}" for n, name in deck]
    return "\n\n".join([rules] + ([PLAN_RULES] if plan else []) + ([FACTS_RULES] if facts else []) + ([lessons] if lessons else []) + [(PRIMER_DIR / "dsk_meta.md").read_text(), gih_table(),
                        "Your deck (the opponent's deck is unknown to you):\n" + "\n".join(deck_lines)])


CUBE_RULES = """Mana in the Cube: mana sources whose cost is more than tapping (Black Lotus, Lotus Petal, Lion's Eye Diamond,
Chromatic Star, Treasure tokens, exert, removing counters) are never used by the automatic payment. They are offered
as ACTIVATE options at priority: activate one yourself before you cast the spell it is for; its mana waits in your
mana pool (shown in the state) until the end of the step, and spells are paid from the pool first. Painful mana
(paying life, or a source that deals damage to you: Talismans, Ancient Tomb, Mana Confluence, painlands) is used
automatically only when painless sources can't pay. Sources making two or more mana at once (Sol Ring, Mana Vault,
Ancient Tomb) are also offered at priority: the automatic payment doesn't use them for a cost smaller than their mana,
so activate one yourself first when you plan to spend its mana on two spells this step. Delve: when you cast a delve
spell you are asked which graveyard cards to exile; the rest is paid with mana."""


def deck_plan(deck_path):
    """The deck's plan (play/cube_deck_pool.py writes <deck>.plan.md next to a Cube deck), or None."""
    p = Path(deck_path).with_suffix(".plan.md")
    return p.read_text().strip() if p.exists() else None


CONCEDE_RULES = """## Conceding
You may concede instead of choosing an option: reply {"concede": true, "reason": "..."}. Concede only when you have no
realistic way to win: you are dead on the opponent's next turn from the board as it is, nothing in your hand or on your
board can stop it, and no likely draw changes that. If you are unsure, keep playing. You will be asked to confirm."""


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
    PASS_TARGETS = ("my_main", "end_of_turn", "my_turn")
    MAX_ERRORS = 2

    def __init__(self, model="claude-opus-5-5", effort="high", lessons=None, plan=False, facts=False, check=False,
                 timeout_s=600, primer=None, concede=False):
        self.model, self.effort, self.timeout_s = model, effort, timeout_s
        self.concede = concede  # may reply {"concede": true} (Playmat's Claude seat; match.py games play to the end)
        # an explicit argument wins over $PRIMER; neither: system_prompt picks by the deck's set (v1 DSK, v2 FDN)
        self.primer = primer or os.environ.get("PRIMER") or None
        if self.primer is not None and self.primer not in PRIMERS:
            raise ValueError(f"primer must be one of {PRIMERS}, not {self.primer!r}")
        self.lessons = Path(lessons).read_text() if lessons else None
        self.plan_mode = plan
        self.facts = facts
        self.check = check  # a second look at combat and near-lethal decisions (_check_gate)
        self.name = f"claude:{model}:{effort}" + (f":{Path(lessons).stem}" if lessons else "") + (":plan" if plan else "") + (":facts" if facts else "") + (":check" if check else "") + (":primer2" if self.primer == "v2" else "")
        self.texts = load_card_text()
        self.set_code = "DSK"  # the deck's set, from start_game
        self.proc = None
        self.fresh = False  # the process was started before the game's first decision (prewarm) and has seen nothing
        self.warm = None

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
        self.restart_note = None   # why the next conversation starts (a take-back), instead of the usual line
        self.batch = None          # the decisions planned by the last answer (batch.py), or None
        self.batch_dropped = None  # why the last plan stopped early, for the next asked decision's record
        self.workdir = tempfile.mkdtemp(prefix="claude-seat-")
        self.set_code = deck_set(deck_path)
        system = system_prompt(deck_path, self.texts, self.lessons, self.plan_mode, self.facts, self.primer)
        if self.concede:
            system += "\n\n" + CONCEDE_RULES
        self.prompt_sha = hashlib.sha256(system.encode()).hexdigest()[:12]  # recorded per decision: prompt versions must not be pooled
        Path(self.workdir, "system.txt").write_text(system)

    def _env(self):
        # Jeff 2026-11-12: a service started from a Claude Code session inherits that session's auth (ANTHROPIC_BASE_URL,
        # CLAUDE_CODE_* host-auth settings); once the session is gone every call fails "Not logged in". The seat's
        # claude must use the Mac's own login, so none of those are passed on.
        env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "ANTHROPIC"))}
        env["CLAUDE_EFFORT"] = self.effort  # an inherited default (e.g. a cloud session's "medium") must not compete with --effort
        # each seat calls again within seconds (batch 2's longest wait was under 5 min), and 5-minute cache writes cost
        # 1.25x input where 1-hour ones (the subscription default) cost 2x
        env["CLAUDE_CODE_PROMPT_CACHE_TTL"] = "5m"
        return env

    def _args(self):
        return ["claude", "-p", "--model", self.model, "--effort", self.effort, "--system-prompt-file", "system.txt",
                "--tools", "", "--strict-mcp-config", "--setting-sources", "", "--no-session-persistence"]

    def prewarm(self):
        """Before the game's first decision (after start_game): start the conversation's process, and write the system
        prompt to the prompt cache with a throwaway one-line call in the background, so the first decision waits on
        neither. The conversation itself is untouched."""
        if self.proc is None:
            self._spawn()
            self.fresh = True
        self.warm = {"done": False}

        def warm():
            t0 = time.time()
            try:
                out = subprocess.run(self._args() + ["--output-format", "json", "Reply with the word OK."], cwd=self.workdir,
                                     env=self._env(), capture_output=True, text=True, timeout=180)
                res = json.loads(out.stdout or "{}")
                self.warm.update(cost_usd=res.get("total_cost_usd", 0.0), cache_write=res.get("usage", {}).get("cache_creation_input_tokens"))
            except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
                self.warm["error"] = str(e)[:200]
            self.warm.update(done=True, seconds=round(time.time() - t0, 2))

        threading.Thread(target=warm, daemon=True).start()

    def warm_info(self):
        """The prewarm's cost and timing so far, for the record of the first decision."""
        return {f"cache_{k}" if k in ("done", "seconds", "error") else k: v for k, v in (self.warm or {}).items()}

    def _spawn(self):
        self.proc = subprocess.Popen(
            self._args()[:2] + ["--input-format", "stream-json", "--output-format", "stream-json", "--verbose"] + self._args()[2:],
            cwd=self.workdir, env=self._env(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
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
        self.fresh = False

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
        """(choice, reason, pass_until, plan, reply dict) from the reply, or Nones."""
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
                return c, str(j.get("reason", "")), j.get("pass_until"), j.get("plan"), j
        return None, None, None, None, None

    def _auto_pass(self, msg, g):
        """Why this decision is a priority window passed without asking (recorded as "auto"), or None to ask."""
        if msg["kind"] != "PRIORITY" or msg["options"][0]["label"] != "PASS":
            return None  # attacks, blocks, targets... are always asked; pass_until stays for later windows
        if g["my_turn"] and g["step"] in ("Upkeep", "Draw") and g["stack_size"] == 0:
            # Jeff 2026-10-29: in the effort batch 847 of these were asked, nearly always answered PASS ("wait for the
            # draw"); the turn's conversation restart made them the first, costliest call of the turn
            return "own_upkeep_draw"
        if self._flip_only_skip(msg, g):
            return "flip_only"
        if not self.pass_until:
            return None
        if g["my_turn"] and g["step"] in ("Precombat Main", "Postcombat Main"):
            if self.pass_until["target"] == "my_main":
                self.pass_until = None
            return None  # never skip my own main phases (land drops, sorcery-speed plays); pass_until stays
        if any(e.get("attacking") for e in msg["obs"]["entries"]):
            return None  # combat-trick windows (before and after blocks) are always asked
        # Windows where PASS is the only option are answered in Java and never reach us, so the target step may be
        # missed: expire by turn number too (turns are numbered across both players: mine, theirs, mine, ...).
        p = self.pass_until
        if p["target"] == "my_main":  # cleared in my main phase above; a later turn means it was missed
            reached = g["turn"] > p["turn"] + (0 if p["my_turn"] else 1)
        elif p["target"] == "my_turn":
            reached = g["my_turn"] and g["turn"] != p["turn"]
        else:  # end_of_turn: the end step of the opponent's current turn, or of their next one if set on my turn
            last = p["turn"] + (1 if p["my_turn"] else 0)
            reached = g["turn"] > last or (not g["my_turn"] and g["step"] == "End Turn")
        if reached or g["stack_size"] > 0:
            self.pass_until = None
            return None
        return f"pass_until:{p['target']}"

    @staticmethod
    def _only_mine_on_stack(msg, g):
        """Jeff 2026-11-05: priority on my own turn with only my own spells and abilities on the stack is passed (they
        resolve unless the opponent responds, and then I'm asked). In batch 03 these were asked 1,412 times and answered
        PASS 99% of the time, and asking ended the turn's planned plays 245 times."""
        if msg["kind"] != "PRIORITY" or msg["options"][0]["label"] != "PASS" or not g["my_turn"] or not g["stack_size"]:
            return False
        stack = [e for e in msg["obs"]["entries"][1:] if e.get("zone") == "STACK"]
        return bool(stack) and all(e.get("mine") for e in stack)

    _FLIP = "Turn this face-down permanent face up"
    _HARMFUL = re.compile(r"damage|destroy|exile|sacrifice|-\d+/-\d+|return [^.]* to [^.]*hand|tap target|stun", re.I)

    def _flip_only_skip(self, msg, g):
        """Jeff 2026-11-08: a window where the only thing to do besides passing is turning a face-down permanent up is
        asked only where flips happen (the recordings since October: the opponent's end step 7/7, combat 5/22, my
        precombat main 2/9; never anywhere else): the opponent's end step, combat once attackers are declared, my
        precombat main phase, and an opponent spell or ability that targets my permanents or could hurt them
        without targeting (flipping in response can matter then). Everywhere else it is passed without asking."""
        entries = msg["obs"]["entries"]
        rest = [o["label"] for o in msg["options"][1:]]
        if not rest or not all(self._FLIP in x for x in rest):
            return False
        if not g["my_turn"] and g["step"] == "End Turn":
            return False
        if g["step"] in ("Declare Attackers", "Declare Blockers") and any(e.get("attacking") for e in entries[1:]):
            return False
        if g["my_turn"] and g["step"] == "Precombat Main":
            return False
        stack = [e for e in entries[1:] if e.get("zone") == "STACK"]
        theirs = [e for e in stack if not e.get("mine")]
        mine = {e["i"] for e in entries[1:] if e.get("mine") and e.get("zone") == "BATTLEFIELD"}
        on_stack = {e["i"] for e in theirs}
        if any(t == "targets" and a in on_stack and b in mine for t, a, b in msg["obs"].get("edges", [])):
            return False
        return not any(self._HARMFUL.search(self._stack_text(e)) for e in theirs)

    def _stack_text(self, e):
        """An object's rules text on the stack: an ability's own text, a spell's card text."""
        if e.get("text"):
            return e["text"]
        c = _card_texts().get(e.get("name") or "")
        return " ".join(c.get("rules", [])) if isinstance(c, dict) else ""

    def _prompt(self, msg, g):
        """This decision's text; starts a conversation (with the game log) if none is running."""
        names = names_in(msg["obs"])
        if self.proc is None or self.fresh:
            if self.proc is None:
                self._spawn()
            self.fresh = False
            self.seen = set()  # a new conversation hasn't seen any card text yet
            self.conv_pregame = True
            head = ("A new game starts." if not self.asked_any else
                    (self.restart_note or "The game continues (your conversation was restarted to keep it short).")
                    + " Game log so far:\n" + "\n".join(self.log[-self.LOG_LINES:]))
            self.restart_note = None
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
        return head + "\n" + plan + render(msg, new, facts_block(msg, self.set_code) if self.facts else ())

    def choose(self, msg):
        g = msg["obs"]["entries"][0]
        changes = events(self.prev_obs, msg["obs"])
        self.prev_obs = msg["obs"]
        self.log += [f"turn {g['turn']}: {line}" for line in changes]
        self.pending += changes
        if self._only_mine_on_stack(msg, g):
            return 0, {"auto": "own_stack"}  # before the plan: passing for my own spell keeps the rest of the plan going
        planned = self._from_batch(msg, g)
        if planned is not None:
            return planned
        auto = self._auto_pass(msg, g)
        if auto:
            return 0, {"auto": auto}

        # restart the conversation at the start of each of my turns (unless it has only held the mulligan)
        if g["my_turn"] and g["turn"] != self.round_turn:
            self.round_turn = g["turn"]
            if not self.conv_pregame:
                self._close()
        text = self._prompt(msg, g)
        info = {"prompt_text": text, "turns": [], "conversation_decision": self.conv_decisions, "prompt_sha": self.prompt_sha}
        if self.batch_dropped:
            info["batch_fallback"], self.batch_dropped = self.batch_dropped, None
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
            if self.concede and self._wants_concede(out) and not info.get("concede_declined"):
                confirm, ccost = self._confirm_concede(info)
                if confirm:
                    info["reason"] = confirm
                    info["concede"] = True
                    self.log.append(f"turn {g['turn']}: you conceded ({confirm})")
                    return 0, info
                ask = "You chose to keep playing. Reply with the one line of JSON for this decision."
                continue
            choice, reason, until, plan, reply = self._parse(out, n)
            if choice is not None and self.check and self._check_gate(msg, g, choice):
                choice, reason, until, plan, reply = self._self_check(msg, info, choice, reason, until, plan, reply)
            if choice is not None:
                info["reason"] = reason
                self._plan_batch(msg, choice, reply, reason, info)
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

    def _plan_batch(self, msg, choice, reply, reason, info):
        """Keep the plan an answer gives for the decisions after it (batch.py); a broken plan is recorded and dropped."""
        self.batch = None
        if not isinstance(reply, dict):
            return
        try:
            plan = batch.make_plan(msg, choice, reply, option_label)
        except ValueError as e:
            info["batch_invalid"] = str(e)
            return
        if plan:
            plan["reason"] = reason
            self.batch = plan
            info["batch"] = {"id": plan["id"], "pos": 0, "of": len(plan["steps"])}

    def _from_batch(self, msg, g):
        """(choice, info) for a decision the current plan answers, or None (the plan is then dropped and the model
        asked). Every planned decision is recorded on its own, with its place in the plan."""
        if not self.batch:
            return None
        plan = self.batch
        rest = plan["steps"][plan["pos"]:]
        if rest and all(s.get("done") for s in rest) and msg["kind"] != rest[0]["kind"]:
            self.batch = None  # the game ended the declarations itself (no attacker or blocker left): the plan is done
            return None
        try:
            k, step = batch.next_choice(plan, msg, option_label)
        except LookupError as e:
            self.batch_dropped = {"id": plan["id"], "pos": plan["pos"], "of": len(plan["steps"]), "why": str(e)}
            self.batch = None
            return None
        plan["pos"] += 1
        info = {"auto": "batch", "batch": {"id": plan["id"], "pos": plan["pos"], "of": len(plan["steps"])},
                "reason": f"(planned) {plan['reason']}", "prompt_sha": self.prompt_sha}
        if plan["pos"] >= len(plan["steps"]):
            self.batch = None
        if step.get("pass_until") in self.PASS_TARGETS and msg["options"][k]["label"] == "PASS":
            self.pass_until = {"target": step["pass_until"], "turn": g["turn"], "my_turn": g["my_turn"]}
            info["pass_until"] = step["pass_until"]
        self.log.append(f"turn {g['turn']}: you chose \"{option_label(msg['options'][k], msg['obs']['entries'])}\" (planned)")
        return k, info

    @staticmethod
    def _wants_concede(text):
        for cand in [text.strip()] + [l.strip() for l in reversed(text.splitlines())]:
            start, end = cand.find("{"), cand.rfind("}")
            if 0 <= start < end:
                try:
                    j = json.loads(cand[start:end + 1])
                except json.JSONDecodeError:
                    continue
                return isinstance(j, dict) and j.get("concede") is True
        return False

    CONCEDE_CHECK = ("Before conceding, check once: is there any line, including your next draws and every card in your "
                     "hand, any block or chump, and any mistake the opponent could make, that keeps you alive and gives "
                     "you a realistic way to win? If there is, keep playing. Reply with one line of JSON: "
                     "{\"concede\": true, \"reason\": \"...\"} to concede, or {\"concede\": false, \"reason\": \"...\"} to play on.")

    def _confirm_concede(self, info):
        """The self-check a concession needs: the confirming reason, or None to play on."""
        t0 = time.time()
        out, usage, cost, secs = self._ask(self.CONCEDE_CHECK)
        info["turns"].append({"reply": out, "usage": usage, "cost_usd": cost, "seconds": round(secs, 2), "concede_check": True})
        if self._wants_concede(out):
            for cand in [out.strip()] + [l.strip() for l in reversed(out.splitlines())]:
                start, end = cand.find("{"), cand.rfind("}")
                try:
                    return str(json.loads(cand[start:end + 1]).get("reason", "")) or "no realistic out", cost
                except (json.JSONDecodeError, ValueError, AttributeError):
                    continue
            return "no realistic out", cost
        info["concede_declined"] = True
        return None, cost

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

    def _self_check(self, msg, info, choice, reason, until, plan, reply=None):
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
            return choice, reason, until, plan, reply
        info["turns"].append({"reply": out, "usage": usage, "cost_usd": cost, "seconds": round(secs, 2), "self_check": True})
        c2, r2, u2, p2, j2 = self._parse(out, len(msg["options"]))
        if c2 is None:
            info["self_check"]["invalid"] = True
            return choice, reason, until, plan, reply
        info["self_check"]["changed"] = c2 != choice
        return c2, r2, u2, (p2 if p2 else plan), j2

    UNDONE = "(undone by {how}) "
    _LINE_TURN = re.compile(r"turn (\d+): ")

    def _take_back(self, to_turn, how):
        """After the log is marked: the game is back at the start of turn to_turn, so the next decision starts a
        fresh conversation with the log (no diff against an observation from the undone part)."""
        self.log.append(f"turn {to_turn}: the game went back to the start of turn {to_turn} ({how}); lines marked "
                        f"\"(undone ...)\" did not happen in this game, though you saw them")
        self.pending, self.prev_obs, self.pass_until = [], None, None
        self.batch, self.batch_dropped = None, None
        self.round_turn, self.checked_combat, self.conv_pregame = None, None, False
        self.asked_any = self.asked_any or bool(self.log)
        self.restart_note = (f"The game went back to the start of turn {to_turn} ({how}), so your conversation was "
                             "restarted. What was undone is marked in the log: it did not happen in this game, but what "
                             "you saw then you still know (and so does your opponent, of what they saw).")
        if not self.fresh:  # a prewarmed process that has seen nothing can start the new conversation
            self._close()

    def rollback(self, to_turn, how="a rollback"):
        """The game went back to the start of turn to_turn (a take-back the opponent asked for). Log lines of that
        turn and later are kept (both players saw them) but marked as undone."""
        if not hasattr(self, "log"):
            return  # no game started yet
        tag = self.UNDONE.format(how=how)
        for i, line in enumerate(self.log):
            m = self._LINE_TURN.match(line)
            if m and int(m.group(1)) >= to_turn:
                self.log[i] = tag + line
        self._take_back(to_turn, how)

    def resume(self, records, from_turn):
        """A game carried on from the start of turn from_turn of an earlier recording (a new table): rebuild the
        log this seat had there from its recorded decisions (each with "undone": how, or None, oldest first), as
        choose() wrote it, then go on as after a rollback. Call after start_game."""
        prev = None
        for r in records:
            if r.get("rule") or r.get("auto") == "own_stack" or r.get("leak_blocked"):
                continue  # answered by the service without the player (choose() never saw it)
            g = r["obs"]["entries"][0]
            tag = self.UNDONE.format(how=r["undone"]) if r.get("undone") else ""
            self.log += [f"{tag}turn {g['turn']}: {line}" for line in events(prev, r["obs"])]
            prev = r["obs"]
            if "reason" in r and 0 <= r.get("choice", -1) < len(r["options"]):
                self.log.append(f"{tag}turn {g['turn']}: you chose \"{option_label(r['options'][r['choice']], r['obs']['entries'])}\" ({r['reason']})")
        self._take_back(from_turn, "a take-back: this game carries on a saved turn of the earlier one")

    def end_game(self, result):
        self._close()
