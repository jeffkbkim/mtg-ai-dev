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

    /** Key of an ability in a running game, or null if it can't be mapped. */
    public static String key(Game game, Ability ability) {
        Card card = game.getCard(ability.getSourceId());
        if (card instanceof SubCard) card = ((SubCard<?>) card).getParentCard();
        if (card != null) {
            List<Ability> list = keyedAbilities(card);
            for (int i = 0; i < list.size(); i++) {
                if (list.get(i).getOriginalId().equals(ability.getOriginalId())) return card.getName() + "#" + i;
            }
        }
        return granted(game).get(ability.getOriginalId());
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
