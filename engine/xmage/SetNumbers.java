import mage.cards.repository.*;
import java.util.*;

/** Prints "number<TAB>name" for every card of the current set (see SetCards: -Dmtg.set or $MTG_SET, default DSK),
 *  lowest printing per name, and "SPG:number<TAB>name" for the Special Guests its boosters carry. */
public class SetNumbers {
    public static void main(String[] args) {
        RepositoryUtil.bootstrapLocalDb();
        String set = SetCards.current();
        Map<String, String> seen = new TreeMap<>();
        for (Map.Entry<String, CardInfo> e : SetCards.byName(set).entrySet()) {
            CardInfo c = e.getValue();
            seen.put(e.getKey(), set.equals(c.getSetCode()) ? c.getCardNumber() : c.getSetCode() + ":" + c.getCardNumber());
        }
        seen.forEach((n, num) -> System.out.println(num + "\t" + n));
        System.exit(0);
    }
}
