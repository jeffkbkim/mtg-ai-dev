import mage.abilities.SpellAbility;
import mage.abilities.costs.mana.ManaCost;
import mage.abilities.costs.mana.ManaCostsImpl;
import mage.cards.Card;
import mage.cards.repository.*;
import mage.constants.*;
import mage.game.*;
import mage.game.mulligan.MulliganType;
import mage.game.permanent.Permanent;
import mage.game.permanent.PermanentCard;
import mage.player.ai.ComputerPlayer7;
import com.google.gson.*;
import java.io.*;
import java.util.*;

/**
 * Regression check for automatic mana payment: our seat must not tap a creature for mana while lands can pay.
 * XMage's ComputerPlayer scores each mana source and taps the lowest first; a dual land (two mana abilities) ties with
 * a creature that Enduring Vitality lets tap for any colour, and ties break in hash order, so the reviewer saw an
 * Insect token tapped for an equip cost while Strangled Cemetery stayed untapped (and the creature then couldn't
 * block). Each trial builds a fresh board (Enduring Vitality, 3 Bashful Beastie, 2 Strangled Cemetery, 2 Forest) and
 * pays {4}, which the lands cover; then pays {6}, which needs two creatures.
 * Overgrown Zealot: its "{T}: Add one mana of any color" must be usable for a spell. Its other ability makes two mana
 * that can only turn permanents face up; XMage's payer tries the bigger ability first, and casts paid with Zealot
 * were rolled back (seen by the reviewer in five games). Board: Zealot and two Swamps, paying {2}{G}.
 * Colours in hand: paying {1}{G} from Island + 3 Forest while holding Don't Make a Sound ({1}{U}) must leave the
 * Island untapped (the reviewer saw the payer strand the only blue source in four games). Two boards from batch 2
 * games, where a colour-demand count still chose badly: {2}{W} from 3 Plains + 2 Mountain holding Jump Scare ({W}),
 * Irreverent Gremlin ({1}{R}) and Vengeful Possession ({2}{R}) must leave a Plains and a Mountain; {4}{G} from
 * 4 Forest + 3 Island holding House Cartographer ({1}{G}) and two {3}{U} instants must leave a Forest.
 * Prints PASS or FAIL and exits 1 on FAIL.
 */
public class ManaCheck {
    public static Card make(Game game, String name, UUID owner) {
        Card c = CardRepository.instance.findCards(new CardCriteria().setCodes("DSK").name(name)).get(0).createCard();
        game.loadCards(new HashSet<>(Collections.singletonList(c)), owner);
        return c;
    }

    public static Permanent put(Game game, String name, UUID owner) {
        Card c = make(game, name, owner);
        PermanentCard perm = new PermanentCard(c, owner, game);
        game.addPermanent(perm, 0);
        game.getState().setZone(c.getId(), Zone.BATTLEFIELD);
        perm.removeSummoningSickness();
        return perm;
    }

    static final List<String> asked = Collections.synchronizedList(new ArrayList<>());

    /** A link whose Python side picks a "Green" option when there is one, else the first option. */
    public static PySeat.Link link() throws IOException {
        PipedInputStream seatIn = new PipedInputStream(), fromSeat = new PipedInputStream();
        PrintWriter toSeat = new PrintWriter(new PipedOutputStream(seatIn), true);
        PySeat.Link link = new PySeat.Link(seatIn, new PipedOutputStream(fromSeat));
        Thread python = new Thread(() -> {
            try (BufferedReader r = new BufferedReader(new InputStreamReader(fromSeat))) {
                for (String line; (line = r.readLine()) != null; ) {
                    JsonObject m = JsonParser.parseString(line).getAsJsonObject();
                    asked.add(m.get("kind").getAsString() + ": " + m.get("prompt").getAsString());
                    JsonArray opts = m.getAsJsonArray("options");
                    int pick = 0;
                    for (int i = 0; i < opts.size(); i++)
                        if (opts.get(i).getAsJsonObject().get("label").getAsString().contains("Green")) pick = i;
                    toSeat.println("{\"choice\":" + pick + "}");
                }
            } catch (IOException ignored) { }
        });
        python.setDaemon(true);
        python.start();
        return link;
    }

    static String[] hand = {};
    static List<String> untapped = new ArrayList<>();  // land names left untapped by the last trial

