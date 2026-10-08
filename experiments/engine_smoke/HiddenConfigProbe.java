import org.mage.magezero.Config;
import java.util.Map;

/** Reproduce the released MageZero sample-config key mismatch without any game data. */
public class HiddenConfigProbe {
    public static void main(String[] args) {
        for (String key : new String[]{"hidden_info", "hiddenInfo"}) {
            Config.PlayerConfig config = new Config.PlayerConfig(
                Map.of(key, Map.of("see_opponent_hand", false)));
            System.out.println(key + " false -> opponentHand=" + config.hiddenInfo.opponentHand);
        }
    }
}
