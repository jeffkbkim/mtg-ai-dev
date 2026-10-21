import com.google.gson.Gson;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import mage.MageObject;
import mage.abilities.Ability;
import mage.abilities.ActivatedAbility;
import mage.abilities.Mode;
import mage.abilities.Modes;
import mage.abilities.TriggeredAbility;
import mage.cards.Card;
import mage.cards.Cards;
import mage.choices.Choice;
import mage.constants.Outcome;
import mage.constants.RangeOfInfluence;
import mage.game.Game;
import mage.game.combat.CombatGroup;
import mage.game.permanent.Permanent;
import mage.player.ai.ComputerPlayer;
import mage.target.Target;
import mage.target.TargetCard;

import java.io.*;
import java.util.*;

/**
 * Spike step 3: each decision goes to Python with this seat's observation (built from XMage's per-seat view)
 * and options that point at observation entries. Forced decisions (one option) are answered here.
 * Every outgoing message is checked against the full game state for hidden-information leaks.
 */
public class PySeat extends ComputerPlayer {

    static final class Link {
        final BufferedReader in;
        final PrintWriter out;
        final Gson gson = new Gson();
        final Map<String, Integer> asked = new TreeMap<>();
        final Map<String, Integer> forced = new TreeMap<>();
        final Map<String, Integer> fallback = new TreeMap<>();
        final List<String> rejected = new ArrayList<>();
        final Map<String, Integer> leaks = new TreeMap<>();
        final Map<String, Integer> unseenRefs = new TreeMap<>();
        final Map<String, Integer> unmappedAbilities = new TreeMap<>();
        final Map<String, Integer> unmappedChoices = new TreeMap<>();
        // coverage: abilities on permanents keyed through a grant, and ones with no key (would be unmapped if used)
        final Map<String, Integer> grantedOnBoard = new TreeMap<>();
        final Map<String, Integer> unkeyedOnBoard = new TreeMap<>();
        long roundTripNanos = 0, observeNanos = 0;
        int roundTrips = 0, bytes = 0;

        Link(InputStream in, OutputStream out) {
            this.in = new BufferedReader(new InputStreamReader(in));
            this.out = new PrintWriter(new OutputStreamWriter(out), true);
        }
    }

    /** One choice: what it acts on (engine ids, mapped to entry indices before sending) and what to do if picked. */
    static final class Option {
        final String label;
        final UUID source, target;
        final Runnable onPick;
        String action;      // action type name for the encoder
        String abilityKey;  // stable ability key for ACTIVATE / trigger options
        String choiceKey;   // named non-card answer (alternative cost, mode, named choice), not its list position
        Option(String label, UUID source, UUID target, Runnable onPick) {
            this.label = label; this.source = source; this.target = target; this.onPick = onPick;
        }
        Option as(String action) { this.action = action; return this; }
        Option key(String k) { this.abilityKey = k; return this; }
        Option choice(String k) { this.choiceKey = k; return this; }
    }

    final transient Link link;
    private transient Set<UUID> failedThisWindow = new HashSet<>();
    private transient String windowKey = "";
    // abilities XMage lists as playable but refused without asking this seat anything (e.g. Crew with no other
    // untapped creature): skip them until the board, hand, life or stack changes, instead of re-offering every step
    private transient Map<UUID, String> refusedAt = new HashMap<>();

    public PySeat(String name, Link link) {
        super(name, RangeOfInfluence.ONE);
        this.link = link;
    }

    public PySeat(final PySeat player) {
        super(player);
        this.link = player.link;
    }

    @Override
    public PySeat copy() {
        return new PySeat(this);
    }

    private JsonObject ref(Observer.Obs obs, UUID id, String kind, Game game) {
        JsonObject r = new JsonObject();
        if (id == null) return r;
        String player = obs.playerRef(id);
        if (player != null) {
            r.addProperty("player", player);
            return r;
        }
        // a Room door (card half) acts for the whole Room card
        MageObject obj = game.getObject(id);
        // a spell on the stack acts through its card (e.g. a resolving spell that asks a choice)
        if (obj instanceof mage.game.stack.Spell) {
            mage.game.stack.Spell spell = (mage.game.stack.Spell) obj;
            id = obs.index.containsKey(spell.getId()) ? spell.getId() : spell.getSourceId();
            obj = game.getObject(id);
        }
        if (obj instanceof mage.cards.SubCard) id = ((mage.cards.SubCard<?>) obj).getParentCard().getId();
        Integer i = obs.index.get(id);
        if (i == null) i = Observer.addCasting(obs, game, id);
        if (i != null) {
            r.addProperty("entry", i);
        } else {
            MageObject o = game.getObject(id);
            link.unseenRefs.merge(kind + ":" + (o == null ? "?" : o.getClass().getSimpleName()), 1, Integer::sum);
            r.addProperty("unseen", true);
        }
        return r;
    }

