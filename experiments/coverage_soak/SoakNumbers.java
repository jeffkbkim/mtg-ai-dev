import com.google.gson.GsonBuilder;
import mage.cards.repository.*;
import java.nio.file.*;
import java.util.*;

/** Writes {card name: DSK collector number, or "SPG:n" for a Special Guest}, so the soak can write .dck files. */
public class SoakNumbers {
    public static void main(String[] args) throws Exception {
        RepositoryUtil.bootstrapLocalDb();
        CardScanner.scan();
        Map<String, String> numbers = new TreeMap<>();
        // Duskmourn cards by number; Special Guests as "SPG:<number>" since they live in another set
        for (CardInfo ci : DskCards.byName().values()) numbers.put(ci.getName(), ci.getSetCode().equals("DSK") ? ci.getCardNumber() : ci.getSetCode() + ":" + ci.getCardNumber());
        Files.writeString(Path.of(args[0]), new GsonBuilder().setPrettyPrinting().create().toJson(numbers));
        System.out.println("wrote " + numbers.size() + " cards");
        System.exit(0);
    }
}
