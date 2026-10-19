import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import mage.cards.Card;
import mage.cards.repository.*;
import java.nio.file.*;
import java.util.*;

/** Writes the rules text of every DSK card as XMage implements it (name, cost, types, P/T, rules lines) as JSON. */
public class CardTextDump {
    public static void main(String[] args) throws Exception {
        RepositoryUtil.bootstrapLocalDb();
        CardScanner.scan();
        Map<String, CardInfo> byName = new TreeMap<>();
        for (CardInfo ci : CardRepository.instance.findCards(new CardCriteria().setCodes("DSK"))) byName.putIfAbsent(ci.getName(), ci);
        JsonArray cards = new JsonArray();
        for (CardInfo ci : byName.values()) {
            Card card = ci.createCard();
            JsonObject c = new JsonObject();
            c.addProperty("name", card.getName());
            c.addProperty("cost", card.getManaCost().getText());
            c.addProperty("mana_value", card.getManaValue());
            c.addProperty("types", ci.getTypes().toString() + (ci.getSubTypes().isEmpty() ? "" : " - " + ci.getSubTypes()));
            c.addProperty("rarity", String.valueOf(ci.getRarity()));
            if (card.isCreature()) c.addProperty("pt", card.getPower().getValue() + "/" + card.getToughness().getValue());
            JsonArray rules = new JsonArray();
            for (String r : card.getRules()) rules.add(r.replaceAll("<[^>]+>", "").replace("&mdash;", "-"));
            c.add("rules", rules);
            if (card instanceof mage.cards.SplitCard) {
                mage.cards.SplitCard s = (mage.cards.SplitCard) card;
                for (Card half : new Card[]{s.getLeftHalfCard(), s.getRightHalfCard()}) {
                    JsonObject h = new JsonObject();
                    h.addProperty("name", half.getName());
                    h.addProperty("cost", half.getManaCost().getText());
                    JsonArray hr = new JsonArray();
                    for (String r : half.getRules()) hr.add(r.replaceAll("<[^>]+>", "").replace("&mdash;", "-"));
                    h.add("rules", hr);
                    c.add(half == s.getLeftHalfCard() ? "left" : "right", h);
                }
            }
            cards.add(c);
        }
        Files.writeString(Path.of(args[0]), new GsonBuilder().setPrettyPrinting().disableHtmlEscaping().create().toJson(cards));
        System.out.println("CARD_TEXT cards=" + cards.size());
        System.exit(0);
    }
}
