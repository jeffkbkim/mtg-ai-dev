import com.google.gson.GsonBuilder;
import mage.cards.repository.*;
import java.nio.file.*;
import java.util.*;

/** Writes {card name: DSK collector number} for every DSK card XMage knows, so the soak can write .dck files. */
public class DskNumbers {
    public static void main(String[] args) throws Exception {
        RepositoryUtil.bootstrapLocalDb();
        CardScanner.scan();
        Map<String, String> numbers = new TreeMap<>();
        for (CardInfo ci : CardRepository.instance.findCards(new CardCriteria().setCodes("DSK"))) numbers.putIfAbsent(ci.getName(), ci.getCardNumber());
        Files.writeString(Path.of(args[0]), new GsonBuilder().setPrettyPrinting().create().toJson(numbers));
        System.out.println("wrote " + numbers.size() + " cards");
        System.exit(0);
    }
}
