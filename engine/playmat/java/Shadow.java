import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import mage.MageObject;
import mage.abilities.Ability;
import mage.abilities.ActivatedAbility;
import mage.abilities.Mode;
import mage.abilities.Modes;
import mage.abilities.TriggeredAbility;
import mage.cards.Cards;
import mage.choices.Choice;
import mage.game.Game;
import mage.game.combat.CombatGroup;
import mage.game.permanent.Permanent;
import mage.players.Player;
import mage.target.Target;

import java.util.*;

/**
 * Records the decisions of a seat whose choices are not made through PySeat (Jeff in the browser, XMage's AI) in
 * PySeat's decision format: before the seat decides, the same options PySeat would offer (same kinds, actions,
 * ability and choice keys, observation built by Observer for that seat, with its leak checks); after it decides,
 * the option its answer matches. Each record says how sure that match is ("mapping"):
 *   exact     the answer is one of the options (a priority action, yes/no, a mode, a single target)
 *   inferred  rebuilt afterwards from what changed (several targets, attackers or blockers in the order XMage
 *             holds them; every line of such a sequence carries the observation from before the first pick)
 *   unmapped  the answer matched no option (choice -1, raw answer kept in "ui")
 * Forced decisions (one option) are not recorded, as in PySeat.
 */
final class Shadow {

    static final class Opt {
        final String label;
        final UUID source, target;
        String action, abilityKey, choiceKey;
        Object ref;  // what the option stands for (ability, target id, mode, ...), to match the answer

        Opt(String label, UUID source, UUID target, String action) {
            this.label = label; this.source = source; this.target = target; this.action = action;
        }
        Opt key(String k) { abilityKey = k; return this; }
        Opt choice(String k) { choiceKey = k; return this; }
        Opt ref(Object r) { ref = r; return this; }
    }

    /** A decision about to be made: its options and the observation from before. */
    static final class Pending {
        final String kind, prompt;
        final List<Opt> opts;
        final JsonObject msg;
        Pending(String kind, String prompt, List<Opt> opts, JsonObject msg) {
            this.kind = kind; this.prompt = prompt; this.opts = opts; this.msg = msg;
        }
    }

    private final Player player;
    private final String source;  // "human_ui" or "xmage_ai"
    final Map<String, Integer> unseenRefs = new TreeMap<>();

    Shadow(Player player, String source) {
        this.player = player;
        this.source = source;
    }

    static String label(Game game, UUID id) {
        MageObject o = game.getObject(id);
        if (o instanceof Permanent && ((Permanent) o).isFaceDown(game)) return "face-down permanent";
        return o == null ? "?" : o.getName();
    }

    // ---------- building a decision (PySeat.pick, without sending it) ----------

    Pending build(String kind, String prompt, Game game, List<Opt> opts, Collection<UUID> offered) {
        Observer.Obs obs = Observer.build(game, player.getId(), offered);
        for (Opt o : opts) if (o.abilityKey != null && o.abilityKey.contains("#")) obs.knownNames.add(o.abilityKey.substring(0, o.abilityKey.lastIndexOf('#')));
        JsonObject msg = new JsonObject();
        msg.addProperty("type", "decision");
        msg.addProperty("kind", kind);
        msg.addProperty("prompt", prompt == null ? "" : prompt);
        msg.add("obs", obs.json);
        JsonArray arr = new JsonArray();
        for (Opt o : opts) {
            JsonObject j = new JsonObject();
            j.addProperty("label", o.label.replaceAll("<[^>]+>", "").replaceAll(" ?\\[[0-9a-f]{3}\\]", ""));
            j.add("source", ref(obs, o.source, kind + "/source", game));
            j.add("target", ref(obs, o.target, kind + "/target", game));
            j.addProperty("action", o.action == null ? kind : o.action);
            if (o.abilityKey != null) j.addProperty("ability_key", o.abilityKey);
            if (o.choiceKey != null) j.addProperty("choice_key", o.choiceKey);
            arr.add(j);
        }
        msg.add("options", arr);
        List<String> leaks = new ArrayList<>(obs.violations);
        leaks.addAll(Observer.scanText(GameRecorder.GSON.toJson(msg), game, obs));
        msg.add("leaks", GameRecorder.GSON.toJsonTree(leaks));
        return new Pending(kind, prompt, opts, msg);
    }

