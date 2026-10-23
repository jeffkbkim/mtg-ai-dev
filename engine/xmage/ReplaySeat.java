import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import mage.cards.Card;
import mage.constants.PhaseStep;
import mage.game.Game;
import mage.game.permanent.Permanent;
import mage.players.Player;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.util.*;

/**
 * A seat for replaying a recorded (17lands) game: a PySeat whose decisions a Python script answers, plus what
 * replaying needs on top of playing:
 *  - scripted draws: each seat has a queue of card names; before a draw the next queued names are moved to the top of
 *    its library, so the seat draws what the record says (opening hands, one per mulligan, then each turn's draws).
 *    Effects that look at or mill the top of the library still see random cards. Python replaces the queues at any
 *    reply ({"draws": {"A": [...], "B": [...]}}); a seat set to reset its queue on a shuffle starts it over when its
 *    hand is shuffled back during mulligans (the opponent, whose draws stand for "cards it needs");
 *  - sync points: at the active player's first priority in upkeep a {"type":"turn_start"} message, and in the end
 *    step a {"type":"eot"} message carrying the true state of both players (hands, battlefields, life ...) for
 *    Python to compare with the recorded end of turn. These go out even when the seat has nothing to decide;
 *  - rewind: a reply with {"rollback": true} sends the game back to the start of the current turn (XMage's own
 *    turn rollback), so Python can try another reading of the record.
 * Messages carry "seat", "turn" and "step". The true-state dump is for the replay harness only: a policy must
 * never see it.
 */
public class ReplaySeat extends PySeat {

    /** State shared by both seats of one game. */
    static final class Shared {
        boolean rollback;
        int rollbacks;
        String sentKey = "";          // last sync point sent, so a step's repeated priorities send it once
        Map<String, List<String>> queue = new HashMap<>();   // seat name -> names it draws next, in order
        Map<String, Integer> pos = new HashMap<>();
        Set<String> resetOnShuffle = new HashSet<>();
        boolean started;                                   // first priority reached: mulligans are over
        long seed;                                         // XMage's random generator is reseeded from this each turn
        String gameId = "";                                // the record's id, sent with every message
    }

    final transient Shared shared;

    public ReplaySeat(String name, Link link, Shared shared) {
        super(name, link);
        this.shared = shared;
    }

    public ReplaySeat(final ReplaySeat p) {
        super(p);
        this.shared = p.shared;
    }

    @Override
    public ReplaySeat copy() {
        return new ReplaySeat(this);
    }

    @Override
    protected void decorate(JsonObject msg, Game game) {
        msg.addProperty("game", shared.gameId);
        msg.addProperty("seat", getName());
        msg.addProperty("turn", game.getTurnNum());
        msg.addProperty("active", game.isActivePlayer(playerId));
        msg.addProperty("step", game.getTurnStepType() == null ? "" : game.getTurnStepType().name());
        msg.addProperty("rollbacks", shared.rollbacks);
    }

    @Override
    protected void onReply(JsonObject reply, Game game) {
        if (reply.has("draws")) {
            for (Map.Entry<String, JsonElement> e : reply.getAsJsonObject("draws").entrySet()) {
                List<String> names = new ArrayList<>();
                for (JsonElement n : e.getValue().getAsJsonArray()) names.add(n.getAsString());
                shared.queue.put(e.getKey(), names);
                shared.pos.put(e.getKey(), 0);
            }
            for (Player p : game.getPlayers().values()) protectTop(p, game);
        }
        if (reply.has("top")) {  // cards an effect about to look at the top of the library should find (manifest dread)
            for (Map.Entry<String, JsonElement> e : reply.getAsJsonObject("top").entrySet()) {
                List<String> names = new ArrayList<>();
                for (JsonElement n : e.getValue().getAsJsonArray()) names.add(n.getAsString());
                for (Player p : game.getPlayers().values()) if (p.getName().equals(e.getKey())) { protectTop(p, game); stack(p, names, game); }
            }
        }
        if (reply.has("rollback") && reply.get("rollback").getAsBoolean()) shared.rollback = true;
        if (reply.has("fix")) fix(reply.getAsJsonObject("fix"), game);
    }

