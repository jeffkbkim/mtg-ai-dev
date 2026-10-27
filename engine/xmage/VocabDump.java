import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import mage.abilities.Ability;
import mage.cards.Card;
import mage.cards.repository.*;
import java.nio.file.*;
import java.util.*;

/** Writes the DSK card and ability vocabulary (Duskmourn and its Special Guests: names and ability keys) as JSON. */
public class VocabDump {
    public static void main(String[] args) throws Exception {
        RepositoryUtil.bootstrapLocalDb();
        CardScanner.scan();
        Map<String, CardInfo> byName = DskCards.byName();  // Duskmourn plus its 10 Special Guests
        JsonArray cards = new JsonArray(), abilities = new JsonArray();
        // modes and alternative costs are abilities too, appended after the printed and granted ones so their ids stay put
        JsonArray extra = new JsonArray();
        for (CardInfo ci : byName.values()) {
            Card card = ci.createCard();
            cards.add(card.getName());
            List<Ability> list = AbilityKeys.keyedAbilities(card);
            for (int i = 0; i < list.size(); i++) {
                JsonObject a = new JsonObject();
                a.addProperty("key", card.getName() + "#" + i);
                a.addProperty("type", String.valueOf(list.get(i).getAbilityType()));
                a.addProperty("text", AbilityKeys.text(list.get(i)));
                abilities.add(a);
            }
            for (Ability a : card.getAbilities()) {
                if (!(a instanceof mage.abilities.costs.AlternativeSourceCosts)) continue;
                JsonObject x = new JsonObject();
                x.addProperty("key", AbilityKeys.altCostAbilityKey(card.getName(), a));
                x.addProperty("type", "AlternativeCost");
                x.addProperty("text", AbilityKeys.text(a));
                extra.add(x);
            }
            List<String> modeKeys = AbilityKeys.modeKeys(card);
            List<String> modeTexts = AbilityKeys.modeTexts(card);
            for (int i = 0; i < modeKeys.size(); i++) {
                JsonObject x = new JsonObject();
                x.addProperty("key", modeKeys.get(i));
                x.addProperty("type", "Mode");
                x.addProperty("text", modeTexts.get(i));
                extra.add(x);
            }
            List<Ability> granted = AbilityKeys.grantedAbilities(card);
            for (int i = 0; i < granted.size(); i++) {
                JsonObject a = new JsonObject();
                a.addProperty("key", card.getName() + "#g" + i);
                a.addProperty("type", String.valueOf(granted.get(i).getAbilityType()));
                a.addProperty("granted", true);
                a.addProperty("text", AbilityKeys.text(granted.get(i)));
                abilities.add(a);
            }
        }
        abilities.addAll(extra);
        JsonObject out = new JsonObject();
        out.addProperty("set", "DSK");
        out.addProperty("xmage", "1.4.62");
        out.add("cards", cards);
        out.add("abilities", abilities);
        // token names and named options come from recorded games, not the card list: keep them from the existing file
        Path path = Path.of(args[0]);
        if (Files.exists(path)) {
            JsonObject old = com.google.gson.JsonParser.parseString(Files.readString(path)).getAsJsonObject();
            for (String k : new String[]{"named_options", "named_options_note", "tokens", "tokens_note"}) if (old.has(k)) out.add(k, old.get(k));
        }
        Files.writeString(path, new GsonBuilder().setPrettyPrinting().create().toJson(out));
        System.out.println("VOCAB cards=" + cards.size() + " abilities=" + abilities.size() + " (modes and alternative costs: " + extra.size() + ")");
        System.exit(0);
    }
}