    /** PySeat.ref: an option's object as an observation entry or player, "unseen" if this seat can't see it. */
    private JsonObject ref(Observer.Obs obs, UUID id, String kind, Game game) {
        JsonObject r = new JsonObject();
        if (id == null) return r;
        String p = obs.playerRef(id);
        if (p != null) {
            r.addProperty("player", p);
            return r;
        }
        MageObject obj = game.getObject(id);
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
            unseenRefs.merge(kind + ":" + (o == null ? "?" : o.getClass().getSimpleName()), 1, Integer::sum);
            r.addProperty("unseen", true);
        }
        return r;
    }

    /** Writes the decision with the picked option index (-1: unmapped). Skips forced decisions. */
    void record(Game game, Pending p, int choice, String mapping, JsonObject ui) {
        if (p == null || p.opts.size() < 2) return;
        GameRecorder r = GameRecorder.find(game);
        if (r == null) return;
        JsonObject extra = new JsonObject();
        extra.addProperty("source", source);
        extra.addProperty("mapping", mapping);
        if ("xmage_ai".equals(source)) {
            // XMage's AI searches copies of the full game: its choices may use hidden information
            extra.addProperty("reconstructed", true);
            extra.addProperty("clairvoyant", true);
        }
        if (ui != null) extra.add("ui", ui);
        r.writeDecision(player.getId(), r.playerName(r.seat(player.getId())), p.msg, choice, extra);
    }

    // ---------- options, as PySeat builds them ----------

    /** PASS plus every playable non-mana ability (PySeat.priority; without its per-window refusal memory). */
    List<Opt> priorityOptions(Game game) {
        List<Opt> opts = new ArrayList<>();
        opts.add(new Opt("PASS", null, null, "PASS"));
        Set<String> seen = new HashSet<>();
        List<ActivatedAbility> list = new ArrayList<>(player.getPlayable(game, true));
        for (ActivatedAbility a : list) {
            if (a.isManaAbility()) continue;
            if (!seen.add(a.getSourceId() + "|" + a.getId())) continue;
            Opt o = new Opt(a.getAbilityType() + " | " + label(game, a.getSourceId()) + " | " + a, a.getSourceId(), null, null).ref(a);
            switch (a.getAbilityType()) {
                case PLAY_LAND: o.action = "PLAY_LAND"; break;
                case SPELL: o.action = "CAST"; break;
                case SPECIAL_ACTION: o.action = "SPECIAL"; break;
                default: o.action = "ACTIVATE"; o.key(AbilityKeys.key(game, a));
            }
            opts.add(o);
        }
        return opts;
    }

    /** Index of the activated ability among priority options, or -1. */
    static int matchAbility(List<Opt> opts, ActivatedAbility a, Game game) {
        if (a == null) return 0;  // passed
        for (int i = 1; i < opts.size(); i++) {
            ActivatedAbility o = (ActivatedAbility) opts.get(i).ref;
            if (o.getId().equals(a.getId()) && Objects.equals(o.getSourceId(), a.getSourceId())) return i;
        }
        // same source and rules text (XMage copies abilities when it lists them)
        for (int i = 1; i < opts.size(); i++) {
            ActivatedAbility o = (ActivatedAbility) opts.get(i).ref;
            if (Objects.equals(o.getSourceId(), a.getSourceId()) && o.getRule().equals(a.getRule())) return i;
        }
        return -1;
    }

    List<Opt> targetOptions(String kind, Target target, Ability source, Game game, Cards fromCards, boolean withDone) {
        UUID controller = target.getAffectedAbilityControllerId(player.getId());
        UUID sourceId = source == null ? null : source.getSourceId();
        Set<UUID> possible = new LinkedHashSet<>(fromCards == null
                ? target.possibleTargets(controller, source, game)
                : target.possibleTargets(controller, source, game, fromCards));
        possible.removeAll(target.getTargets());
        List<Opt> opts = new ArrayList<>();
        if (withDone) opts.add(new Opt("DONE", sourceId, null, "DONE"));
        for (UUID id : possible) opts.add(new Opt(label(game, id), sourceId, id, kind).ref(id));
        return opts;
    }

    List<Opt> modeOptions(Modes modes, Ability source, Game game) {
        List<Opt> opts = new ArrayList<>();
        for (Mode m : modes.getAvailableModes(source, game)) {
            if ((modes.isMayChooseSameModeMoreThanOnce() || !modes.getSelectedModes().contains(m.getId()))
                    && m.getTargets().canChoose(source.getControllerId(), source, game)) {
                opts.add(new Opt(m.getEffects().getText(m), source.getSourceId(), null, "MODE").choice(AbilityKeys.modeKey(game, source, m)).ref(m));
            }
        }
        return opts;
    }

    List<Opt> choiceOptions(Choice choice) {
        List<Opt> opts = new ArrayList<>();
        if (choice.isKeyChoice()) {
            for (Map.Entry<String, String> e : choice.getKeyChoices().entrySet())
                opts.add(new Opt(e.getValue(), null, null, "CHOICE").choice("choice:" + e.getValue()).ref(e.getKey()));
        } else {
            for (String c : choice.getChoices()) opts.add(new Opt(c, null, null, "CHOICE").choice("choice:" + c).ref(c));
        }
        return opts;
    }

    List<Opt> triggerOptions(List<TriggeredAbility> abilities, Game game) {
        List<Opt> opts = new ArrayList<>();
        for (TriggeredAbility t : abilities) opts.add(new Opt(t.toString(), t.getSourceId(), null, "TRIGGER_ORDER").key(AbilityKeys.key(game, t)).ref(t));
        return opts;
    }

    static List<Opt> yesNo(String trueText, String falseText, UUID sourceId) {
        List<Opt> opts = new ArrayList<>();
        opts.add(new Opt("YES " + (trueText == null ? "" : trueText), sourceId, null, "YES"));
        opts.add(new Opt("NO " + (falseText == null ? "" : falseText), sourceId, null, "NO"));
        return opts;
    }

    /** Attack options as PySeat offers them: DONE, then each untapped creature that can attack and isn't. */
    List<Opt> attackOptions(Game game, UUID defender, Set<UUID> already) {
        List<Opt> opts = new ArrayList<>();
        opts.add(new Opt("DONE", null, null, "DONE"));
        for (Permanent p : player.getAvailableAttackers(defender, game)) {
            if (already.contains(p.getId())) continue;
            opts.add(new Opt(label(game, p.getId()) + " attacks", p.getId(), defender, "ATTACK").ref(p.getId()));
        }
        return opts;
    }

    List<Opt> blockOptions(Game game, Set<UUID> already) {
        List<Opt> opts = new ArrayList<>();
        opts.add(new Opt("DONE", null, null, "DONE"));
        for (Permanent blocker : player.getAvailableBlockers(game)) {
            if (already.contains(blocker.getId())) continue;
            for (CombatGroup group : game.getCombat().getGroups()) {
                if (group.getAttackers().isEmpty() || !group.canBlock(blocker, game)) continue;
                UUID attacker = group.getAttackers().get(0);
                opts.add(new Opt(label(game, blocker.getId()) + " blocks " + label(game, attacker), blocker.getId(), attacker, "BLOCK")
                        .ref(blocker.getId() + ">" + attacker));
            }
        }
        return opts;
    }

    static int indexOfRef(List<Opt> opts, Object ref) {
        for (int i = 0; i < opts.size(); i++) if (Objects.equals(opts.get(i).ref, ref)) return i;
        return -1;
    }

    // ---------- recording a decision from what changed ----------

    /**
     * Targets added by one call, recorded as PySeat's one-at-a-time sequence: each pick, then DONE if the seat
     * stopped before the maximum. The first line's options are the real ones; later lines drop the picked ones.
     */
    void recordTargets(Game game, String kind, Target target, Ability source, Cards fromCards, int sizeBefore,
                       Pending first, boolean exactSingle) {
        if (first == null) return;
        List<UUID> added = new ArrayList<>(target.getTargets());
        added = added.size() > sizeBefore ? added.subList(sizeBefore, added.size()) : Collections.emptyList();
        List<Opt> opts = new ArrayList<>(first.opts);
        boolean many = added.size() > 1 || target.getMaxNumberOfTargets() > 1;
        String mapping = many || !exactSingle ? "inferred" : "exact";
        int chosen = 0;
        for (UUID id : added) {
            int i = indexOfRef(opts, id);
            Pending p = chosen == 0 ? first : rebuilt(first, opts);
            JsonObject ui = null;
            if (i < 0) { ui = new JsonObject(); ui.addProperty("target", label(game, id)); }
            record(game, p, i, i < 0 ? "unmapped" : mapping, ui);
            if (i >= 0) opts.remove(i);
            chosen++;
            boolean canStop = sizeBefore + chosen >= target.getMinNumberOfTargets();
            if (canStop && (opts.isEmpty() || !"DONE".equals(opts.get(0).action))) opts.add(0, new Opt("DONE", source == null ? null : source.getSourceId(), null, "DONE"));
        }
        int total = target.getTargets().size();
        if (total < target.getMaxNumberOfTargets() && opts.size() > 1 && "DONE".equals(opts.get(0).action)) {
            record(game, chosen == 0 ? first : rebuilt(first, opts), 0, mapping, null);
        }
    }

    /** A later step of a sequence: same observation, the remaining options. */
    private Pending rebuilt(Pending first, List<Opt> opts) {
        JsonObject msg = first.msg.deepCopy();
        JsonArray all = first.msg.getAsJsonArray("options"), keep = new JsonArray();
        for (Opt o : opts) {
            int i = first.opts.indexOf(o);
            if (i >= 0) keep.add(all.get(i));
            else {  // a DONE added after the first pick
                JsonObject j = new JsonObject();
                j.addProperty("label", "DONE");
                j.add("source", new JsonObject());
                j.add("target", new JsonObject());
                j.addProperty("action", "DONE");
                keep.add(j);
            }
        }
        msg.add("options", keep);
        return new Pending(first.kind, first.prompt, new ArrayList<>(opts), msg);
    }

    /** Attackers or blockers declared in one call, as PySeat's sequence of picks ending with DONE. */
    void recordSequence(Game game, Pending first, List<Object> picked) {
        if (first == null) return;
        List<Opt> opts = new ArrayList<>(first.opts);
        int n = 0;
        for (Object ref : picked) {
            int i = indexOfRef(opts, ref);
            Pending p = n == 0 ? first : rebuilt(first, opts);
            JsonObject ui = null;
            if (i < 0) { ui = new JsonObject(); ui.addProperty("declared", String.valueOf(ref)); }
            record(game, p, i, i < 0 ? "unmapped" : "inferred", ui);
            if (i >= 0) {
                // a creature attacks or blocks once: drop all its options
                String who = String.valueOf(ref).split(">")[0];
                opts.removeIf(o -> o.ref != null && String.valueOf(o.ref).split(">")[0].equals(who));
            }
            n++;
        }
        if (opts.size() > 1) record(game, n == 0 ? first : rebuilt(first, opts), 0, n == 0 ? "exact" : "inferred", null);
    }

    /** "blocker>first attacker of its group" for each of this player's blockers, the option refs blockOptions uses. */
    static List<Object> declaredBlocks(Game game, UUID me) {
        List<Object> picked = new ArrayList<>();
        for (CombatGroup g : game.getCombat().getGroups()) {
            if (g.getAttackers().isEmpty()) continue;
            for (UUID b : g.getBlockers()) {
                mage.game.permanent.Permanent perm = game.getPermanent(b);
                if (perm != null && me.equals(perm.getControllerId())) picked.add(b + ">" + g.getAttackers().get(0));
            }
        }
        return picked;
    }
}
