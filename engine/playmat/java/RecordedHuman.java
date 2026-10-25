import com.google.gson.JsonObject;
import mage.abilities.Ability;
import mage.abilities.ActivatedAbility;
import mage.abilities.Mode;
import mage.abilities.Modes;
import mage.abilities.TriggeredAbility;
import mage.cards.Cards;
import mage.choices.Choice;
import mage.constants.Outcome;
import mage.constants.RangeOfInfluence;
import mage.game.Game;
import mage.game.combat.CombatGroup;
import mage.game.permanent.Permanent;
import mage.player.human.HumanPlayer;
import mage.target.Target;
import mage.target.TargetCard;

import java.io.Serializable;
import java.util.*;

/**
 * Playmat's human seat (config.xml "Human"), unchanged in play, with every decision recorded for mtg-ai in PySeat's
 * format (see Shadow). A priority window the browser was never asked about (Playmat's auto-pass and stops) is
 * recorded as a PASS with "auto": "ui_skip". Mana the player taps by hand while paying is not a decision PySeat has;
 * each such tap is counted in the next record's "ui".manual_mana.
 *
 * Blocks: XMage asks again when a declaration breaks a block requirement or restriction (e.g. an attacker that must be
 * blocked if able), so one declare-blockers step can take several declarations. Each one the engine refused is one
 * BLOCK line with choice -1, "mapping": "refused" and the declared blocks in "ui".declared; the legal one is written
 * as the usual sequence when the engine accepts it (the DECLARED_BLOCKERS event), from the blocks XMage holds then,
 * with "block_attempts" (declarations it took) and "engine_adjusted": true when those differ from what was declared.
 *
 * A turn rollback the player asks for ends the priority window it was asked in: that window is recorded as choice -1
 * with "ui".rollback_request (not a PASS), and what the seat still holds (an unaccepted block declaration, hand-tapped
 * mana) is written or dropped when the rollback happens (onRollback). GameRecorder marks the undone decisions.
 */
public class RecordedHuman extends HumanPlayer {

    // pinned (2026-10-24): Playmat saves games as serialized players; a changed class must still read old saves.
    // Keep this value when the class changes, and keep new fields transient or safe to default.
    private static final long serialVersionUID = 1749539587898916129L;

    private transient Shadow shadow;
    private transient int waits;               // browser prompts since the decision started
    private transient int depth;               // nested decisions (a target asked while casting from priority)
    private transient int manualMana;

    public RecordedHuman(String name, RangeOfInfluence range, int skill) {
        super(name, range, skill);
    }

    public RecordedHuman(final RecordedHuman player) {
        super(player);
    }

    @Override
    public RecordedHuman copy() {
        return new RecordedHuman(this);
    }

    private Shadow shadow() {
        if (shadow == null) shadow = new Shadow(this, "human_ui");
        return shadow;
    }

    private boolean recording(Game game) {
        return !game.isSimulation() && GameRecorder.find(game) != null && depth == 0;
    }

    @Override
    public void init(Game game) {
        super.init(game);
        if (game.isSimulation()) return;
        GameRecorder r = GameRecorder.of(game);
        r.register(this, "human", getClass().getName(), 0);
        game.getState().addWatcher(new BlocksDeclared(playerId));
        synchronized (r) {
            r.beforeEnd.add(() -> flushBlocks(game, false));
        }
    }

    @Override
    protected void waitForResponse(Game game) {
        waits++;
        super.waitForResponse(game);
    }

    /**
     * The priority decision is written when its action starts (before the targets and costs it asks for, which are
     * their own decisions), or as PASS when priority ends without one.
     */
    private transient Shadow.Pending pendingPriority;
    private transient int priorityWaits;

    @Override
    public boolean activateAbility(ActivatedAbility ability, Game game) {
        if (ability.isManaAbility()) {
            manualMana++;
        } else if (pendingPriority != null) {
            Shadow.Pending p = pendingPriority;
            pendingPriority = null;
            int choice = Shadow.matchAbility(p.opts, ability, game);
            JsonObject ui = ui(priorityWaits);
            if (choice < 0) ui.addProperty("ability", ability.getAbilityType() + " | " + Shadow.label(game, ability.getSourceId()) + " | " + ability);
            shadow().record(game, p, choice, choice < 0 ? "unmapped" : "exact", ui);
        }
        return super.activateAbility(ability, game);
    }

    private JsonObject ui(int waitsBefore) {
        JsonObject ui = new JsonObject();
        ui.addProperty("prompts", waits - waitsBefore);
        if (manualMana > 0) ui.addProperty("manual_mana", manualMana);
        manualMana = 0;
        return ui;
    }