    /**
     * Resync after a turn no attempt reproduced: make the visible state match the recorded end of turn, moving cards
     * directly between zones (no zone-change events, so nothing triggers). Per seat: "life", "hand" (names) or
     * "hand_count", "battlefield" (non-token, face-up names). Tokens and face-down cards are left as they are.
     * Returns nothing: Python reads the next state as usual. Only for replaying records, never in real play.
     */
    static void fix(JsonObject want, Game game) {
        for (Player p : game.getPlayers().values()) {
            if (!want.has(p.getName())) continue;
            JsonObject w = want.getAsJsonObject(p.getName());
            if (w.has("life")) setLifeQuietly(p, w.get("life").getAsInt());
            if (w.has("battlefield")) {
                Map<String, Integer> need = counts(w.getAsJsonArray("battlefield"));
                Map<String, Integer> tokens = w.has("tokens") ? counts(w.getAsJsonArray("tokens")) : null;
                boolean hidden = w.has("face_down_hidden") && w.get("face_down_hidden").getAsBoolean();
                for (Permanent m : game.getBattlefield().getAllActivePermanents(p.getId())) {
                    if (m instanceof mage.game.permanent.PermanentToken) {
                        String tn = m.getName().endsWith(" Token") ? m.getName().substring(0, m.getName().length() - 6) : m.getName();
                        if (tokens != null) {
                            if (tokens.getOrDefault(tn, 0) > 0) tokens.merge(tn, -1, Integer::sum);
                            else game.getBattlefield().removePermanent(m.getId());
                        }
                        continue;
                    }
                    Card own = game.getCard(m.getId());
                    // the record names this seat's face-down cards "[Face-Down Card]" (the opponent's), or by name
                    String n = m.isFaceDown(game) && hidden ? FACE_DOWN : own != null ? own.getName() : m.getName();
                    if (need.getOrDefault(n, 0) > 0) need.merge(n, -1, Integer::sum);
                    else {  // extra: to its owner's graveyard
                        game.getBattlefield().removePermanent(m.getId());
                        Card c = game.getCard(m.getId());
                        if (c != null) {
                            game.getPlayer(c.getOwnerId()).getGraveyard().add(c);
                            game.getState().setZone(c.getId(), mage.constants.Zone.GRAVEYARD);
                        }
                    }
                }
                // missing tokens: made from the classes Python names (no enter-the-battlefield suppression)
                if (tokens != null && w.has("token_classes")) {
                    JsonObject classes = w.getAsJsonObject("token_classes");
                    for (Map.Entry<String, Integer> e : tokens.entrySet()) {
                        if (e.getValue() <= 0 || !classes.has(e.getKey())) continue;
                        try {
                            mage.game.permanent.token.Token t = (mage.game.permanent.token.Token)
                                    Class.forName(classes.get(e.getKey()).getAsString()).getDeclaredConstructor().newInstance();
                            t.putOntoBattlefield(e.getValue(), game, null, p.getId());
                        } catch (ReflectiveOperationException ex) {
                            // unknown class: the token stays missing and shows up in the next comparison
                        }
                    }
                }
                // missing face-down cards: manifest that many cards from the library
                for (int i = 0; i < need.getOrDefault(FACE_DOWN, 0) && p.getLibrary().hasCards(); i++) {
                    Card top = p.getLibrary().getFromTop(game);
                    // manifesting needs a source ability; a blank one stands in for "the resync"
                    mage.abilities.Ability src = new mage.abilities.common.SimpleStaticAbility(
                            mage.constants.Zone.ALL, new mage.abilities.effects.common.InfoEffect("replay resync"));
                    src.setControllerId(p.getId());
                    src.setSourceId(top.getId());
                    try {
                        mage.abilities.effects.keyword.ManifestEffect.doManifestCards(game, src, p, new HashSet<>(Collections.singletonList(top)));
                    } catch (RuntimeException ex) {
                        break;  // leave it missing: the next comparison reports it
                    }
                }
                need.remove(FACE_DOWN);
                for (Map.Entry<String, Integer> e : need.entrySet()) {
                    for (int i = 0; i < e.getValue(); i++) {
                        Card c = take(p, e.getKey(), game);
                        if (c == null) continue;
                        mage.game.permanent.PermanentCard perm = new mage.game.permanent.PermanentCard(c, p.getId(), game);
                        game.addPermanent(perm, 0);
                        game.getState().setZone(c.getId(), mage.constants.Zone.BATTLEFIELD);
                        perm.removeSummoningSickness();
                        if (perm.hasSubtype(mage.constants.SubType.AURA, game)) attachAura(perm, p, game);
                    }
                }
            }
            if (w.has("doors")) {  // which Room doors are unlocked: the record's casts and unlock triggers
                JsonObject doors = w.getAsJsonObject("doors");
                for (Permanent m : game.getBattlefield().getAllActivePermanents(p.getId())) {
                    Card own = game.getCard(m.getId());
                    if (own == null || !doors.has(own.getName()) || m.isFaceDown(game)) continue;
                    Set<String> sides = new HashSet<>();
                    for (JsonElement e : doors.getAsJsonArray(own.getName())) sides.add(e.getAsString());
                    setField(m, "leftHalfUnlocked", sides.contains("left"));
                    setField(m, "rightHalfUnlocked", sides.contains("right"));
                }
            }
            if (w.has("tap")) {  // the player whose turn just ended: lands it spent mana from, creatures that attacked
                JsonObject tap = w.getAsJsonObject("tap");
                List<Permanent> lands = new ArrayList<>();
                Map<String, Integer> attackers = tap.has("creatures") ? counts(tap.getAsJsonArray("creatures")) : new HashMap<>();
                List<Permanent> mine = new ArrayList<>(game.getBattlefield().getAllActivePermanents(p.getId()));
                mine.sort(Comparator.comparing(Permanent::getName));
                for (Permanent m : mine) {
                    if (m.isLand(game)) { m.setTapped(false); lands.add(m); }
                    else if (m.isCreature(game)) {
                        Card own = game.getCard(m.getId());
                        String n = own != null && !(m instanceof mage.game.permanent.PermanentToken) ? own.getName() : m.getName();
                        boolean attacked = attackers.getOrDefault(n, 0) > 0 && !m.hasAbility(mage.abilities.keyword.VigilanceAbility.getInstance(), game);
                        if (attackers.getOrDefault(n, 0) > 0) attackers.merge(n, -1, Integer::sum);
                        m.setTapped(attacked);
                    }
                }
                // tap basics first, then other lands that make mana; never a land that makes none (Terramorphic
                // Expanse), whose own ability the record may still need
                lands.removeIf(m -> m.getAbilities().getActivatedManaAbilities(mage.constants.Zone.BATTLEFIELD).isEmpty());
                lands.sort(Comparator.comparing((Permanent m) -> m.isBasic(game) ? 0 : 1).thenComparing(Permanent::getName));
                int n = tap.has("lands") ? tap.get("lands").getAsInt() : 0;
                for (int i = 0; i < Math.min(n, lands.size()); i++) lands.get(i).setTapped(true);
            }
            if (w.has("hand")) {
                Map<String, Integer> need = counts(w.getAsJsonArray("hand"));
                for (Card c : new ArrayList<>(p.getHand().getCards(game))) {
                    if (need.getOrDefault(c.getName(), 0) > 0) need.merge(c.getName(), -1, Integer::sum);
                    else toLibrary(p, c, game);
                }
                for (Map.Entry<String, Integer> e : need.entrySet())
                    for (int i = 0; i < e.getValue(); i++) toHand(p, take(p, e.getKey(), game), game);
            }
            if (w.has("hand_count")) {
                int want_n = w.get("hand_count").getAsInt();
                while (p.getHand().size() > want_n) toLibrary(p, p.getHand().getCards(game).iterator().next(), game);
                while (p.getHand().size() < want_n && p.getLibrary().hasCards()) toHand(p, p.getLibrary().getFromBottom(game), game);
            }
        }
        game.applyEffects();
    }

