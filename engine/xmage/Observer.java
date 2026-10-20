import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import mage.cards.Card;
import mage.game.Game;
import mage.game.permanent.Permanent;
import mage.players.Player;
import mage.view.*;

import java.util.*;

/**
 * Builds one seat's observation from XMage's own per-seat GameView (the view a human client gets),
 * then checks it against the full game state for hidden-information leaks.
 *
 * Entry layout: [global (0) | cards | abilities on the stack]. Entries carry no engine UUIDs;
 * the UUID -> entry index map stays on the Java side so options can point at entries.
 */
public final class Observer {

    public static final class Obs {
        public final JsonObject json = new JsonObject();
        public final Map<UUID, Integer> index = new HashMap<>();
        public final Map<UUID, String> names = new HashMap<>();
        public final List<String> violations = new ArrayList<>();
        // full card names known through a visible object, e.g. a Room on the battlefield shown by its door name
        public final Set<String> knownNames = new HashSet<>();
        final JsonArray entries = new JsonArray();
        final Set<UUID> whitelist = new HashSet<>(); // revealed / looked at / offered by the current prompt
        UUID me, opp;

        int add(UUID id, JsonObject e) {
            Integer existing = index.get(id);
            if (existing != null) return existing;
            int i = entries.size();
            e.addProperty("i", i);
            entries.add(e);
            if (id != null) index.put(id, i);
            return i;
        }

        public String playerRef(UUID id) {
            if (id == null) return null;
            if (id.equals(me)) return "me";
            if (id.equals(opp)) return "opp";
            return null;
        }
    }

    /** My own spell or card that is being cast/activated but isn't in the view yet: it's mine, so I may see it. */
    public static Integer addCasting(Obs obs, Game game, UUID id) {
        mage.MageObject o = game.getObject(id);
        if (o == null || !obs.me.equals(game.getControllerId(id) == null ? game.getOwnerId(id) : game.getControllerId(id))) return null;
        JsonObject e = new JsonObject();
        e.addProperty("kind", "card");
        e.addProperty("zone", "CASTING");
        e.addProperty("name", o.getName());
        e.addProperty("mine", true);
        e.addProperty("being_cast", true);
        obs.names.put(id, o.getName());
        return obs.add(id, e);
    }

