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
import mage.player.ai.ComputerPlayerControllableProxy;
import mage.target.Target;
import mage.target.TargetCard;

import java.io.Serializable;
import java.util.*;

/**
 * Playmat's standard AI (config.xml "Computer - mad", XMage's ComputerPlayer7), unchanged in play, with its choices
 * recorded for review in PySeat's format (see Shadow). Every record is flagged source "xmage_ai", "reconstructed"
 * (rebuilt from what the AI did, not asked as options) and "clairvoyant": the AI searches copies of the whole game,
 * hidden cards included, so these are not choices made from its own view and are not imitation-learning labels.
 */
public class RecordedMad extends ComputerPlayerControllableProxy {

    private transient Shadow shadow;
    private transient Shadow.Pending pendingPriority;
    private transient int depth;
    private final int skill;

    public RecordedMad(String name, RangeOfInfluence range, int skill) {
        super(name, range, skill);
        this.skill = skill;
    }

    public RecordedMad(final RecordedMad player) {
        super(player);
        this.skill = player.skill;
    }

    @Override
    public RecordedMad copy() {
        return new RecordedMad(this);
    }

    private Shadow shadow() {
        if (shadow == null) shadow = new Shadow(this, "xmage_ai");
        return shadow;
    }

    private boolean recording(Game game) {
        return !game.isSimulation() && depth == 0 && GameRecorder.find(game) != null;
    }

    @Override
    public void init(Game game) {
        super.init(game);
        if (!game.isSimulation()) GameRecorder.of(game).register(this, "xmage_ai", getClass().getName(), skill);
    }

    @Override
    public boolean priority(Game game) {
        if (!recording(game)) return super.priority(game);
        GameRecorder.find(game).ensureDecks();
        Shadow.Pending p = shadow().build("PRIORITY", "priority", game, shadow().priorityOptions(game), null);
        pendingPriority = p;
        try {
            return super.priority(game);
        } finally {
            if (pendingPriority != null) shadow().record(game, p, 0, "exact", null);
            pendingPriority = null;
        }
    }

    @Override
    public boolean activateAbility(ActivatedAbility ability, Game game) {
        if (!ability.isManaAbility() && pendingPriority != null && !game.isSimulation()) {
            Shadow.Pending p = pendingPriority;
            pendingPriority = null;
            int i = Shadow.matchAbility(p.opts, ability, game);
            JsonObject ui = null;
            if (i < 0) { ui = new JsonObject(); ui.addProperty("ability", ability.getAbilityType() + " | " + Shadow.label(game, ability.getSourceId()) + " | " + ability); }
            shadow().record(game, p, i, i < 0 ? "unmapped" : "exact", ui);
            // the AI casts several things in one priority call: each later action is its own priority decision
            boolean r = super.activateAbility(ability, game);
            if (!game.isSimulation() && depth == 0) pendingPriority = shadow().build("PRIORITY", "priority", game, shadow().priorityOptions(game), null);
            return r;
        }
        return super.activateAbility(ability, game);
    }

    private boolean targets(String kind, Target target, Ability source, Game game, Cards cards, java.util.function.BooleanSupplier call) {
        if (!recording(game)) return call.getAsBoolean();
        int before = target.getTargets().size();
        boolean canStop = before >= target.getMinNumberOfTargets();
        Shadow.Pending p = shadow().build(kind, target.getMessage(game), game, shadow().targetOptions(kind, target, source, game, cards, canStop), cards);
        depth++;
        boolean r;
        try {
            r = call.getAsBoolean();
        } finally {
            depth--;
        }
        shadow().recordTargets(game, kind, target, source, cards, before, p, false);
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

    @Override
    public boolean chooseMulligan(Game game) {
        if (!recording(game)) return super.chooseMulligan(game);
        GameRecorder.find(game).ensureDecks();
        List<Shadow.Opt> opts = new ArrayList<>();
        opts.add(new Shadow.Opt("YES mulligan", null, null, "YES"));
        opts.add(new Shadow.Opt("NO keep this hand", null, null, "NO"));
        Shadow.Pending p = shadow().build("USE", "Mulligan? Your hand has " + getHand().size() + " cards", game, opts, null);
        boolean r = super.chooseMulligan(game);
        shadow().record(game, p, r ? 0 : 1, "exact", null);
        return r;
    }

    @Override
    public boolean chooseUse(Outcome outcome, String message, String secondMessage, String trueText, String falseText, Ability source, Game game) {
        if (!recording(game)) return super.chooseUse(outcome, message, secondMessage, trueText, falseText, source, game);
        Shadow.Pending p = shadow().build("USE", message, game, Shadow.yesNo(trueText, falseText, source == null ? null : source.getSourceId()), null);
        depth++;
        boolean r;
        try {
            r = super.chooseUse(outcome, message, secondMessage, trueText, falseText, source, game);
        } finally {
            depth--;
        }
        shadow().record(game, p, r ? 0 : 1, "exact", null);
        return r;
    }

    @Override
    public boolean choose(Outcome outcome, Choice choice, Game game) {
        if (!recording(game) || outcome == Outcome.PutManaInPool || choice.getMessage() != null && choice.getMessage().toLowerCase().contains("mana"))
            return super.choose(outcome, choice, game);
        Shadow.Pending p = shadow().build("CHOICE", choice.getMessage(), game, shadow().choiceOptions(choice), null);
        boolean r = super.choose(outcome, choice, game);
        Object picked = choice.isKeyChoice() ? choice.getChoiceKey() : choice.getChoice();
        int i = Shadow.indexOfRef(p.opts, picked);
        shadow().record(game, p, i, i < 0 ? "unmapped" : "exact", null);
        return r;
    }

    @Override
    public Mode chooseMode(Modes modes, Ability source, Game game) {
        if (!recording(game) || modes.getMode() != null && modes.getMaxModes(game, source) == modes.getSelectedModes().size())
            return super.chooseMode(modes, source, game);
        Shadow.Pending p = shadow().build("MODE", "choose a mode", game, shadow().modeOptions(modes, source, game), null);
        Mode m = super.chooseMode(modes, source, game);
        int i = Shadow.indexOfRef(p.opts, m);
        shadow().record(game, p, i, i < 0 ? "unmapped" : "exact", null);
        return m;
    }

    @Override
    public TriggeredAbility chooseTriggeredAbility(List<TriggeredAbility> abilities, Game game) {
        if (!recording(game) || abilities.isEmpty()) return super.chooseTriggeredAbility(abilities, game);
        Shadow.Pending p = shadow().build("TRIGGER_ORDER", "which trigger goes on the stack first", game, shadow().triggerOptions(abilities, game), null);
        TriggeredAbility t = super.chooseTriggeredAbility(abilities, game);
        int i = Shadow.indexOfRef(p.opts, t);
        shadow().record(game, p, i, i < 0 ? "unmapped" : "exact", null);
        return t;
    }

    @Override
    public void selectAttackers(Game game, UUID attackingPlayerId) {
        if (!recording(game)) { super.selectAttackers(game, attackingPlayerId); return; }
        UUID defender = game.getOpponents(playerId).iterator().next();
        Shadow.Pending p = shadow().build("ATTACK", "declare attackers one at a time", game, shadow().attackOptions(game, defender, Collections.emptySet()), null);
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
        Shadow.Pending p = shadow().build("BLOCK", "declare blockers one at a time", game, shadow().blockOptions(game, Collections.emptySet()), null);
        depth++;
        try {
            super.selectBlockers(source, game, defendingPlayerId);
        } finally {
            depth--;
        }
        shadow().recordSequence(game, p, Shadow.declaredBlocks(game, playerId));
    }
}
