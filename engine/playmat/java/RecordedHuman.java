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
 */
public class RecordedHuman extends HumanPlayer {

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
        if (!game.isSimulation()) GameRecorder.of(game).register(this, "human", getClass().getName(), 0);
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
                if (waits == w) {
                    // not asked: Playmat's auto-pass or a stop the player didn't set. Recorded so the history has no gaps
                    ui.addProperty("auto", "ui_skip");
                    p.msg.addProperty("auto", "ui_skip");
                }
                shadow().record(game, p, 0, "exact", ui);
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

    @Override
    public void selectBlockers(Ability source, Game game, UUID defendingPlayerId) {
        if (!recording(game)) { super.selectBlockers(source, game, defendingPlayerId); return; }
        Shadow.Pending p = shadow().build("BLOCK", "declare blockers one at a time", game,
                shadow().blockOptions(game, Collections.emptySet()), null);
        depth++;
        try {
            super.selectBlockers(source, game, defendingPlayerId);
        } finally {
            depth--;
        }
        shadow().recordSequence(game, p, Shadow.declaredBlocks(game, playerId));
    }
}
