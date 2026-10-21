import mage.cards.repository.*;
import java.util.*;

/** Prints "number<TAB>name" for every DSK card in XMage's card database (first printing per name). */
public class DskNumbers {
    public static void main(String[] args) {
        RepositoryUtil.bootstrapLocalDb();
        Map<String, String> seen = new TreeMap<>();
        for (CardInfo c : CardRepository.instance.findCards(new CardCriteria().setCodes("DSK"))) {
            String name = c.getName();
            if (!seen.containsKey(name) || Integer.parseInt(c.getCardNumber().replaceAll("\\D", "0")) < Integer.parseInt(seen.get(name).replaceAll("\\D", "0")))
                seen.put(name, c.getCardNumber());
        }
        seen.forEach((n, num) -> System.out.println(num + "\t" + n));
        System.exit(0);
    }
}
