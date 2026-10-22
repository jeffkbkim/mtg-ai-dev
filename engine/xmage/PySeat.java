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
        long simulated = 0;  // decisions inside XMage AI simulations, answered in Java (see PySeat.simulated)
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

    /**
     * XMage's AI tries moves on copies of the game (createSimulationForAI), and the copies hold a copy of this seat
     * that shares the same link. Questions from those make-believe games must not reach Python: they show states
     * that never happen (often the AI's own candidate blocks) and their answers change nothing real. In a
     * simulation this seat decides like XMage's ComputerPlayer instead.
     */
    private boolean simulated(Game game) {
        if (!game.isSimulation()) return false;
        link.simulated++;
        return true;
    }

    /**
     * Mana is paid automatically. ComputerPlayer's payer had three faults that cost our players real plays (ManaCheck):
     * with Enduring Vitality it tapped creatures while lands stood untapped; it tries a source's biggest mana ability
     * first, so Overgrown Zealot made its two face-up-only mana and the spell was rolled back; and it spent the only
     * Island on a generic cost while the player held a blue instant. Each payment step here pays one symbol, coloured
     * symbols before generic, from the source that matters least: lands before creatures (creatures only when nothing
     * else can pay, and never the permanent whose own {T} the ability needs), then the source whose colours the
     * other cards in hand need least, then the one with fewer colours. Mana that can't be spent on this ability is
     * skipped. Anything this can't pay (X, phyrexian, convoke, ...) falls back to XMage's payer, lands first.
     */
    private transient boolean skipCreatureMana = false;

    @Override
    protected boolean playManaHandling(Ability ability, mage.abilities.costs.mana.ManaCost unpaid, Game game) {
        if (payStep(ability, unpaid, game, false) || payStep(ability, unpaid, game, true)) return true;
        skipCreatureMana = true;
        try {
            if (super.playManaHandling(ability, unpaid, game)) return true;  // false means nothing was activated
        } finally {
            skipCreatureMana = false;
        }
        return super.playManaHandling(ability, unpaid, game);
    }

    private static final mage.constants.ColoredManaSymbol[] COLOURS = mage.constants.ColoredManaSymbol.values();

    private static int amount(mage.Mana m, mage.constants.ColoredManaSymbol c) {
        return m.getAny() > 0 ? 1 : m.getColor(c);
    }

    private boolean payStep(Ability ability, mage.abilities.costs.mana.ManaCost unpaid, Game game, boolean creatures) {
        List<mage.abilities.costs.mana.ManaCost> symbols = new ArrayList<>();
        if (unpaid instanceof mage.abilities.costs.mana.ManaCosts) symbols.addAll((mage.abilities.costs.mana.ManaCosts<mage.abilities.costs.mana.ManaCost>) unpaid);
        else symbols.add(unpaid);
        symbols.removeIf(c -> c.isPaid() || c instanceof mage.abilities.costs.mana.VariableManaCost || c.isPhyrexian());
        symbols.sort(Comparator.comparingInt(c -> c instanceof mage.abilities.costs.mana.GenericManaCost ? 1 : 0));
        if (symbols.isEmpty()) return false;
        boolean tapsSource = ability.getCosts().stream().anyMatch(c -> c instanceof mage.abilities.costs.common.TapSourceCost);
        int[] need = new int[COLOURS.length];  // coloured symbols of the other cards in hand, per colour
        for (Card c : getHand().getCards(game)) {
            if (c.getId().equals(ability.getSourceId())) continue;
            mage.Mana m = c.getManaCost().getMana();
            for (int i = 0; i < COLOURS.length; i++) need[i] += m.getColor(COLOURS[i]);
        }
        Map<MageObject, int[]> keys = new HashMap<>();  // [need of its colours, colours it makes]
        List<MageObject> sources = new ArrayList<>();
        for (MageObject o : super.getAvailableManaProducers(game)) {
            if (o.isCreature(game) != creatures) continue;
            if (tapsSource && o.getId().equals(ability.getSourceId())) continue;
            int needed = 0, colours = 0;
            for (int i = 0; i < COLOURS.length; i++) {
                final int k = i;
                boolean makes = o.getAbilities().getAvailableActivatedManaAbilities(mage.constants.Zone.BATTLEFIELD, playerId, game).stream()
                        .anyMatch(ma -> ma.getNetMana(game).stream().anyMatch(m -> amount(m, COLOURS[k]) > 0));
                if (makes) { needed += need[i]; colours++; }
            }
            keys.put(o, new int[]{needed, colours});
            sources.add(o);
        }
        Set<MageObject> plan = planPayment(ability, symbols, sources, keys, game);
        if (plan.isEmpty()) sources.sort(Comparator.<MageObject>comparingInt(o -> keys.get(o)[0]).thenComparingInt(o -> keys.get(o)[1]));
        else sources.sort(Comparator.<MageObject>comparingInt(o -> plan.contains(o) ? 0 : 1).thenComparingInt(o -> keys.get(o)[1]));
        for (mage.abilities.costs.mana.ManaCost symbol : symbols) {
            for (MageObject o : sources) {
                List<mage.abilities.mana.ActivatedManaAbilityImpl> abilities = new ArrayList<>(
                        o.getAbilities().getAvailableActivatedManaAbilities(mage.constants.Zone.BATTLEFIELD, playerId, game));
                abilities.sort(Comparator.comparingInt(ma -> ma.getNetMana(game).stream().mapToInt(mage.Mana::count).max().orElse(0)));
                for (mage.abilities.mana.ActivatedManaAbilityImpl ma : abilities) {
                    for (mage.Mana net : ma.getNetMana(game)) {
                        if (net instanceof mage.ConditionalMana && !((mage.ConditionalMana) net).apply(ability, game, playerId, symbol)) continue;
                        if (!symbol.testPay(net)) continue;
                        if (activateAbility(ma, game)) return true;
                    }
                }
            }
        }
        return false;
    }

    /** Colours a source can make for this ability as a bitmask (W U B R G), or -1 if it makes more than one mana at once. */
    private int colourMask(MageObject o, Ability ability, mage.abilities.costs.mana.ManaCost symbol, Game game) {
        int mask = 0;
        for (mage.abilities.mana.ActivatedManaAbilityImpl ma : o.getAbilities().getAvailableActivatedManaAbilities(mage.constants.Zone.BATTLEFIELD, playerId, game))
            for (mage.Mana net : ma.getNetMana(game)) {
                if (net instanceof mage.ConditionalMana && !((mage.ConditionalMana) net).apply(ability, game, playerId, symbol)) continue;
                if (net.count() > 1) return -1;
                for (int i = 0; i < COLOURS.length; i++) if (amount(net, COLOURS[i]) > 0) mask |= 1 << i;
            }
        return mask;
    }

    /** {W, U, B, R, G, generic} of a cost, or null for symbols the planner doesn't handle (hybrid, {C}, snow, X). */
    private static int[] split(Collection<? extends mage.abilities.costs.mana.ManaCost> costs) {
        int[] r = new int[COLOURS.length + 1];
        for (mage.abilities.costs.mana.ManaCost c : costs) {
            mage.abilities.costs.mana.ManaCost u = c.getUnpaid();
            if (c instanceof mage.abilities.costs.mana.GenericManaCost) r[COLOURS.length] += u.getMana().getGeneric();
            else if (c instanceof mage.abilities.costs.mana.ColoredManaCost)
                for (int i = 0; i < COLOURS.length; i++) r[i] += u.getMana().getColor(COLOURS[i]);
            else return null;
        }
        return r;
    }

    /** Can these sources (one mana each, colour bitmasks) pay {pips..., generic}? Pips are matched by backtracking. */
    private static boolean canPay(int[] cost, List<Integer> masks) {
        List<Integer> pips = new ArrayList<>();
        for (int i = 0; i < COLOURS.length; i++) for (int k = 0; k < cost[i]; k++) pips.add(i);
        if (pips.size() + cost[COLOURS.length] > masks.size()) return false;
        return match(pips, 0, masks, new boolean[masks.size()]);
    }

    private static boolean match(List<Integer> pips, int at, List<Integer> masks, boolean[] used) {
        if (at == pips.size()) return true;
        for (int j = 0; j < masks.size(); j++)
            if (!used[j] && (masks.get(j) & (1 << pips.get(at))) != 0) {
                used[j] = true;
                if (match(pips, at + 1, masks, used)) return true;
                used[j] = false;
            }
        return false;
    }

    /**
     * Which sources to tap for what is still unpaid: of the ways to pay it with one mana per source, the one whose
     * untapped remainder leaves the most cards in hand castable (instants and flash cards count three times), then the
     * one tapping sources whose colours the hand needs least, then fewer colours. Empty when it can't plan (a source
     * making two mana, symbols other than coloured and generic, too many sources); the caller then uses its own order.
     */
    private Set<MageObject> planPayment(Ability ability, List<mage.abilities.costs.mana.ManaCost> symbols, List<MageObject> sources,
                                        Map<MageObject, int[]> keys, Game game) {
        int[] cost = split(symbols);
        if (cost == null || sources.size() > 14) return Collections.emptySet();
        int total = Arrays.stream(cost).sum();
        if (total == 0 || total > sources.size()) return Collections.emptySet();
        List<Integer> masks = new ArrayList<>();
        for (MageObject o : sources) {
            int m = colourMask(o, ability, symbols.get(0), game);
            if (m < 0) return Collections.emptySet();
            masks.add(m);
        }
        List<List<int[]>> hand = new ArrayList<>();  // per other card in hand: the costs of its ways to be cast
        List<Integer> weights = new ArrayList<>();
        for (Card c : getHand().getCards(game)) {
            if (c.isLand(game) || c.getId().equals(ability.getSourceId())) continue;
            List<Card> ways = c instanceof mage.cards.SplitCard  // a Room's doors are cast separately
                    ? Arrays.asList(((mage.cards.SplitCard) c).getLeftHalfCard(), ((mage.cards.SplitCard) c).getRightHalfCard())
                    : Collections.singletonList(c);
            List<int[]> costs = new ArrayList<>();
            for (Card w : ways) {
                int[] wc = split(w.getManaCost());
                if (wc != null) costs.add(wc);
            }
            if (costs.isEmpty()) continue;
            hand.add(costs);
            weights.add(c.isInstant(game) || c.getAbilities(game).containsClass(mage.abilities.keyword.FlashAbility.class) ? 3 : 1);
        }
        int n = sources.size();
        long best = Long.MIN_VALUE;
        int bestSet = -1;
        for (int set = 0; set < (1 << n); set++) {
            if (Integer.bitCount(set) != total) continue;
            List<Integer> tapped = new ArrayList<>(), rest = new ArrayList<>();
            int neededSum = 0, coloursSum = 0;
            for (int j = 0; j < n; j++) {
                if ((set & (1 << j)) != 0) {
                    tapped.add(masks.get(j));
                    neededSum += keys.get(sources.get(j))[0];
                    coloursSum += keys.get(sources.get(j))[1];
                } else rest.add(masks.get(j));
            }
            if (!canPay(cost, tapped)) continue;
            int keep = 0;
            for (int h = 0; h < hand.size(); h++)
                if (hand.get(h).stream().anyMatch(way -> canPay(way, rest))) keep += weights.get(h);
            long score = ((long) keep << 32) - ((long) neededSum << 16) - coloursSum;
            if (score > best) { best = score; bestSet = set; }
        }
        if (bestSet < 0) return Collections.emptySet();
        Set<MageObject> plan = new HashSet<>();
        for (int j = 0; j < n; j++) if ((bestSet & (1 << j)) != 0) plan.add(sources.get(j));
        return plan;
    }

    @Override
    public List<MageObject> getAvailableManaProducers(Game game) {
        List<MageObject> producers = super.getAvailableManaProducers(game);
        if (skipCreatureMana) producers.removeIf(o -> o.isCreature(game));
        return producers;
    }

    @Override
    public List<Permanent> getAvailableManaProducersWithCost(Game game) {
        List<Permanent> producers = super.getAvailableManaProducersWithCost(game);
        if (skipCreatureMana) producers.removeIf(o -> o.isCreature(game));
        return producers;
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
        if (simulated(game)) return super.priority(game);
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
        for (ActivatedAbility a : playable(game)) {
            if (a.isManaAbility() || failedThisWindow.contains(a.getId())) continue;
            if (resources(game).equals(refusedAt.get(a.getId()))) continue;
            if (a instanceof mage.abilities.keyword.CrewAbility && !canCrew(a, game)) continue;
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

    /**
     * getPlayable(game, true) keeps one ability per rules text (meant for the UI), so with two Glimmerlights on the
     * battlefield only one Equip was offered, often the attached one. The abilities it dropped from other permanents
     * are added back after its list; cards in hand and elsewhere are listed as before.
     */
    private List<ActivatedAbility> playable(Game game) {
        List<ActivatedAbility> list = new ArrayList<>(getPlayable(game, true));
        Set<UUID> ids = new HashSet<>();
        for (ActivatedAbility a : list) ids.add(a.getId());
        for (ActivatedAbility a : getPlayable(game, true, mage.constants.Zone.ALL, false))
            if (game.getPermanent(a.getSourceId()) != null && ids.add(a.getId())) list.add(a);
        return list;
    }

    /**
     * XMage's CrewCost.canPay checks "another untapped creature you control" without the vehicle as source, so a
     * crewed, untapped vehicle counts toward its own Crew and the ability is listed as playable, then refused when
     * paid (soak: Hedge Shredder, Unidentified Hovership). Check it properly: other untapped creatures' total power.
     */
    private boolean canCrew(ActivatedAbility a, Game game) {
        java.util.regex.Matcher m = java.util.regex.Pattern.compile("Crew (\\d+)").matcher(a.getRule());
        if (!m.find()) return true;  // unknown wording: leave it to XMage
        int need = Integer.parseInt(m.group(1)), power = 0;
        for (Permanent p : game.getBattlefield().getAllActivePermanents(playerId)) {
            if (p.getId().equals(a.getSourceId()) || p.isTapped() || !p.isCreature(game)) continue;
            power += Math.max(0, p.getPower().getValue());
            if (power >= need) return true;
        }
        return false;
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

    /**
     * XMage calls chooseTarget again whenever the previous call added a target and the choice isn't complete
     * (TargetImpl.chooseTarget), so after DONE the same prompt came back once more and the player had to say DONE
     * twice (or, thinking the first DONE was lost, picked another target). That follow-up call is answered here with
     * nothing added, which ends XMage's loop.
     */
    private transient Target doneTarget = null;
    private transient int doneSize = -1;

    private boolean chooseTargets(String kind, Target target, Ability source, Game game, boolean isTargeting, Cards fromCards) {
        if (target == doneTarget && target.getTargets().size() == doneSize) {
            doneTarget = null;
            return target.isChosen(game);
        }
        doneTarget = null;
        int sizeBefore = target.getTargets().size();
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
            if (done[0]) {
                if (target.getTargets().size() > sizeBefore) { doneTarget = target; doneSize = target.getTargets().size(); }
                break;
            }
        }
        return target.isChosen(game);
    }

    @Override
    public boolean chooseTarget(Outcome outcome, Target target, Ability source, Game game) {
        if (simulated(game)) return super.chooseTarget(outcome, target, source, game);
        return chooseTargets("TARGET", target, source, game, true, null);
    }

    @Override
    public boolean choose(Outcome outcome, Target target, Ability source, Game game, Map<String, Serializable> options) {
        if (simulated(game)) return super.choose(outcome, target, source, game, options);
        return chooseTargets("CHOOSE", target, source, game, false, null);
    }

    @Override
    public boolean choose(Outcome outcome, Cards cards, TargetCard target, Ability source, Game game) {
        if (simulated(game)) return super.choose(outcome, cards, target, source, game);
        return chooseTargets("CHOOSE_CARDS", target, source, game, false, cards);
    }

    @Override
    public boolean chooseTarget(Outcome outcome, Cards cards, TargetCard target, Ability source, Game game) {
        if (simulated(game)) return super.chooseTarget(outcome, cards, target, source, game);
        return chooseTargets("TARGET_CARDS", target, source, game, true, cards);
    }

    // ---------- small choices ----------

    @Override
    public boolean chooseUse(Outcome outcome, String message, String secondMessage, String trueText, String falseText, Ability source, Game game) {
        if (simulated(game)) return super.chooseUse(outcome, message, secondMessage, trueText, falseText, source, game);
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
        if (simulated(game)) return super.choose(outcome, choice, game);
        // mana colour choices belong to the autopayer (v1: autotap); "Choose color" for a mana ability is one too
        if (choice.isManaColorChoice() || choice.getMessage() != null && choice.getMessage().toLowerCase().contains("mana")) {
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
        if (simulated(game)) return super.chooseMode(modes, source, game);
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
        if (simulated(game)) return super.chooseTriggeredAbility(abilities, game);
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
        if (simulated(game)) { super.selectAttackers(game, attackingPlayerId); return; }
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
        if (simulated(game)) { super.selectBlockers(source, game, defendingPlayerId); return; }
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
        if (simulated(game)) return super.chooseMulligan(game);
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

    /**
     * X for a mana cost is still XMage's AI choice (the most the untapped sources cover), but its formula takes X =
     * sources minus the rest of the cost, as if X appeared once: with 7 Forests Valgavoth's Onslaught ({X}{X}{G}) got
     * X = 6, needing 13 mana, so every cast was refused. Divided by the number of X symbols here.
     */
    @Override
    public int announceX(int min, int max, String message, Game game, Ability source, boolean isManaPay) {
        fallback("ANNOUNCE_X");
        int x = super.announceX(min, max, message, game, source, isManaPay);
        if (!isManaPay || source == null) return x;
        int instances = 0;
        for (mage.abilities.costs.VariableCost v : source.getManaCostsToPay().getVariableCosts())
            if (v instanceof mage.abilities.costs.mana.VariableManaCost) instances += ((mage.abilities.costs.mana.VariableManaCost) v).getXInstancesCount();
        return instances > 1 ? Math.max(min, x / instances) : x;
    }

    @Override
    public int getAmount(int min, int max, String message, Ability source, Game game) { fallback("AMOUNT"); return super.getAmount(min, max, message, source, game); }

    @Override
    public int chooseReplacementEffect(Map<String, String> effectsMap, Map<String, MageObject> objectsMap, Game game) { fallback("REPLACEMENT"); return super.chooseReplacementEffect(effectsMap, objectsMap, game); }
}