    static final String FACE_DOWN = "[Face-Down Card]";

    /**
     * The record doesn't say what an Aura enchants. Attach it to a creature: the controller's own if its text says
     * "you control" or it helps (gets +, gains), else an opponent's; first by name, so runs agree.
     */
    private static void attachAura(Permanent aura, Player p, Game game) {
        String rules = String.join(" ", aura.getRules(game)).toLowerCase();
        boolean own = rules.contains("creature you control") || rules.contains("gets +") || rules.contains("gains") || rules.contains("has ");
        List<Permanent> mine = new ArrayList<>(), theirs = new ArrayList<>();
        for (Permanent c : game.getBattlefield().getAllActivePermanents()) {
            if (!c.isCreature(game) || c.getId().equals(aura.getId())) continue;
            (c.isControlledBy(p.getId()) ? mine : theirs).add(c);
        }
        Comparator<Permanent> byName = Comparator.comparing(Permanent::getName);
        mine.sort(byName); theirs.sort(byName);
        List<Permanent> first = own ? mine : theirs, second = own ? theirs : mine;
        Permanent host = !first.isEmpty() ? first.get(0) : !second.isEmpty() ? second.get(0) : null;
        if (host != null) host.addAttachment(aura.getId(), null, game);
    }

    /** Set a boolean field of a permanent without events (Room door state lives in PermanentImpl). */
    private static void setField(Permanent m, String name, boolean v) {
        try {
            java.lang.reflect.Field f = mage.game.permanent.PermanentImpl.class.getDeclaredField(name);
            f.setAccessible(true);
            f.setBoolean(m, v);
        } catch (ReflectiveOperationException e) {
            throw new IllegalStateException(e);
        }
    }