    /** [creatures tapped, lands left untapped, paid?, Islands left untapped] after paying cost on a fresh board. */
    static int[] trial(String cost, String... cards) throws IOException {
        PySeat.Link link = link();
        Game game = new TwoPlayerDuel(MultiplayerAttackOption.LEFT, RangeOfInfluence.ONE, MulliganType.GAME_DEFAULT.getMulligan(0), 40, 20, 7);
        PySeat py = new PySeat("PY", link);
        ComputerPlayer7 ai = new ComputerPlayer7("AI", RangeOfInfluence.ONE, 2);
        mage.game.match.Match match = new TwoPlayerMatch(new mage.game.match.MatchOptions("mana check", "Two Player Duel", false));
        for (mage.players.Player p : new mage.players.Player[]{py, ai}) {
            p.setTestMode(true);
            mage.cards.decks.Deck deck = new mage.cards.decks.Deck();
            game.addPlayer(p, deck);
            match.addPlayer(p, deck);
        }
        List<Permanent> board = new ArrayList<>();
        for (String n : cards) board.add(put(game, n, py.getId()));
        for (String n : hand) { Card c = make(game, n, py.getId()); py.getHand().add(c); game.getState().setZone(c.getId(), Zone.HAND); }
        for (mage.players.Player p : new mage.players.Player[]{py, ai}) p.beginTurn(game);
        game.getState().setActivePlayerId(py.getId());
        game.applyEffects();
        Card spell = make(game, "Murder", py.getId());  // any spell of ours to pay for
        SpellAbility sa = spell.getSpellAbility();
        sa.setControllerId(py.getId());
        boolean paid = new ManaCostsImpl<ManaCost>(cost).pay(sa, game, sa, py.getId(), false, null);
        int creaturesTapped = 0, landsUntapped = 0, islandsUntapped = 0;
        untapped = new ArrayList<>();
        for (Permanent p : board) {
            if (p.isLand(game) && !p.isTapped()) untapped.add(p.getName());
            if (p.isCreature(game) && p.isTapped()) creaturesTapped++;
            if (p.isLand(game) && !p.isTapped()) landsUntapped++;
            if (p.getName().equals("Island") && !p.isTapped()) islandsUntapped++;
        }
        return new int[]{creaturesTapped, landsUntapped, paid ? 1 : 0, islandsUntapped};
    }

    public static void main(String[] args) throws Exception {
        RepositoryUtil.bootstrapLocalDb();
        CardScanner.scan();
        String[] vitality = {"Enduring Vitality", "Bashful Beastie", "Bashful Beastie", "Bashful Beastie",
                "Strangled Cemetery", "Strangled Cemetery", "Forest", "Forest"};
        int trials = 20, badFour = 0, unpaid = 0, badSix = 0, zealotUnpaid = 0, islandSpent = 0, badKeep = 0;
        for (int t = 0; t < trials; t++) {
            int[] r = trial("{4}", vitality);
            if (r[2] == 0) unpaid++;
            else if (r[0] > 0) badFour++;
            int[] s = trial("{6}", vitality);
            if (s[2] == 0) unpaid++;
            else if (s[0] != 2 || s[1] != 0) badSix++;
            if (trial("{2}{G}", "Overgrown Zealot", "Swamp", "Swamp")[2] == 0) zealotUnpaid++;
            hand = new String[]{"Don't Make a Sound"};
            int[] k = trial("{1}{G}", "Island", "Forest", "Forest", "Forest");
            hand = new String[]{};
            if (k[2] == 0 || k[3] == 0) islandSpent++;
            hand = new String[]{"Jump Scare", "Irreverent Gremlin", "Vengeful Possession"};
            int[] w = trial("{2}{W}", "Plains", "Plains", "Plains", "Mountain", "Mountain");
            if (w[2] == 0 || !untapped.contains("Plains") || !untapped.contains("Mountain")) badKeep++;
            hand = new String[]{"House Cartographer", "Vanish from Sight", "Glimmerburst"};
            int[] g = trial("{4}{G}", "Forest", "Forest", "Forest", "Forest", "Island", "Island", "Island");
            if (g[2] == 0 || !untapped.contains("Forest")) badKeep++;
            hand = new String[]{};
        }
        System.out.println("{4} with 4 lands: a creature was tapped in " + badFour + "/" + trials + " trials");
        System.out.println("{6} with 4 lands: not exactly 4 lands + 2 creatures in " + badSix + "/" + trials + " trials; unpaid " + unpaid);
        System.out.println("{2}{G} with Overgrown Zealot + 2 Swamps: unpaid in " + zealotUnpaid + "/" + trials + " trials");
        System.out.println("{1}{G} from Island + 3 Forest holding a blue instant: Island spent (or unpaid) in " + islandSpent + "/" + trials + " trials");
        System.out.println("batch-2 boards: the colour a card in hand needs was spent in " + badKeep + "/" + (2 * trials) + " trials");
        System.out.println("asked Python: " + new TreeSet<>(asked));
        boolean ok = badFour == 0 && badSix == 0 && unpaid == 0 && zealotUnpaid == 0 && islandSpent == 0 && badKeep == 0;
        System.out.println(ok ? "PASS" : "FAIL");
        System.exit(ok ? 0 : 1);
    }
}