    /** Send one decision with the observation; return the picked option. Answers forced decisions locally. */
    private int pick(String kind, String prompt, Game game, List<Option> options, Collection<UUID> offered) {
        if (options.isEmpty()) throw new IllegalStateException("no options for " + kind);
        if (options.size() == 1) {
            link.forced.merge(kind, 1, Integer::sum);
            options.get(0).onPick.run();
            return 0;
        }
        link.asked.merge(kind, 1, Integer::sum);
        long t0 = System.nanoTime();
        Observer.Obs obs = Observer.build(game, playerId, offered);
        for (mage.game.permanent.Permanent p : game.getBattlefield().getAllActivePermanents()) {
            for (Ability a : p.getAbilities(game)) {
                if (!AbilityKeys.keyed(a)) continue;
                String key = AbilityKeys.key(game, a);
                if (key == null) link.unkeyedOnBoard.merge(p.getName() + ": " + a.getRule(), 1, Integer::sum);
                else if (key.contains("#g")) link.grantedOnBoard.merge(key + " on " + p.getName(), 1, Integer::sum);
            }
        }
        for (Option o : options) if (o.abilityKey != null) obs.knownNames.add(o.abilityKey.substring(0, o.abilityKey.lastIndexOf('#')));
        JsonObject msg = new JsonObject();
        msg.addProperty("type", "decision");
        msg.addProperty("kind", kind);
        msg.addProperty("prompt", prompt);
        msg.add("obs", obs.json);
        JsonArray opts = new JsonArray();
        for (Option o : options) {
            JsonObject j = new JsonObject();
            // labels are for logs only: strip XMage's GUI markup and short id tags
            j.addProperty("label", o.label.replaceAll("<[^>]+>", "").replaceAll(" ?\\[[0-9a-f]{3}\\]", ""));
            j.add("source", ref(obs, o.source, kind + "/source", game));
            j.add("target", ref(obs, o.target, kind + "/target", game));
            j.addProperty("action", o.action == null ? kind : o.action);
            if (o.abilityKey != null) j.addProperty("ability_key", o.abilityKey);
            if (o.choiceKey != null) j.addProperty("choice_key", o.choiceKey);
            opts.add(j);
        }
        msg.add("options", opts);
        String text = link.gson.toJson(msg);
        List<String> leaks = new ArrayList<>(obs.violations);
        leaks.addAll(Observer.scanText(text, game, obs));
        for (String l : leaks) link.leaks.merge(l, 1, Integer::sum);
        msg.add("leaks", link.gson.toJsonTree(leaks));
        text = link.gson.toJson(msg);
        link.observeNanos += System.nanoTime() - t0;
        link.bytes += text.length();

        long t1 = System.nanoTime();
        link.out.println(text);
        String line;
        try {
            line = link.in.readLine();
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
        link.roundTripNanos += System.nanoTime() - t1;
        link.roundTrips++;
        if (line == null) throw new IllegalStateException("python closed the pipe");
        int choice = link.gson.fromJson(line, JsonObject.class).get("choice").getAsInt();
        if (choice < 0 || choice >= options.size()) throw new IllegalStateException("bad choice " + choice + " for " + kind);
        options.get(choice).onPick.run();
        return choice;
    }

    private static String label(Game game, UUID id) {
        // labels are for humans reading logs; the model uses the entry indices. Never read names of hidden objects here.
        MageObject o = game.getObject(id);
        if (o instanceof Permanent && ((Permanent) o).isFaceDown(game)) return "face-down permanent";
        return o == null ? "?" : o.getName();
    }

    // ---------- priority ----------

    @Override
    public boolean priority(Game game) {
        game.getState().setPriorityPlayerId(playerId);
        game.firePriorityEvent(playerId);
        String key = game.getTurnNum() + "/" + game.getTurnStepType() + "/" + game.getStack().size();
        if (!key.equals(windowKey)) {
            windowKey = key;
            failedThisWindow = new HashSet<>();
        }
        List<Option> opts = new ArrayList<>();
        boolean[] passed = {false};
        ActivatedAbility[] chosen = {null};
        opts.add(new Option("PASS", null, null, () -> passed[0] = true).as("PASS"));
        for (ActivatedAbility a : getPlayable(game, true)) {
            if (a.isManaAbility() || failedThisWindow.contains(a.getId())) continue;
            if (resources(game).equals(refusedAt.get(a.getId()))) continue;
            Option o = new Option(a.getAbilityType() + " | " + label(game, a.getSourceId()) + " | " + a, a.getSourceId(), null, () -> chosen[0] = a);
            switch (a.getAbilityType()) {
                case PLAY_LAND: o.as("PLAY_LAND"); break;
                case SPELL: o.as("CAST"); break;
                case SPECIAL_ACTION: o.as("SPECIAL"); break;
                default:
                    o.as("ACTIVATE");
                    o.key(AbilityKeys.key(game, a));
                    if (o.abilityKey == null) link.unmappedAbilities.merge(label(game, a.getSourceId()) + ": " + a, 1, Integer::sum);
            }
            opts.add(o);
        }
        int i = pick("PRIORITY", "priority", game, opts, null);
        if (passed[0]) {
            pass(game);
            return false;
        }
        String before = resources(game);
        int askedBefore = link.asked.values().stream().mapToInt(Integer::intValue).sum();
        if (!activateAbility(chosen[0], game)) {
            boolean askedSomething = link.asked.values().stream().mapToInt(Integer::intValue).sum() > askedBefore;
            // refused after this seat made choices (a target, a cost option): another choice might work, so only
            // drop it for this window. Refused with no choices: it can't work until something changes.
            if (askedSomething) failedThisWindow.add(chosen[0].getId());
            else refusedAt.put(chosen[0].getId(), before);
            link.rejected.add("turn " + game.getTurnNum() + " " + opts.get(i).label + (askedSomething ? " (after choices)" : ""));
        }
        return true;
    }

    /** What paying a cost can depend on: every permanent and whether it's tapped, this seat's hand, life and graveyard, the stack. */
    private String resources(Game game) {
        StringBuilder sb = new StringBuilder();
        for (Permanent p : game.getBattlefield().getAllActivePermanents()) sb.append(p.getId()).append(p.isTapped() ? 'T' : 'U');
        sb.append('|').append(getHand()).append('|').append(getLife()).append('|').append(getGraveyard().size());
        sb.append('|').append(game.getStack().size()).append('|').append(getManaPool().getMana());
        return sb.toString();
    }

    // ---------- targets ----------

    private boolean chooseTargets(String kind, Target target, Ability source, Game game, boolean isTargeting, Cards fromCards) {
        // whose cards and permissions the choice is about: this seat, unless the target names another player, as in
        // XMage's HumanPlayer. Not the source's controller: an opponent's ability can make this seat pay a cost
        // (Osseous Sticktwister's "discard a card"), and that used to list the opponent's hand.
        UUID controller = target.getAffectedAbilityControllerId(playerId);
        UUID sourceId = source == null ? null : source.getSourceId();
        while (target.getTargets().size() < target.getMaxNumberOfTargets()) {
            Set<UUID> possible = new LinkedHashSet<>(fromCards == null
                    ? target.possibleTargets(controller, source, game)
                    : target.possibleTargets(controller, source, game, fromCards));
            possible.removeAll(target.getTargets());
            if (possible.isEmpty()) break;
            boolean canStop = target.getTargets().size() >= target.getMinNumberOfTargets();
            List<Option> opts = new ArrayList<>();
            boolean[] done = {false};
            if (canStop) opts.add(new Option("DONE", sourceId, null, () -> done[0] = true).as("DONE"));
            for (UUID id : possible) {
                opts.add(new Option(label(game, id), sourceId, id, () -> {
                    if (isTargeting) target.addTarget(id, source, game);
                    else target.add(id, game);
                }).as(kind));
            }
            pick(kind, target.getMessage(game), game, opts, fromCards);
            if (done[0]) break;
        }
        return target.isChosen(game);
    }

    @Override
    public boolean chooseTarget(Outcome outcome, Target target, Ability source, Game game) {
        return chooseTargets("TARGET", target, source, game, true, null);
    }

    @Override
    public boolean choose(Outcome outcome, Target target, Ability source, Game game, Map<String, Serializable> options) {
        return chooseTargets("CHOOSE", target, source, game, false, null);
    }

    @Override
    public boolean choose(Outcome outcome, Cards cards, TargetCard target, Ability source, Game game) {
        return chooseTargets("CHOOSE_CARDS", target, source, game, false, cards);
    }

    @Override
    public boolean chooseTarget(Outcome outcome, Cards cards, TargetCard target, Ability source, Game game) {
        return chooseTargets("TARGET_CARDS", target, source, game, true, cards);
    }

    // ---------- small choices ----------

    @Override
    public boolean chooseUse(Outcome outcome, String message, String secondMessage, String trueText, String falseText, Ability source, Game game) {
        boolean[] yes = {false};
        UUID sourceId = source == null ? null : source.getSourceId();
        List<Option> opts = List.of(
                new Option("YES " + (trueText == null ? "" : trueText), sourceId, null, () -> yes[0] = true).as("YES"),
                new Option("NO " + (falseText == null ? "" : falseText), sourceId, null, () -> {}).as("NO"));
        pick("USE", message, game, opts, null);
        return yes[0];
    }

    @Override
    public boolean choose(Outcome outcome, Choice choice, Game game) {
        // mana colour choices belong to the autopayer (v1: autotap)
        if (choice.getMessage() != null && choice.getMessage().toLowerCase().contains("mana")) {
            link.fallback.merge("CHOICE (mana)", 1, Integer::sum);
            return super.choose(outcome, choice, game);
        }
        List<Option> opts = new ArrayList<>();
        if (choice.isKeyChoice() && altCostPrompt(choice)) {
            // XMage keys these by list position; the texts name the card ("(source: ... object_id='...')")
            Card card = null;
            for (String v : choice.getKeyChoices().values()) {
                java.util.regex.Matcher m = OBJECT_ID.matcher(v);
                if (card == null && m.find()) card = game.getCard(UUID.fromString(m.group(1)));
            }
            if (card instanceof mage.cards.SubCard) card = ((mage.cards.SubCard<?>) card).getParentCard();
            List<Ability> altCosts = new ArrayList<>();
            if (card != null) for (Ability a : card.getAbilities()) if (a instanceof mage.abilities.costs.AlternativeSourceCosts) altCosts.add(a);
            UUID cardId = card == null ? null : card.getId();
            for (Map.Entry<String, String> e : choice.getKeyChoices().entrySet()) {
                String text = e.getValue(), key = null;
                if (text.startsWith("Cast with no alternative cost")) key = AbilityKeys.NO_ALT_COST;
                else if (altCosts.size() == 1) key = AbilityKeys.altCostKey(altCosts.get(0));
                else for (Ability a : altCosts) {
                    if (text.contains(a.getClass().getSimpleName().replace("Ability", ""))) key = AbilityKeys.altCostKey(a);
                }
                if (key == null) link.unmappedChoices.merge("alt cost: " + text.replaceAll("<[^>]+>", ""), 1, Integer::sum);
                opts.add(new Option(text, cardId, null, () -> choice.setChoiceByKey(e.getKey())).as("CHOICE").choice(key));
            }
        } else if (choice.isKeyChoice()) {
            for (Map.Entry<String, String> e : choice.getKeyChoices().entrySet())
                opts.add(new Option(e.getValue(), null, null, () -> choice.setChoiceByKey(e.getKey())).as("CHOICE").choice("choice:" + e.getValue()));
        } else {
            for (String c : choice.getChoices()) opts.add(new Option(c, null, null, () -> choice.setChoice(c)).as("CHOICE").choice("choice:" + c));
        }
        if (opts.isEmpty()) return super.choose(outcome, choice, game);
        pick("CHOICE", choice.getMessage(), game, opts, null);
        return choice.isChosen();
    }

    private static boolean altCostPrompt(Choice choice) {
        String m = choice.getMessage();
        return m != null && m.toLowerCase().contains("alternative cost");
    }

    private static final java.util.regex.Pattern OBJECT_ID = java.util.regex.Pattern.compile("object_id='([0-9a-f-]{36})'");

    @Override
    public Mode chooseMode(Modes modes, Ability source, Game game) {
        if (modes.getMode() != null && modes.getMaxModes(game, source) == modes.getSelectedModes().size()) {
            return modes.getMode();
        }
        Mode[] picked = {null};
        List<Option> opts = new ArrayList<>();
        for (Mode m : modes.getAvailableModes(source, game)) {
            if ((modes.isMayChooseSameModeMoreThanOnce() || !modes.getSelectedModes().contains(m.getId()))
                    && m.getTargets().canChoose(source.getControllerId(), source, game)) {
                String key = AbilityKeys.modeKey(game, source, m);
                if (key == null) link.unmappedChoices.merge("mode: " + label(game, source.getSourceId()) + ": " + m.getEffects().getText(m), 1, Integer::sum);
                opts.add(new Option(m.getEffects().getText(m), source.getSourceId(), null, () -> picked[0] = m).as("MODE").choice(key));
            }
        }
        if (opts.isEmpty()) return null;
        pick("MODE", "choose a mode", game, opts, null);
        return picked[0];
    }

    @Override
    public TriggeredAbility chooseTriggeredAbility(List<TriggeredAbility> abilities, Game game) {
        if (abilities.isEmpty()) return null;
        TriggeredAbility[] picked = {null};
        List<Option> opts = new ArrayList<>();
        for (TriggeredAbility t : abilities) opts.add(new Option(t.toString(), t.getSourceId(), null, () -> picked[0] = t).as("TRIGGER_ORDER").key(AbilityKeys.key(game, t)));
        pick("TRIGGER_ORDER", "which trigger goes on the stack first", game, opts, null);
        return picked[0];
    }

    // ---------- combat ----------

    @Override
    public void selectAttackers(Game game, UUID attackingPlayerId) {
        UUID defender = game.getOpponents(playerId).iterator().next();
        while (true) {
            boolean[] done = {false};
            List<Option> opts = new ArrayList<>();
            opts.add(new Option("DONE", null, null, () -> done[0] = true).as("DONE"));
            for (Permanent p : getAvailableAttackers(defender, game)) {
                if (p.isAttacking()) continue;
                opts.add(new Option(label(game, p.getId()) + " attacks", p.getId(), defender,
                        () -> declareAttacker(p.getId(), defender, game, false)).as("ATTACK"));
            }
            if (opts.size() == 1) return;
            pick("ATTACK", "declare attackers one at a time", game, opts, null);
            if (done[0]) return;
        }
    }

    @Override
    public void selectBlockers(Ability source, Game game, UUID defendingPlayerId) {
        while (true) {
            boolean[] done = {false};
            List<Option> opts = new ArrayList<>();
            opts.add(new Option("DONE", null, null, () -> done[0] = true).as("DONE"));
            for (Permanent blocker : getAvailableBlockers(game)) {
                if (blocker.getBlocking() > 0) continue;
                for (CombatGroup group : game.getCombat().getGroups()) {
                    if (group.getAttackers().isEmpty() || !group.canBlock(blocker, game)) continue;
                    UUID attacker = group.getAttackers().get(0);
                    opts.add(new Option(label(game, blocker.getId()) + " blocks " + label(game, attacker), blocker.getId(), attacker,
                            () -> declareBlocker(defendingPlayerId, blocker.getId(), attacker, game)).as("BLOCK"));
                }
            }
            if (opts.size() == 1) return;
            pick("BLOCK", "declare blockers one at a time", game, opts, null);
            if (done[0]) return;
        }
    }

    // ---------- defaults not sent yet: count them ----------

    private void fallback(String kind) {
        link.fallback.merge(kind, 1, Integer::sum);
    }

    @Override
    public boolean chooseMulligan(Game game) {
        // sent as a yes/no decision (USE) so it fits the existing decision and action vocabularies
        boolean[] mulligan = {false};
        List<Option> opts = List.of(
                new Option("YES mulligan", null, null, () -> mulligan[0] = true).as("YES"),
                new Option("NO keep this hand", null, null, () -> {}).as("NO"));
        pick("USE", "Mulligan? Your hand has " + getHand().size() + " cards", game, opts, null);
        return mulligan[0];
    }

    @Override
    public boolean chooseTargetAmount(Outcome outcome, mage.target.TargetAmount target, Ability source, Game game) { fallback("TARGET_AMOUNT"); return super.chooseTargetAmount(outcome, target, source, game); }

    @Override
    public int announceX(int min, int max, String message, Game game, Ability source, boolean isManaPay) { fallback("ANNOUNCE_X"); return super.announceX(min, max, message, game, source, isManaPay); }

    @Override
    public int getAmount(int min, int max, String message, Ability source, Game game) { fallback("AMOUNT"); return super.getAmount(min, max, message, source, game); }

    @Override
    public int chooseReplacementEffect(Map<String, String> effectsMap, Map<String, MageObject> objectsMap, Game game) { fallback("REPLACEMENT"); return super.chooseReplacementEffect(effectsMap, objectsMap, game); }
}