    /** Set a life total without life-gain or life-loss events (PlayerImpl.life is protected). */
    private static void setLifeQuietly(Player p, int life) {
        try {
            java.lang.reflect.Field f = mage.players.PlayerImpl.class.getDeclaredField("life");
            f.setAccessible(true);
            f.setInt(p, life);
        } catch (ReflectiveOperationException e) {
            throw new IllegalStateException(e);
        }
    }

    private static Map<String, Integer> counts(JsonArray a) {
        Map<String, Integer> m = new HashMap<>();
        for (JsonElement e : a) m.merge(e.getAsString(), 1, Integer::sum);
        return m;
    }

    /** Remove a card with this name owned by p from its library, graveyard, hand or exile, in that order. */
    private static Card take(Player p, String name, Game game) {
        for (Card c : p.getLibrary().getCards(game)) if (c.getName().equals(name)) { p.getLibrary().remove(c.getId(), game); return c; }
        for (Card c : p.getGraveyard().getCards(game)) if (c.getName().equals(name)) { p.getGraveyard().remove(c); return c; }
        for (Card c : p.getHand().getCards(game)) if (c.getName().equals(name)) { p.getHand().remove(c); return c; }
        for (mage.game.ExileZone z : game.getExile().getExileZones())
            for (Card c : z.getCards(game)) if (c.getOwnerId().equals(p.getId()) && c.getName().equals(name)) { z.remove(c); return c; }
        return null;
    }

    private static void toHand(Player p, Card c, Game game) {
        if (c == null) return;
        p.getLibrary().remove(c.getId(), game);
        p.getHand().add(c);
        game.getState().setZone(c.getId(), mage.constants.Zone.HAND);
    }

    private static void toLibrary(Player p, Card c, Game game) {
        p.getHand().remove(c);
        p.getLibrary().putOnBottom(c, game);
        game.getState().setZone(c.getId(), mage.constants.Zone.LIBRARY);
    }

    /** Put the named cards on top of p's library, first name on top; names not in the library are skipped. */
    static void stack(Player p, List<String> names, Game game) {
        List<Card> picked = new ArrayList<>();
        Set<UUID> used = new HashSet<>();
        for (String n : names) {
            for (Card c : p.getLibrary().getCards(game)) {
                if (!used.contains(c.getId()) && c.getName().equals(n)) { picked.add(c); used.add(c.getId()); break; }
            }
        }
        for (int i = picked.size() - 1; i >= 0; i--) {
            Card c = picked.get(i);
            p.getLibrary().remove(c.getId(), game);
            p.getLibrary().putOnTop(c, game);
        }
    }

    /**
     * Keep cards the seat must still draw away from the top of its library: put up to 3 cards that aren't in its
     * remaining draw queue on top, so effects that mill, surveil or manifest from the top don't eat a recorded draw.
     */
    void protectTop(Player p, Game game) {
        List<String> q = shared.queue.get(p.getName());
        int pos = shared.pos.getOrDefault(p.getName(), 0);
        Map<String, Integer> pending = new HashMap<>();
        if (q != null) for (String n : q.subList(Math.min(pos, q.size()), q.size())) pending.merge(n, 1, Integer::sum);
        Map<String, Integer> inLib = new HashMap<>();
        for (Card c : p.getLibrary().getCards(game)) inLib.merge(c.getName(), 1, Integer::sum);
        List<Card> safe = new ArrayList<>();
        for (Card c : p.getLibrary().getCards(game)) {
            if (safe.size() >= 3) break;
            int spare = inLib.getOrDefault(c.getName(), 0) - pending.getOrDefault(c.getName(), 0);
            if (spare > 0) { safe.add(c); inLib.merge(c.getName(), -1, Integer::sum); }
        }
        for (Card c : safe) { p.getLibrary().remove(c.getId(), game); p.getLibrary().putOnTop(c, game); }
    }

