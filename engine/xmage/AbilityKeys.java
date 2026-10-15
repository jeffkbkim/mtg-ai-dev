import mage.abilities.Ability;
import mage.cards.Card;
import mage.cards.SplitCard;
import mage.cards.SubCard;
import mage.game.Game;

import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.util.*;

/**
 * Stable ability vocabulary keys: "<card name>#<index>", where index counts the card's
 * non-mana triggered and activated abilities in the card's own order (main card first, then
 * the left and right halves of split cards and Rooms). XMage's ability ids change every game; these don't.
 *
 * Abilities a card gives to something else ("enchanted creature has ward {2}", a token's abilities) are
 * keyed "<card name>#g<index>": they belong to the card that grants them, found by looking inside its effects.
 */
public final class AbilityKeys {

    public static boolean keyed(Ability a) {
        switch (a.getAbilityType()) {
            case TRIGGERED_NONMANA:
            case ACTIVATED_NONMANA:
                return true;
            default:
                return false;
        }
    }

    public static List<Ability> keyedAbilities(Card card) {
        List<Ability> out = new ArrayList<>();
        for (Ability a : card.getAbilities()) if (keyed(a)) out.add(a);
        if (card instanceof SplitCard) {
            SplitCard s = (SplitCard) card;
            for (Ability a : s.getLeftHalfCard().getAbilities()) if (keyed(a)) out.add(a);
            for (Ability a : s.getRightHalfCard().getAbilities()) if (keyed(a)) out.add(a);
        }
        return out;
    }

    /** Keyed abilities this card grants to other objects or puts on tokens, found inside its effects. */
    public static List<Ability> grantedAbilities(Card card) {
        List<Ability> own = new ArrayList<>(card.getAbilities());
        if (card instanceof SplitCard) {
            own.addAll(((SplitCard) card).getLeftHalfCard().getAbilities());
            own.addAll(((SplitCard) card).getRightHalfCard().getAbilities());
        }
        Set<UUID> printed = new HashSet<>();
        for (Ability a : keyedAbilities(card)) printed.add(a.getOriginalId());
        List<Ability> out = new ArrayList<>();
        Set<UUID> seen = new HashSet<>();
        for (Ability a : own) {
            for (mage.abilities.Mode m : a.getModes().values()) {
                for (mage.abilities.effects.Effect e : m.getEffects()) collect(e, out, seen, printed, 0);
            }
        }
        return out;
    }

    private static void collect(Object o, List<Ability> out, Set<UUID> seen, Set<UUID> printed, int depth) {
        if (o == null || depth > 3) return;
        if (o instanceof Ability) {
            Ability a = (Ability) o;
            if (keyed(a) && !printed.contains(a.getOriginalId()) && seen.add(a.getOriginalId())) out.add(a);
            for (mage.abilities.Mode m : a.getModes().values()) {
                for (mage.abilities.effects.Effect e : m.getEffects()) collect(e, out, seen, printed, depth + 1);
            }
            return;
        }
        if (o instanceof mage.game.permanent.token.Token) {
            for (Ability a : ((mage.game.permanent.token.Token) o).getAbilities()) collect(a, out, seen, printed, depth + 1);
            return;
        }
        if (o instanceof Collection) {
            for (Object x : (Collection<?>) o) collect(x, out, seen, printed, depth + 1);
            return;
        }
        if (o instanceof mage.abilities.effects.Effect) {
            for (Class<?> c = o.getClass(); c != null && c != Object.class; c = c.getSuperclass()) {
                for (Field f : c.getDeclaredFields()) {
                    if (Modifier.isStatic(f.getModifiers())) continue;
                    Class<?> t = f.getType();
                    if (!(Ability.class.isAssignableFrom(t) || Collection.class.isAssignableFrom(t)
                            || mage.game.permanent.token.Token.class.isAssignableFrom(t)
                            || mage.abilities.effects.Effect.class.isAssignableFrom(t))) continue;
                    try {
                        f.setAccessible(true);
                        collect(f.get(o), out, seen, printed, depth + 1);
                    } catch (Exception ignored) {
                        // field not readable: that grant stays unmapped and is reported at runtime
                    }
                }
            }
        }
    }

    // per game: original ability id -> key of a granted ability
    private static final Map<UUID, Map<UUID, String>> grantedByGame = new HashMap<>();

    private static synchronized Map<UUID, String> granted(Game game) {
        return grantedByGame.computeIfAbsent(game.getId(), g -> {
            Map<UUID, String> m = new HashMap<>();
            for (Card card : game.getCards()) {
                if (card instanceof SubCard) continue;
                List<Ability> list = grantedAbilities(card);
                for (int i = 0; i < list.size(); i++) m.putIfAbsent(list.get(i).getOriginalId(), card.getName() + "#g" + i);
            }
            return m;
        });
    }