    public static Obs build(Game game, UUID me, Collection<UUID> offered) {
        Obs obs = new Obs();
        obs.me = me;
        obs.opp = game.getOpponents(me).iterator().next();
        GameView view = new GameView(game.getState(), game, me, null);

        // ---- global entry (index 0) ----
        JsonObject g = new JsonObject();
        g.addProperty("kind", "global");
        g.addProperty("turn", view.getTurn());
        g.addProperty("step", String.valueOf(view.getStep()));
        g.addProperty("my_turn", me.equals(view.getActivePlayerId()));
        for (PlayerView p : view.getPlayers()) {
            String who = me.equals(p.getPlayerId()) ? "my" : "opp";
            g.addProperty(who + "_life", p.getLife());
            g.addProperty(who + "_hand", p.getHandCount());
            g.addProperty(who + "_library", p.getLibraryCount());
            g.addProperty(who + "_graveyard", p.getGraveyard().size());
        }
        g.addProperty("stack_size", view.getStack().size());
        obs.add(null, g);

        // combat status, read from the view
        Set<UUID> attacking = new HashSet<>(), blocking = new HashSet<>();
        for (CombatGroupView cg : view.getCombat()) {
            attacking.addAll(cg.getAttackers().keySet());
            blocking.addAll(cg.getBlockers().keySet());
        }

        // ---- cards ----
        for (CardView c : view.getMyHand().values()) addCard(game, obs, c, "HAND", true, attacking, blocking);
        for (PlayerView p : view.getPlayers()) {
            // the view files an Aura under the enchanted permanent's player; "mine" means I control it
            for (PermanentView c : p.getBattlefield().values()) {
                UUID controller = game.getControllerId(c.getId());
                boolean mine = controller == null ? me.equals(p.getPlayerId()) : me.equals(controller);
                addCard(game, obs, c, "BATTLEFIELD", mine, attacking, blocking);
            }
        }
        for (PlayerView p : view.getPlayers()) {
            boolean mine = me.equals(p.getPlayerId());
            for (CardView c : p.getGraveyard().values()) addCard(game, obs, c, "GRAVEYARD", mine, attacking, blocking);
        }
        for (ExileView ex : view.getExile()) {
            for (CardView c : ex.values()) addCard(game, obs, c, "EXILE", me.equals(game.getOwnerId(c.getId())), attacking, blocking);
        }
        List<StackAbilityView> stackAbilities = new ArrayList<>();
        for (CardView c : view.getStack().values()) {
            if (c instanceof StackAbilityView) stackAbilities.add((StackAbilityView) c);
            else addCard(game, obs, c, "STACK", me.equals(game.getControllerId(c.getId())), attacking, blocking);
        }
        for (RevealedView r : view.getRevealed()) {
            for (CardView c : r.getCards().values()) {
                obs.whitelist.add(c.getId());
                addCard(game, obs, c, "REVEALED", me.equals(game.getOwnerId(c.getId())), attacking, blocking);
            }
        }
        for (LookedAtView l : view.getLookedAt()) obs.whitelist.addAll(l.getCards().keySet());
        // cards the current prompt shows me (e.g. manifest dread's two cards); names come from the engine
        if (offered != null) {
            for (UUID id : offered) {
                if (obs.index.containsKey(id) || game.getPlayer(id) != null) continue;
                Card card = game.getCard(id);
                obs.whitelist.add(id);
                JsonObject e = new JsonObject();
                e.addProperty("kind", "card");
                e.addProperty("zone", "OFFERED");
                e.addProperty("name", card == null ? "" : card.getName());
                e.addProperty("mine", card != null && me.equals(card.getOwnerId()));
                obs.names.put(id, card == null ? "?" : card.getName());
                obs.add(id, e);
            }
        }

        // ---- abilities on the stack ----
        for (StackAbilityView a : stackAbilities) {
            JsonObject e = new JsonObject();
            e.addProperty("kind", "ability");
            e.addProperty("zone", "STACK");
            e.addProperty("source_name", a.getName());
            e.addProperty("ability_type", String.valueOf(a.getAbilityType()));
            e.addProperty("mine", me.equals(game.getControllerId(a.getId())));
            e.addProperty("text", String.join(" ", a.getRules()));
            mage.game.stack.StackObject so = game.getStack().getStackObject(a.getId());
            String key = so instanceof mage.game.stack.StackAbility ? AbilityKeys.key(game, ((mage.game.stack.StackAbility) so).getStackAbility()) : null;
            if (key != null) {
                e.addProperty("ability_key", key);
                obs.knownNames.add(key.substring(0, key.lastIndexOf('#')));
            }
            obs.names.put(a.getId(), a.getName() + " (ability)");
            obs.add(a.getId(), e);
        }

        // negative test only: deliberately leak one opponent hand card and one face-down name to prove the checks fire
        if (Boolean.getBoolean("spike.leaktest")) {
            for (UUID id : game.getPlayer(obs.opp).getHand()) {
                JsonObject e = new JsonObject();
                e.addProperty("kind", "card");
                e.addProperty("zone", "HAND");
                e.addProperty("name", game.getCard(id).getName());
                e.addProperty("mine", false);
                obs.add(id, e);
                break;
            }
            for (Permanent p : game.getBattlefield().getAllActivePermanents(obs.opp)) {
                if (p.isFaceDown(game) && obs.index.containsKey(p.getId())) {
                    obs.entries.get(obs.index.get(p.getId())).getAsJsonObject().addProperty("name", "Manifest: " + game.getCard(p.getId()).getName());
                }
            }
        }
        obs.json.add("entries", obs.entries);

        // ---- edges: [type, from entry, to entry], all read from the view ----
        JsonArray edges = new JsonArray();
        int[] droppedPlayerTargets = {0};
        java.util.function.BiConsumer<String, UUID[]> edge = (type, ft) -> {
            Integer f = obs.index.get(ft[0]), t = obs.index.get(ft[1]);
            if (f == null || t == null) return;
            JsonArray ed = new JsonArray();
            ed.add(type); ed.add(f); ed.add(t);
            edges.add(ed);
        };
        for (CombatGroupView cg : view.getCombat()) {
            for (UUID b : cg.getBlockers().keySet()) for (UUID a : cg.getAttackers().keySet()) {
                edge.accept("blocks", new UUID[]{b, a});
                edge.accept("blocked_by", new UUID[]{a, b});
            }
        }
        for (PlayerView p : view.getPlayers()) {
            for (PermanentView pv : p.getBattlefield().values()) {
                if (pv.isAttachedTo() && pv.getAttachedTo() != null) {
                    edge.accept("attached_to", new UUID[]{pv.getId(), pv.getAttachedTo()});
                    edge.accept("has_attached", new UUID[]{pv.getAttachedTo(), pv.getId()});
                }
            }
        }
        // stack: view order is top of stack first (inferred from XMage's stack iteration), so earlier resolves first
        List<UUID> stackOrder = new ArrayList<>(view.getStack().keySet());
        for (int x = 0; x < stackOrder.size(); x++) {
            CardView sv = view.getStack().get(stackOrder.get(x));
            if (sv.getTargets() != null) for (UUID t : sv.getTargets()) {
                if (obs.playerRef(t) != null) { droppedPlayerTargets[0]++; continue; }
                edge.accept("targets", new UUID[]{stackOrder.get(x), t});
                edge.accept("targeted_by", new UUID[]{t, stackOrder.get(x)});
            }
            for (int y = x + 1; y < stackOrder.size(); y++) {
                edge.accept("resolves_before", new UUID[]{stackOrder.get(x), stackOrder.get(y)});
                edge.accept("resolves_after", new UUID[]{stackOrder.get(y), stackOrder.get(x)});
            }
        }
        obs.json.add("edges", edges);
        if (droppedPlayerTargets[0] > 0) obs.json.addProperty("player_targets_not_in_edges", droppedPlayerTargets[0]);
        check(obs, game);
        return obs;
    }

