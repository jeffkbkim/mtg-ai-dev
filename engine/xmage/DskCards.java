import mage.cards.repository.*;
import java.util.*;

/**
 * The cards a DSK draft can open: the 276 Duskmourn cards plus the 10 Special Guests reprints its play boosters
 * carry (XMage files those under set SPG). One printing per name, Duskmourn first.
 */
public final class DskCards {
    public static final List<String> SPECIAL_GUESTS = List.of(
            "Collected Company", "Damnation", "Expropriate", "Hallowed Haunting", "Maddening Hex",
            "Noxious Revival", "Phantasmal Image", "Sacrifice", "Soul Warden", "Unholy Heat");

    /** Name -> card info, sorted by name. */
    public static Map<String, CardInfo> byName() {
        Map<String, CardInfo> out = new TreeMap<>();
        for (CardInfo ci : CardRepository.instance.findCards(new CardCriteria().setCodes("DSK"))) out.putIfAbsent(ci.getName(), ci);
        for (String n : SPECIAL_GUESTS) {
            List<CardInfo> found = CardRepository.instance.findCards(new CardCriteria().setCodes("SPG").name(n));
            if (found.isEmpty()) throw new IllegalStateException("Special Guest missing from XMage's SPG set: " + n);
            out.putIfAbsent(n, found.get(0));
        }
        return out;
    }

    private DskCards() { }
}
