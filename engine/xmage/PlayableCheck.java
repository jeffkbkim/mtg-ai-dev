import com.google.gson.*;
import mage.cards.Card;
import mage.constants.*;
import mage.game.*;
import mage.game.mulligan.MulliganType;
import mage.game.turn.Phase;
import mage.player.ai.ComputerPlayer7;
import java.io.*;
import java.util.*;

/**
 * Regression check: two copies of the same permanent must each offer their activated ability. XMage's
 * getPlayable(game, true) keeps one ability per rules text, so with two Glimmerlights on the battlefield only one
 * "Equip {1}" was offered, often the attached one (the reviewer saw the unattached Glimmerlight never get equipped in
 * two batch-2 games). Copies in hand were already listed one option each and must stay so. Board in our precombat
 * main: 2 Glimmerlight, Bashful Beastie, 2 Plains; hand: 2 Jump Scare, 2 Plains. Prints PASS or FAIL and exits 1 on
 * FAIL.
 */
public class PlayableCheck {
    public static void main(String[] args) throws Exception {
        mage.cards.repository.RepositoryUtil.bootstrapLocalDb();
        mage.cards.repository.CardScanner.scan();
        PipedInputStream seatIn = new PipedInputStream(), fromSeat = new PipedInputStream();
        PrintWriter toSeat = new PrintWriter(new PipedOutputStream(seatIn), true);
        PySeat.Link link = new PySeat.Link(seatIn, new PipedOutputStream(fromSeat));
        List<String> labels = Collections.synchronizedList(new ArrayList<>());
        Thread python = new Thread(() -> {  // records the priority options and passes
            try (BufferedReader r = new BufferedReader(new InputStreamReader(fromSeat))) {
                for (String line; (line = r.readLine()) != null; ) {
                    for (JsonElement o : JsonParser.parseString(line).getAsJsonObject().getAsJsonArray("options"))
                        labels.add(o.getAsJsonObject().get("label").getAsString());
                    toSeat.println("{\"choice\":0}");
                }
            } catch (IOException ignored) { }
        });
        python.setDaemon(true);
        python.start();

        Game game = new TwoPlayerDuel(MultiplayerAttackOption.LEFT, RangeOfInfluence.ONE, MulliganType.GAME_DEFAULT.getMulligan(0), 40, 20, 7);
        game.setGameOptions(new GameOptions());
        PySeat py = new PySeat("PY", link);
        ComputerPlayer7 ai = new ComputerPlayer7("AI", RangeOfInfluence.ONE, 2);
        mage.game.match.Match match = new TwoPlayerMatch(new mage.game.match.MatchOptions("playable check", "Two Player Duel", false));
        for (mage.players.Player p : new mage.players.Player[]{py, ai}) {
            p.setTestMode(true);
            mage.cards.decks.Deck deck = new mage.cards.decks.Deck();
            game.addPlayer(p, deck);
            match.addPlayer(p, deck);
        }
        for (String n : new String[]{"Glimmerlight", "Glimmerlight", "Bashful Beastie", "Plains", "Plains"})
            ManaCheck.put(game, n, py.getId());
        ManaCheck.put(game, "Bashful Beastie", ai.getId());  // a target for Jump Scare
        for (String n : new String[]{"Jump Scare", "Jump Scare", "Plains", "Plains"}) {
            Card c = ManaCheck.make(game, n, py.getId());
            py.getHand().add(c);
            game.getState().setZone(c.getId(), Zone.HAND);
        }
        for (mage.players.Player p : new mage.players.Player[]{py, ai}) p.beginTurn(game);
        game.getState().setActivePlayerId(py.getId());
        Phase main = game.getState().getTurn().getPhase(TurnPhase.PRECOMBAT_MAIN);
        main.setStep(new mage.game.turn.PreCombatMainStep());
        game.getState().getTurn().setPhase(main);
        game.applyEffects();
        py.priority(game);
        Thread.sleep(300);
        long equips = labels.stream().filter(l -> l.contains("Equip")).count();
        long spells = labels.stream().filter(l -> l.contains("Jump Scare")).count();
        long lands = labels.stream().filter(l -> l.startsWith("Play land")).count();
        System.out.println("options " + labels);
        System.out.println("Equip options " + equips + " (want 2), Jump Scare " + spells + ", land plays " + lands + "");
        boolean ok = equips == 2 && spells == 2 && lands == 2;
        System.out.println(ok ? "PASS" : "FAIL");
        System.exit(ok ? 0 : 1);
    }
}
