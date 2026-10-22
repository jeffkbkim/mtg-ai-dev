import mage.abilities.Ability;
import mage.cards.Card;
import mage.cards.repository.*;
import mage.constants.*;
import mage.game.*;
import mage.game.mulligan.MulliganType;
import mage.game.permanent.Permanent;
import mage.game.permanent.PermanentCard;
import mage.player.ai.ComputerPlayer7;
import mage.players.Player;
import java.util.*;

/**
 * Regression check for abilities the coverage soak found with no stable key:
 * - Marvin, Murderous Mimic borrows the activated abilities of other creatures you control; each should get the
 *   lending card's key (Tyvar, the Pummeler's, and Niko's activated ability, which Marvin borrows too).
 * - Niko, Light of Hope's Shard tokens; their "{2}, sacrifice" ability should get Niko's "#g" key.
 * Builds the board directly. Prints every key and PASS, or FAIL and exits 1.
 */
public class KeyCheck {
    static PermanentCard put(Game game, String name, Player owner) {
        Card c = CardRepository.instance.findCards(new CardCriteria().setCodes("DSK").name(name)).get(0).createCard();
        game.loadCards(new HashSet<>(Collections.singletonList(c)), owner.getId());
        PermanentCard p = new PermanentCard(c, owner.getId(), game);
        game.addPermanent(p, 0);
        game.getState().setZone(c.getId(), Zone.BATTLEFIELD);
        return p;
    }

    public static void main(String[] args) throws Exception {
        RepositoryUtil.bootstrapLocalDb();
        CardScanner.scan();
        Game game = new TwoPlayerDuel(MultiplayerAttackOption.LEFT, RangeOfInfluence.ONE, MulliganType.GAME_DEFAULT.getMulligan(0), 40, 20, 7);
        game.setGameOptions(new GameOptions());
        mage.game.match.Match match = new TwoPlayerMatch(new mage.game.match.MatchOptions("key check", "Two Player Duel", false));
        ComputerPlayer7 us = new ComputerPlayer7("US", RangeOfInfluence.ONE, 2), them = new ComputerPlayer7("THEM", RangeOfInfluence.ONE, 2);
        for (Player p : new Player[]{us, them}) {
            p.setTestMode(true);
            mage.cards.decks.Deck deck = new mage.cards.decks.Deck();
            game.addPlayer(p, deck);
            match.addPlayer(p, deck);
        }
        PermanentCard marvin = put(game, "Marvin, Murderous Mimic", us);
        put(game, "Tyvar, the Pummeler", us);
        PermanentCard niko = put(game, "Niko, Light of Hope", us);
        for (Player p : new Player[]{us, them}) p.beginTurn(game);
        Ability etb = niko.getAbilities().stream().filter(a -> a instanceof mage.abilities.TriggeredAbility).findFirst().get();
        etb.setControllerId(us.getId());
        etb.setSourceId(niko.getId());
        etb.getEffects().get(0).apply(game, etb);  // create two Shard tokens
        game.applyEffects();                       // Marvin picks up Tyvar's abilities

        boolean ok = true;
        List<String> marvinKeys = new ArrayList<>(), shardKeys = new ArrayList<>();
        for (Permanent p : game.getBattlefield().getAllActivePermanents(us.getId())) {
            for (Ability a : p.getAbilities(game)) {
                if (!AbilityKeys.keyed(a)) continue;
                String key = AbilityKeys.key(game, a);
                System.out.println(p.getName() + ": " + AbilityKeys.text(a) + " -> " + key);
                if (p.getId().equals(marvin.getId())) marvinKeys.add(String.valueOf(key));
                if (p.getName().startsWith("Shard")) shardKeys.add(String.valueOf(key));
            }
        }
        if (marvinKeys.size() < 2 || !marvinKeys.stream().allMatch(k -> k.startsWith("Tyvar, the Pummeler#") || k.equals("Niko, Light of Hope#1"))) { System.out.println("FAIL Marvin's borrowed abilities: " + marvinKeys); ok = false; }
        if (shardKeys.isEmpty() || !shardKeys.stream().allMatch(k -> k.startsWith("Niko, Light of Hope#g"))) { System.out.println("FAIL Shard token abilities: " + shardKeys); ok = false; }
        System.out.println(ok ? "PASS" : "FAILED");
        System.exit(ok ? 0 : 1);
    }
}