    private static void addCard(Game game, Obs obs, CardView c, String zone, boolean mine, Set<UUID> attacking, Set<UUID> blocking) {
        JsonObject e = new JsonObject();
        e.addProperty("kind", "card");
        e.addProperty("zone", zone);
        e.addProperty("name", c.getName());
        e.addProperty("mine", mine);
        e.addProperty("face_down", c.isFaceDown());
        e.addProperty("token", c.isToken());
        e.addProperty("types", String.valueOf(c.getCardTypes()));
        e.addProperty("mana_value", c.getManaValue());
        e.addProperty("power", c.getPower());
        e.addProperty("toughness", c.getToughness());
        if (c.getCounters() != null && !c.getCounters().isEmpty()) {
            JsonObject counters = new JsonObject();
            for (CounterView cv : c.getCounters()) counters.addProperty(cv.getName(), cv.getCount());
            e.add("counters", counters);
        }
        if (c instanceof PermanentView) {
            PermanentView p = (PermanentView) c;
            e.addProperty("tapped", p.isTapped());
            e.addProperty("damage", p.getDamage());
            e.addProperty("summoning_sick", p.hasSummoningSickness());
            e.addProperty("attacking", attacking.contains(c.getId()));
            e.addProperty("blocking", blocking.contains(c.getId()));
            // keyword abilities it has right now, including granted ones (e.g. first strike from an Aura);
            // nothing for an opponent's face-down permanent
            Permanent perm = game.getPermanent(c.getId());
            if (perm != null && !(c.isFaceDown() && !mine)) {
                JsonArray kw = new JsonArray();
                for (mage.abilities.Ability a : perm.getAbilities(game)) {
                    if (!a.getClass().getName().startsWith("mage.abilities.keyword.")) continue;
                    String rule = a.getRule().replaceAll("<[^>]+>", "").replaceAll(" ?\\(.*\\)", "").trim();
                    if (rule.startsWith("Enchant") || rule.startsWith("Impending")) continue; // printed card text, not a keyword
                    if (!rule.isEmpty() && !kw.contains(new com.google.gson.JsonPrimitive(rule))) kw.add(rule);
                }
                if (kw.size() > 0) e.add("keywords", kw);
            }
        }
        // printed name of a face-up card (public): a Room's displayed name is its unlocked door(s), or empty if none
        if (!c.isFaceDown()) {
            Card card = game.getCard(c.getId());
            if (card instanceof mage.cards.SubCard) card = ((mage.cards.SubCard<?>) card).getParentCard();
            if (card != null) {
                e.addProperty("card_name", card.getName());
                obs.knownNames.add(card.getName());
            }
        }
        obs.names.put(c.getId(), c.getName().isEmpty() ? "face-down card" : c.getName());
        obs.add(c.getId(), e);
    }

