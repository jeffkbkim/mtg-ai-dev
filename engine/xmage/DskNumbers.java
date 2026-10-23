import mage.cards.repository.*;
import java.util.*;

/** Prints "number<TAB>name" for every DSK card in XMage's card database (first printing per name), and
 *  "SPG:number<TAB>name" for the 10 Special Guests DSK boosters carry (see DskCards). */
public class DskNumbers {
    public static void main(String[] args) {
        RepositoryUtil.bootstrapLocalDb();
        Map<String, String> seen = new TreeMap<>();
        for (CardInfo c : CardRepository.instance.findCards(new CardCriteria().setCodes("DSK"))) {
            String name = c.getName();
            if (!seen.containsKey(name) || Integer.parseInt(c.getCardNumber().replaceAll("\\D", "0")) < Integer.parseInt(seen.get(name).replaceAll("\\D", "0")))
                seen.put(name, c.getCardNumber());
        }
        for (String n : DskCards.SPECIAL_GUESTS) {
            List<CardInfo> g = CardRepository.instance.findCards(new CardCriteria().setCodes("SPG").name(n));
            if (!g.isEmpty()) seen.putIfAbsent(n, "SPG:" + g.get(0).getCardNumber());
        }
        seen.forEach((n, num) -> System.out.println(num + "\t" + n));
        System.exit(0);
    }
}
