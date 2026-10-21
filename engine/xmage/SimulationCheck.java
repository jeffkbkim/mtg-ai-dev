import mage.constants.*;
import mage.game.*;
import mage.game.mulligan.MulliganType;
import mage.player.ai.ComputerPlayer7;
import mage.players.Player;
import java.io.*;
import java.util.*;

/**
 * Regression check: XMage's AI plays out candidate moves on copies of the game (createSimulationForAI), and each
 * copy holds a copy of our seat that shares the live link to Python. A question asked inside such a copy must be
 * answered in Java, never sent to Python. The soak saw our seat asked about boards that never happened (run 67:
 * a Screaming Nemesis damage trigger during the AI's declare-blockers lookahead).
 * Prints PASS or FAIL and exits 1 on FAIL.
 */
public class SimulationCheck {
    public static void main(String[] args) throws Exception {
        mage.cards.repository.RepositoryUtil.bootstrapLocalDb();
        mage.cards.repository.CardScanner.scan();
        PipedInputStream seatIn = new PipedInputStream(), fromSeat = new PipedInputStream();
        PrintWriter toSeat = new PrintWriter(new PipedOutputStream(seatIn), true);
        PySeat.Link link = new PySeat.Link(seatIn, new PipedOutputStream(fromSeat));
        List<String> asked = Collections.synchronizedList(new ArrayList<>());
        Thread python = new Thread(() -> {
            try (BufferedReader r = new BufferedReader(new InputStreamReader(fromSeat))) {
                for (String line; (line = r.readLine()) != null; ) { asked.add(line.length() > 120 ? line.substring(0, 120) : line); toSeat.println("{\"choice\":0}"); }
            } catch (IOException ignored) { }
        });
        python.setDaemon(true);
        python.start();

        Game game = new TwoPlayerDuel(MultiplayerAttackOption.LEFT, RangeOfInfluence.ONE, MulliganType.GAME_DEFAULT.getMulligan(0), 40, 20, 7);
        game.setGameOptions(new GameOptions());
        mage.game.match.Match match = new TwoPlayerMatch(new mage.game.match.MatchOptions("simulation check", "Two Player Duel", false));
        PySeat py = new PySeat("PY", link);
        ComputerPlayer7 ai = new ComputerPlayer7("AI", RangeOfInfluence.ONE, 2);
        for (Player p : new Player[]{py, ai}) {
            p.setTestMode(true);
            mage.cards.decks.Deck deck = new mage.cards.decks.Deck();
            game.addPlayer(p, deck);
            match.addPlayer(p, deck);
        }
        for (Player p : new Player[]{py, ai}) p.beginTurn(game);

        // the same question, once in the real game and once in an AI simulation copy
        py.chooseUse(Outcome.Benefit, "real question", null, "Yes", "No", null, game);
        Game sim = game.createSimulationForAI();
        Player simSeat = sim.getPlayer(py.getId());
        simSeat.chooseUse(Outcome.Benefit, "simulated question", null, "Yes", "No", null, sim);
        Thread.sleep(500);

        boolean real = asked.stream().anyMatch(a -> a.contains("real question"));
        boolean simulated = asked.stream().anyMatch(a -> a.contains("simulated question"));
        System.out.println("seat copy in simulation is a PySeat: " + (simSeat instanceof PySeat) + "; sent to Python: real " + real + ", simulated " + simulated);
        boolean ok = real && !simulated;
        System.out.println(ok ? "PASS" : "FAIL");
        System.exit(ok ? 0 : 1);
    }
}