    // ---------- priority ----------

    @Override
    public boolean priority(Game game) {
        if (!recording(game)) return super.priority(game);
        GameRecorder.find(game).ensureDecks();
        Shadow.Pending p = shadow().build("PRIORITY", "priority", game, shadow().priorityOptions(game), null);
        int w = waits;
        pendingPriority = p;
        priorityWaits = w;
        boolean result;
        try {
            result = super.priority(game);
        } finally {
            boolean acted = pendingPriority == null;
            pendingPriority = null;
            if (!acted && p.opts.size() > 1) {
                JsonObject ui = ui(w);
                if (hasLeft() || hasLost()) {
                    // the window ended with a concession, not a pass
                    ui.addProperty("conceded", true);
                    shadow().record(game, p, -1, "unmapped", ui);
                } else if (game.executingRollback()) {
                    // the window ended with the player's take-back request (XMage aborts the human seats), not a pass
                    ui.addProperty("rollback_request", true);
                    shadow().record(game, p, -1, "unmapped", ui);
                } else {
                    if (waits == w) {
                        // not asked: Playmat's auto-pass or a stop the player didn't set. Recorded so the history has
                        // no gaps
                        ui.addProperty("auto", "ui_skip");
                        p.msg.addProperty("auto", "ui_skip");
                    }
                    shadow().record(game, p, 0, "exact", ui);
                }
            }
        }
        return result;
    }

    // ---------- targets and cards ----------

    private boolean targets(String kind, Target target, Ability source, Game game, Cards cards, java.util.function.BooleanSupplier call) {
        if (!recording(game)) return call.getAsBoolean();
        GameRecorder.find(game).ensureDecks();
        int before = target.getTargets().size();
        boolean canStop = before >= target.getMinNumberOfTargets();
        Shadow.Pending p = shadow().build(kind, target.getMessage(game), game,
                shadow().targetOptions(kind, target, source, game, cards, canStop), cards);
        depth++;
        boolean r;
        try {
            r = call.getAsBoolean();
        } finally {
            depth--;
        }
        shadow().recordTargets(game, kind, target, source, cards, before, p, true);
        return r;
    }

    @Override
    public boolean chooseTarget(Outcome outcome, Target target, Ability source, Game game) {
        return targets("TARGET", target, source, game, null, () -> super.chooseTarget(outcome, target, source, game));
    }

    @Override
    public boolean choose(Outcome outcome, Target target, Ability source, Game game, Map<String, Serializable> options) {
        return targets("CHOOSE", target, source, game, null, () -> super.choose(outcome, target, source, game, options));
    }

    @Override
    public boolean choose(Outcome outcome, Cards cards, TargetCard target, Ability source, Game game) {
        return targets("CHOOSE_CARDS", target, source, game, cards, () -> super.choose(outcome, cards, target, source, game));
    }

    @Override
    public boolean chooseTarget(Outcome outcome, Cards cards, TargetCard target, Ability source, Game game) {
        return targets("TARGET_CARDS", target, source, game, cards, () -> super.chooseTarget(outcome, cards, target, source, game));
    }

    // ---------- small choices ----------

    @Override
    public boolean chooseMulligan(Game game) {
        if (!recording(game)) return super.chooseMulligan(game);
        GameRecorder.find(game).ensureDecks();
        List<Shadow.Opt> opts = new ArrayList<>();
        opts.add(new Shadow.Opt("YES mulligan", null, null, "YES"));
        opts.add(new Shadow.Opt("NO keep this hand", null, null, "NO"));
        Shadow.Pending p = shadow().build("USE", "Mulligan? Your hand has " + getHand().size() + " cards", game, opts, null);
        int w = waits;
        boolean r = super.chooseMulligan(game);
        shadow().record(game, p, r ? 0 : 1, "exact", ui(w));
        return r;
    }

    @Override
    public boolean chooseUse(Outcome outcome, String message, String secondMessage, String trueText, String falseText, Ability source, Game game) {
        if (!recording(game)) return super.chooseUse(outcome, message, secondMessage, trueText, falseText, source, game);
        Shadow.Pending p = shadow().build("USE", message, game, Shadow.yesNo(trueText, falseText, source == null ? null : source.getSourceId()), null);
        int w = waits;
        boolean r = super.chooseUse(outcome, message, secondMessage, trueText, falseText, source, game);
        shadow().record(game, p, r ? 0 : 1, "exact", ui(w));
        return r;
    }