    // printed card objects by name, for permanents that are copies of another card
    private static final Map<String, Card> templates = new HashMap<>();

    private static synchronized Card template(String name) {
        return templates.computeIfAbsent(name, n -> {
            List<mage.cards.repository.CardInfo> found = mage.cards.repository.CardRepository.instance.findCards(n);
            return found.isEmpty() ? null : found.get(0).createCard();
        });
    }

    /** Cards whose printed abilities an object may be using: its own card, and the card it is a copy of. */
    private static List<Card> candidates(Game game, UUID sourceId) {
        List<Card> out = new ArrayList<>();
        Card card = game.getCard(sourceId);
        if (card instanceof SubCard) card = ((SubCard<?>) card).getParentCard();
        if (card != null) out.add(card);
        mage.game.permanent.Permanent p = game.getPermanentOrLKIBattlefield(sourceId);
        if (p != null && !p.isFaceDown(game) && (card == null || !p.getName().equals(card.getName()))) {
            Card copied = template(p.getName());
            if (copied != null) out.add(copied);
        }
        return out;
    }

    private static boolean sameAbility(Ability printed, Ability running, boolean sameCard) {
        if (sameCard && printed.getOriginalId().equals(running.getOriginalId())) return true;
        // a card turned face up (e.g. after manifest dread) or a copy gets fresh ability objects: match class + rules text
        return printed.getClass() == running.getClass() && text(printed).equals(text(running));
    }

    /** Key of an ability in a running game, or null if it can't be mapped. */
    public static String key(Game game, Ability ability) {
        List<Card> cards = candidates(game, ability.getSourceId());
        for (int pass = 0; pass < 2; pass++) {  // exact ids first, then rules text
            for (int c = 0; c < cards.size(); c++) {
                List<Ability> list = keyedAbilities(cards.get(c));
                for (int i = 0; i < list.size(); i++) {
                    Ability a = list.get(i);
                    boolean hit = pass == 0 ? c == 0 && a.getOriginalId().equals(ability.getOriginalId()) : sameAbility(a, ability, false);
                    if (hit) return cards.get(c).getName() + "#" + i;
                }
            }
        }
        return granted(game).get(ability.getOriginalId());
    }

    // ---- named choices: what a non-card answer means, independent of the order XMage lists it in ----

    /** Choice key of an alternative cost, e.g. "alt_cost:ImpendingAbility". */
    public static String altCostKey(Object altCost) {
        return "alt_cost:" + altCost.getClass().getSimpleName();
    }

    public static final String NO_ALT_COST = "alt_cost:none";

    /** Modal abilities of a card in printed order (main card, then halves). */
    public static List<Ability> modalAbilities(Card card) {
        List<Ability> all = new ArrayList<>(card.getAbilities());
        if (card instanceof SplitCard) {
            all.addAll(((SplitCard) card).getLeftHalfCard().getAbilities());
            all.addAll(((SplitCard) card).getRightHalfCard().getAbilities());
        }
        List<Ability> out = new ArrayList<>();
        for (Ability a : all) if (a.getModes().size() > 1) out.add(a);
        return out;
    }

    /** Mode keys of a card: "<card name>#mode<i>", i counting the modes of its modal abilities in printed order. */
    public static List<String> modeKeys(Card card) {
        List<String> out = new ArrayList<>();
        for (Ability a : modalAbilities(card)) {
            for (int i = 0; i < a.getModes().size(); i++) out.add(card.getName() + "#mode" + out.size());
        }
        return out;
    }

    /** Key of one mode of a modal ability in a running game, or null if it can't be mapped. */
    public static String modeKey(Game game, Ability source, mage.abilities.Mode mode) {
        List<Card> cards = candidates(game, source.getSourceId());
        for (int c = 0; c < cards.size(); c++) {
            int offset = 0;
            for (Ability a : modalAbilities(cards.get(c))) {
                if (sameAbility(a, source, c == 0)) {
                    // the running ability's modes keep printed order
                    int i = new ArrayList<>(source.getModes().keySet()).indexOf(mode.getId());
                    if (i < 0) {  // fresh mode objects: match the mode's effect text against the printed modes
                        String want = mode.getEffects().getText(mode);
                        List<mage.abilities.Mode> printed = new ArrayList<>(a.getModes().values());
                        for (int k = 0; k < printed.size(); k++) {
                            if (printed.get(k).getEffects().getText(printed.get(k)).equals(want)) i = k;
                        }
                    }
                    if (i >= 0) return cards.get(c).getName() + "#mode" + (offset + i);
                }
                offset += a.getModes().size();
            }
        }
        return null;
    }

    /** Readable text for the vocabulary file. */
    public static String text(Ability a) {
        try {
            return a.getRule();
        } catch (Exception e) {
            return a.getClass().getSimpleName();
        }
    }
}
