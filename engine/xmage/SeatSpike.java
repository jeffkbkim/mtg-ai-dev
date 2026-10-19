import mage.cards.decks.Deck;
import mage.cards.decks.importer.DeckImporter;
import mage.cards.repository.CardScanner;
import mage.cards.repository.RepositoryUtil;
import mage.constants.*;
import mage.game.*;
import mage.game.match.*;
import mage.game.mulligan.MulliganType;
import mage.player.ai.ComputerPlayer7;
import mage.players.Player;
import java.net.Socket;
import java.util.*;

/** Spike: one DSK game, PySeat (decisions from Python over a socket) vs XMage's ComputerPlayer7. */
public class SeatSpike {
    public static void main(String[] args) throws Exception {
        int port = Integer.parseInt(args[0]);
        String pyDeck = args[1], aiDeck = args[2];
        int games = args.length > 3 ? Integer.parseInt(args[3]) : 1;
        long boot = System.nanoTime();
        RepositoryUtil.bootstrapLocalDb();
        CardScanner.scan();
        System.out.printf("BOOT_SECONDS %.3f%n", (System.nanoTime()-boot)/1e9);
        Socket socket = new Socket("127.0.0.1", port);
        socket.setTcpNoDelay(true);
        PySeat.Link link = new PySeat.Link(socket.getInputStream(), socket.getOutputStream());
        for (int g = 0; g < games; g++) {
            Game game = new TwoPlayerDuel(MultiplayerAttackOption.LEFT, RangeOfInfluence.ONE,
                MulliganType.GAME_DEFAULT.getMulligan(0), 40, 20, 7);
            Match match = new TwoPlayerMatch(new MatchOptions("seat spike", "Two Player Duel", false));
            PySeat py = new PySeat("PY", link);
            ComputerPlayer7 ai = new ComputerPlayer7("AI", RangeOfInfluence.ONE, 2);
            ai.setMaxThinkTimeSecs(1);
            Player[] seats = {py, ai};
            String[] decks = {pyDeck, aiDeck};
            for (int s = 0; s < 2; s++) {
                seats[s].setTestMode(true);
                Deck deck = Deck.load(DeckImporter.importDeckFromFile(decks[s], true), false, false);
                game.loadCards(deck.getCards(), seats[s].getId());
                game.addPlayer(seats[s], deck);
                match.addPlayer(seats[s], deck);
            }
            GameOptions options = new GameOptions();
            options.testMode = false; // true skips the opening hands (every game started with 0 cards)
            options.stopOnTurn = 100;
            options.stopAtStep = PhaseStep.END_TURN;
            game.setGameOptions(options);
            game.setStartingPlayerId(g % 2 == 0 ? py.getId() : ai.getId());
            long start = System.nanoTime();
            game.start(null);
            double secs = (System.nanoTime()-start)/1e9;
            boolean terminal = py.hasWon() || ai.hasWon() || (py.hasLost() && ai.hasLost());
            System.out.printf("RESULT game=%d first=%s terminal=%s winner=%s turns=%d seconds=%.3f life_py=%d life_ai=%d%n",
                g, g % 2 == 0 ? "PY" : "AI", terminal, game.getWinner(), game.getTurnNum(), secs, py.getLife(), ai.getLife());
        }
        System.out.println("ASKED " + link.asked);
        System.out.println("FORCED " + link.forced);
        System.out.println("LEAKS " + link.leaks);
        System.out.println("UNSEEN_REFS " + link.unseenRefs);
        System.out.println("UNMAPPED_ABILITIES " + link.unmappedAbilities);
        System.out.println("UNMAPPED_CHOICES " + link.unmappedChoices);
        System.out.println("GRANTED_ON_BOARD " + link.grantedOnBoard);
        System.out.println("UNKEYED_ON_BOARD " + link.unkeyedOnBoard);
        System.out.printf("OBSERVE mean_ms=%.3f mean_bytes=%d%n", link.roundTrips == 0 ? 0 : link.observeNanos / 1e6 / link.roundTrips, link.roundTrips == 0 ? 0 : link.bytes / link.roundTrips);
        System.out.println("FALLBACK " + link.fallback);
        System.out.println("REJECTED " + link.rejected.size() + " " + link.rejected);
        System.out.printf("ROUND_TRIPS %d mean_ms=%.3f%n", link.roundTrips, link.roundTrips == 0 ? 0 : link.roundTripNanos / 1e6 / link.roundTrips);
        link.out.println("{\"type\":\"end\"}");
        socket.close();
        System.exit(0);
    }
}