    @Override
    public boolean choose(Outcome outcome, Choice choice, Game game) {
        // mana colour choices belong to paying, as in PySeat
        if (!recording(game) || outcome == Outcome.PutManaInPool || choice.getMessage() != null && choice.getMessage().toLowerCase().contains("mana"))
            return super.choose(outcome, choice, game);
        Shadow.Pending p = shadow().build("CHOICE", choice.getMessage(), game, shadow().choiceOptions(choice), null);
        int w = waits;
        boolean r = super.choose(outcome, choice, game);
        Object picked = choice.isKeyChoice() ? choice.getChoiceKey() : choice.getChoice();
        int i = Shadow.indexOfRef(p.opts, picked);
        JsonObject ui = ui(w);
        if (i < 0) ui.addProperty("answer", String.valueOf(picked));
        shadow().record(game, p, i, i < 0 ? "unmapped" : "exact", ui);
        return r;
    }

    @Override
    public Mode chooseMode(Modes modes, Ability source, Game game) {
        if (!recording(game) || modes.getMode() != null && modes.getMaxModes(game, source) == modes.getSelectedModes().size())
            return super.chooseMode(modes, source, game);
        Shadow.Pending p = shadow().build("MODE", "choose a mode", game, shadow().modeOptions(modes, source, game), null);
        int w = waits;
        Mode m = super.chooseMode(modes, source, game);
        int i = Shadow.indexOfRef(p.opts, m);
        shadow().record(game, p, i, i < 0 ? "unmapped" : "exact", ui(w));
        return m;
    }

    @Override
    public TriggeredAbility chooseTriggeredAbility(List<TriggeredAbility> abilities, Game game) {
        if (!recording(game) || abilities.isEmpty()) return super.chooseTriggeredAbility(abilities, game);
        Shadow.Pending p = shadow().build("TRIGGER_ORDER", "which trigger goes on the stack first", game, shadow().triggerOptions(abilities, game), null);
        int w = waits;
        TriggeredAbility t = super.chooseTriggeredAbility(abilities, game);
        int i = Shadow.indexOfRef(p.opts, t);
        shadow().record(game, p, i, i < 0 ? "unmapped" : "exact", ui(w));
        return t;
    }

    // ---------- combat ----------

    @Override
    public void selectAttackers(Game game, UUID attackingPlayerId) {
        if (!recording(game)) { super.selectAttackers(game, attackingPlayerId); return; }
        UUID defender = game.getOpponents(playerId).iterator().next();
        Shadow.Pending p = shadow().build("ATTACK", "declare attackers one at a time", game,
                shadow().attackOptions(game, defender, Collections.emptySet()), null);
        depth++;
        try {
            super.selectAttackers(game, attackingPlayerId);
        } finally {
            depth--;
        }
        List<Object> picked = new ArrayList<>();
        for (UUID a : game.getCombat().getAttackers()) {
            mage.game.permanent.Permanent perm = game.getPermanent(a);
            if (perm != null && playerId.equals(perm.getControllerId())) picked.add(a);
        }
        shadow().recordSequence(game, p, picked);
    }

    /** This step's declaration so far: the decision, what was declared, how many declarations, when. */
    private transient Shadow.Pending blockPending;
    private transient List<Object> blockDeclared;
    private transient int blockAttempts;
    private transient long blockTs;
    private transient int blockTurn;

    @Override
    public void selectBlockers(Ability source, Game game, UUID defendingPlayerId) {
        // Jeff 2026-10-25: not asked when none of the player's creatures can legally block any attacker (XMage lists
        // every untapped creature and checks evasion only on declaring). A one-option question isn't a recorded
        // decision; the game log says why it was skipped.
        if (blockPending == null && noLegalBlock(game)) {
            game.informPlayers(getLogName() + " has no legal blockers: no blocks (skipped)");
            return;
        }
        if (!recording(game)) { super.selectBlockers(source, game, defendingPlayerId); return; }
        if (blockPending != null && blockTurn != game.getTurnNum()) flushBlocks(game, false);  // never accepted (shouldn't happen)
        if (blockPending != null) {
            // asked again in the same step: XMage refused the previous declaration
            JsonObject ui = new JsonObject();
            com.google.gson.JsonArray declared = new com.google.gson.JsonArray();
            for (Object ref : blockDeclared) {
                int i = Shadow.indexOfRef(blockPending.opts, ref);
                declared.add(i < 0 ? String.valueOf(ref) : blockPending.opts.get(i).label.replaceAll("<[^>]+>", "").replaceAll(" ?\\[[0-9a-f]{3}\\]", ""));
            }
            ui.add("declared", declared);
            blockPending.msg.addProperty("ts_at", blockTs);
            shadow().record(game, blockPending, -1, "refused", ui);
        } else {
            blockAttempts = 0;
        }
        Shadow.Pending p = shadow().build("BLOCK", "declare blockers one at a time", game,
                shadow().blockOptions(game, Collections.emptySet()), null);
        depth++;
        try {
            super.selectBlockers(source, game, defendingPlayerId);
        } finally {
            depth--;
        }
        blockPending = p;
        blockDeclared = Shadow.declaredBlocks(game, playerId);
        blockAttempts++;
        blockTs = System.currentTimeMillis();
        blockTurn = game.getTurnNum();
    }