    /** Compare the observation with the full game state. Every hit is a hidden-information leak. */
    private static void check(Obs obs, Game game) {
        Player opp = game.getPlayer(obs.opp);
        Set<UUID> oppHand = new HashSet<>(opp.getHand());
        Set<UUID> libraries = new HashSet<>();
        for (Player p : game.getPlayers().values()) libraries.addAll(p.getLibrary().getCardList());
        Set<UUID> hiddenNames = new HashSet<>(); // ids whose real name must not be shown
        Map<UUID, String> realName = new HashMap<>();
        for (Permanent p : game.getBattlefield().getAllActivePermanents(obs.opp)) {
            if (p.isFaceDown(game)) {
                hiddenNames.add(p.getId());
                Card card = game.getCard(p.getId());
                realName.put(p.getId(), card == null ? "" : card.getName());
            }
        }
        for (Map.Entry<UUID, Integer> en : obs.index.entrySet()) {
            UUID id = en.getKey();
            JsonObject e = obs.entries.get(en.getValue()).getAsJsonObject();
            if (oppHand.contains(id) && !obs.whitelist.contains(id))
                obs.violations.add("opponent hand card visible: " + e.get("name"));
            if (libraries.contains(id) && !obs.whitelist.contains(id))
                obs.violations.add("library card visible: " + e.get("name"));
            if (hiddenNames.contains(id)) {
                String shown = e.has("name") ? e.get("name").getAsString() : "";
                String real = realName.get(id);
                // XMage labels face-down cards with a generic name such as "Manifest"; only the real name is a leak
                if (!real.isEmpty() && shown.contains(real)) obs.violations.add("opponent face-down card shows its real name: " + shown);
                if (!real.isEmpty() && obs.json.toString().contains("\"" + real + "\"") && !visibleElsewhere(obs, id, real))
                    obs.violations.add("opponent face-down card's real name appears in the observation: " + real);
            }
        }
    }

    /**
     * Scan a whole outgoing message for names of cards this seat must not know:
     * cards in the opponent's hand or in any library, and the real names of the opponent's face-down permanents.
     * A name only counts as a leak if no visible entry legitimately carries the same name.
     */
    public static List<String> scanText(String text, Game game, Obs obs) {
        Set<String> visible = new HashSet<>(obs.knownNames);
        for (String n : obs.names.values()) {
            visible.add(n);
            // my own face-down cards are shown as "Manifest: <real name>", and I may know that name
            int k = n.indexOf(": ");
            if (k >= 0) visible.add(n.substring(k + 2));
        }
        Map<String, String> secret = new TreeMap<>();
        Player opp = game.getPlayer(obs.opp);
        for (UUID id : opp.getHand()) {
            if (obs.whitelist.contains(id)) continue;
            Card c = game.getCard(id);
            if (c != null) secret.put(c.getName(), "opponent hand");
        }
        for (Player p : game.getPlayers().values()) {
            for (Card c : p.getLibrary().getCards(game)) {
                if (!obs.whitelist.contains(c.getId())) secret.putIfAbsent(c.getName(), "library");
            }
        }
        for (Permanent p : game.getBattlefield().getAllActivePermanents(obs.opp)) {
            if (p.isFaceDown(game)) {
                Card c = game.getCard(p.getId());
                if (c != null) secret.put(c.getName(), "opponent face-down");
            }
        }
        List<String> hits = new ArrayList<>();
        for (Map.Entry<String, String> s : secret.entrySet()) {
            String name = s.getKey();
            if (name.isEmpty() || visible.contains(name) || isBasic(name)) continue;
            if (text.contains(name)) hits.add(s.getValue() + " name in message: " + name);
        }
        return hits;
    }

    private static boolean isBasic(String name) {
        return name.equals("Plains") || name.equals("Island") || name.equals("Swamp") || name.equals("Mountain") || name.equals("Forest");
    }

    private static boolean visibleElsewhere(Obs obs, UUID faceDownId, String name) {
        Integer self = obs.index.get(faceDownId);
        for (int k = 0; k < obs.entries.size(); k++) {
            if (self != null && k == self) continue;
            JsonObject e = obs.entries.get(k).getAsJsonObject();
            for (String f : new String[]{"name", "card_name", "source_name"}) {
                if (e.has(f) && name.equals(e.get(f).getAsString())) return true;
            }
        }
        return false;
    }
}
