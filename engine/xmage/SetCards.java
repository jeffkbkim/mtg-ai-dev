import mage.cards.repository.*;
import java.util.*;

/**
 * The cards a draft of one set can open: the set's play-booster cards plus the Special Guests reprints its play
 * boosters carry (XMage files those under set SPG). One printing per name, the set's own printing first.
 *   DSK: the 276 Duskmourn cards plus 10 Special Guests.
 *   FDN: Foundations play-booster numbers 1-361 (271 cards plus basics; higher numbers are the starter/Jumpstart
 *        cards, not in play boosters) plus 10 Special Guests.
 * The set is picked by -Dmtg.set=FDN or the MTG_SET environment variable; DSK when neither is given.
 */
public final class SetCards {
    public static final Map<String, List<String>> SPECIAL_GUESTS = Map.of(
            "DSK", List.of("Collected Company", "Damnation", "Expropriate", "Hallowed Haunting", "Maddening Hex",
                    "Noxious Revival", "Phantasmal Image", "Sacrifice", "Soul Warden", "Unholy Heat"),
            "FDN", List.of("Akroma's Memorial", "Bloom Tender", "Condemn", "Embercleave", "Fiend Artisan",
                    "Goblin Bushwhacker", "Grim Tutor", "Paradise Druid", "Sphinx's Tutelage", "Temporal Manipulation"));
    /** Highest collector number a play booster can hold; a set missing here keeps every number. */
    private static final Map<String, Integer> MAX_BOOSTER_NUMBER = Map.of("FDN", 361);

    /** The set this run is for: -Dmtg.set, else $MTG_SET, else DSK. */
    public static String current() {
        String s = System.getProperty("mtg.set", System.getenv().getOrDefault("MTG_SET", "DSK"));
        if (!SPECIAL_GUESTS.containsKey(s)) throw new IllegalArgumentException("unsupported set " + s + ", known: " + SPECIAL_GUESTS.keySet());
        return s;
    }

    /** Name -> card info for the current set, sorted by name. */
    public static Map<String, CardInfo> byName() {
        return byName(current());
    }

    /** Name -> card info for one set, sorted by name. */
    public static Map<String, CardInfo> byName(String set) {
        return byName(set, true);
    }

    /** strict: a Special Guest missing from XMage's SPG set is an error (vocabulary dumps); otherwise it is left out. */
    static Map<String, CardInfo> byName(String set, boolean strict) {
        Map<String, CardInfo> out = new TreeMap<>();
        Integer max = MAX_BOOSTER_NUMBER.get(set);
        List<CardInfo> cards = new ArrayList<>(CardRepository.instance.findCards(new CardCriteria().setCodes(set)));
        cards.sort(Comparator.comparingInt(SetCards::number));  // lowest printing first
        for (CardInfo ci : cards) {
            if (max != null && number(ci) > max) continue;
            out.putIfAbsent(ci.getName(), ci);
        }
        for (String n : SPECIAL_GUESTS.get(set)) {
            List<CardInfo> found = CardRepository.instance.findCards(new CardCriteria().setCodes("SPG").name(n));
            if (found.isEmpty() && !strict) continue;
            if (found.isEmpty()) throw new IllegalStateException("Special Guest missing from XMage's SPG set: " + n);
            out.putIfAbsent(n, found.get(0));
        }
        return out;
    }

    /** Name -> card info over every supported set (for checks that must know all card names, like the leak checker).
     *  Lenient: a card this XMage build lacks is left out, never an error (the Playmat server runs another build). */
    public static Map<String, CardInfo> allSets() {
        Map<String, CardInfo> out = new TreeMap<>();
        for (String s : new TreeSet<>(SPECIAL_GUESTS.keySet())) byName(s, false).forEach(out::putIfAbsent);
        return out;
    }

    static int number(CardInfo ci) {
        String digits = ci.getCardNumber().replaceAll("\\D", "");
        return digits.isEmpty() ? Integer.MAX_VALUE : Integer.parseInt(digits);
    }

    private SetCards() { }
}