    /**
     * None of this player's creatures can legally block any attacker, by XMage's own check for each blocker and
     * attacker (evasion such as flying, fear and intimidate, "can block only creatures with flying", can't-block
     * effects, protection), and an attacker that must be blocked by two or more (menace) needs that many.
     */
    boolean noLegalBlock(Game game) {
        List<Permanent> blockers = getAvailableBlockers(game);
        for (CombatGroup group : game.getCombat().getGroups()) {
            if (group.getAttackers().isEmpty() || !playerId.equals(group.getDefendingPlayerId())) continue;
            Permanent attacker = game.getPermanent(group.getAttackers().get(0));
            int needed = attacker == null ? 1 : Math.max(1, attacker.getMinBlockedBy());
            int able = 0;
            for (Permanent blocker : blockers) if (group.canBlock(blocker, game)) able++;
            if (able >= needed) return false;
        }
        return true;
    }

    /**
     * The step's last declaration, written once the engine has accepted it (accepted) or the game ended first: the
     * blocks XMage holds, flagged when they differ from what the player declared.
     */
    void flushBlocks(Game game, boolean accepted) {
        flushBlocks(game, accepted, false);
    }

    private void flushBlocks(Game game, boolean accepted, boolean rolledBack) {
        Shadow.Pending p = blockPending;
        if (p == null) return;
        blockPending = null;
        List<Object> held = accepted ? Shadow.declaredBlocks(game, playerId) : blockDeclared;
        JsonObject extra = new JsonObject();
        extra.addProperty("block_attempts", blockAttempts);
        if (!new HashSet<>(held).equals(new HashSet<>(blockDeclared))) {
            extra.addProperty("engine_adjusted", true);
            com.google.gson.JsonArray declared = new com.google.gson.JsonArray();
            for (Object ref : blockDeclared) declared.add(String.valueOf(ref));
            extra.add("declared", declared);
        }
        if (!accepted) extra.addProperty("block_unconfirmed", true);  // the game ended before the engine accepted it
        if (rolledBack) extra.addProperty("rolled_back", true);  // a rollback came before the engine accepted it
        p.msg.add("extra", extra);
        p.msg.addProperty("ts_at", blockTs);
        shadow().recordSequence(game, p, held);
    }

    /**
     * The game is going back to the start of an earlier turn (GameRecorder, from the game log; the state isn't put
     * back yet). A block declaration the engine never accepted is written as it stood (superseded at the merge, like
     * everything else of the undone turns); mana tapped by hand in the undone part is dropped, not counted against the
     * next decision.
     */
    void onRollback(Game game) {
        if (blockPending != null) flushBlocks(game, false, true);
        blockPending = null;
        blockDeclared = null;
        blockAttempts = 0;
        blockTurn = 0;
        pendingPriority = null;
        manualMana = 0;
        depth = 0;  // the rollback runs from the game loop, outside any of this seat's decisions
    }

    /** Tells the defending RecordedHuman when the engine has accepted its blocks. */
    static final class BlocksDeclared extends mage.watchers.Watcher {
        private static final long serialVersionUID = 3609735809894604730L;  // pinned, see above
        BlocksDeclared(UUID playerId) {
            super(mage.constants.WatcherScope.PLAYER);
            this.controllerId = playerId;
        }

        @Override
        public void watch(mage.game.events.GameEvent event, Game game) {
            if (event.getType() != mage.game.events.GameEvent.EventType.DECLARED_BLOCKERS || game.isSimulation()
                    || !controllerId.equals(event.getPlayerId())) return;
            mage.players.Player p = game.getPlayer(controllerId);
            if (p instanceof RecordedHuman) ((RecordedHuman) p).flushBlocks(game, true);
        }
    }

    /** The deck's name as the web client sent it (for the AI, how its deck was matched to the player's) goes to config.json. */
    @Override
    public void useDeck(mage.cards.decks.Deck deck, Game game) {
        super.useDeck(deck, game);
        GameRecorder r = GameRecorder.find(game);
        if (r != null && !game.isSimulation()) r.setSeatInfo(r.seat(playerId), "deck_name", String.valueOf(deck.getName()));  // how the web client picked it
    }
}