    @Override
    public void shuffleLibrary(mage.abilities.Ability source, Game game) {
        super.shuffleLibrary(source, game);
        if (!game.isSimulation() && !shared.started && shared.resetOnShuffle.contains(getName())) shared.pos.put(getName(), 0);
    }

    @Override
    public int drawCards(int num, mage.abilities.Ability source, Game game, mage.game.events.GameEvent event) {
        if (!game.isSimulation()) {
            List<String> q = shared.queue.get(getName());
            int p = shared.pos.getOrDefault(getName(), 0);
            if (q != null && p < q.size()) {
                List<String> next = new ArrayList<>(q.subList(p, Math.min(q.size(), p + Math.max(0, num))));
                stack(this, next, game);
                shared.pos.put(getName(), p + next.size());
            }
        }
        int drawn = super.drawCards(num, source, game, event);
        if (!game.isSimulation() && shared.started) protectTop(this, game);
        return drawn;
    }

    @Override
    public boolean priority(Game game) {
        if (game.isSimulation()) return super.priority(game);
        shared.started = true;
        if (shared.rollback) {
            shared.rollback = false;
            shared.rollbacks++;
            shared.sentKey = "";
            game.rollbackTurns(0);
            return true;
        }
        PhaseStep step = game.getTurnStepType();
        if (game.isActivePlayer(playerId) && (step == PhaseStep.UPKEEP || step == PhaseStep.END_TURN)) {
            String key = game.getTurnNum() + "/" + step + "/" + shared.rollbacks;
            if (!key.equals(shared.sentKey)) {
                shared.sentKey = key;
                // every attempt at a turn sees the same random numbers (shuffles, random choices)
                if (step == PhaseStep.UPKEEP) mage.util.RandomUtil.setSeed(shared.seed * 1000 + game.getTurnNum());
                JsonObject msg = new JsonObject();
                msg.addProperty("type", step == PhaseStep.UPKEEP ? "turn_start" : "eot");
                decorate(msg, game);
                msg.add("state", dump(game));
                onReply(send(msg), game);
                if (shared.rollback) return priority(game);
            }
        }
        return super.priority(game);
    }

    private JsonObject send(JsonObject msg) {
        link.out.println(link.gson.toJson(msg));
        try {
            String line = link.in.readLine();
            if (line == null) throw new IllegalStateException("python closed the pipe");
            return link.gson.fromJson(line, JsonObject.class);
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    /** The true state of both players: for comparing with the record, never for a policy. */
    static JsonObject dump(Game game) {
        JsonObject out = new JsonObject();
        for (Player p : game.getPlayers().values()) {
            JsonObject s = new JsonObject();
            s.addProperty("life", p.getLife());
            s.addProperty("library", p.getLibrary().size());
            s.add("hand", names(p.getHand().getCards(game)));
            s.add("graveyard", names(p.getGraveyard().getCards(game)));
            JsonArray bf = new JsonArray();
            for (Permanent m : game.getBattlefield().getAllActivePermanents(p.getId())) {
                JsonObject j = new JsonObject();
                Card card = game.getCard(m.getId());
                // the card's own name: a face-down card's real one, a Room's full name even with both doors locked
                j.addProperty("name", card != null && !(m instanceof mage.game.permanent.PermanentToken) ? card.getName() : m.getName());
                j.addProperty("face_down", m.isFaceDown(game));
                j.addProperty("token", m instanceof mage.game.permanent.PermanentToken);
                j.addProperty("creature", m.isCreature(game));
                j.addProperty("land", m.isLand(game));
                j.addProperty("tapped", m.isTapped());
                bf.add(j);
            }
            s.add("battlefield", bf);
            out.add(p.getName(), s);
        }
        JsonArray exile = new JsonArray();
        for (Card c : game.getExile().getAllCards(game)) exile.add(c.getName());
        out.add("exile", exile);
        return out;
    }

    private static JsonArray names(Collection<Card> cards) {
        JsonArray a = new JsonArray();
        for (Card c : cards) a.add(c.getName());
        return a;
    }
}
