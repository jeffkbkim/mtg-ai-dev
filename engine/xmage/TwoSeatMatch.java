import com.google.gson.JsonObject;
import mage.cards.decks.Deck;
import mage.cards.decks.importer.DeckImporter;
import mage.cards.repository.CardScanner;
import mage.cards.repository.RepositoryUtil;
import mage.constants.*;
import mage.game.*;
import mage.game.match.*;
import mage.game.mulligan.MulliganType;
import mage.players.Player;
import java.net.Socket;
import java.util.*;

/**
 * N DSK games with both seats driven from Python: seat A and seat B each get their own socket, so each side
 * only ever receives its own seat's observation. Seat A starts the even games, seat B the odd ones.
 * After each game both sockets get {"type":"game_end", ...}; after the last, {"type":"end"}.
 */
public class TwoSeatMatch {
    public static void main(String[] args) throws Exception {
        int portA = Integer.parseInt(args[0]), portB = Integer.parseInt(args[1]);
        String deckA = args[2], deckB = args[3];
        int games = Integer.parseInt(args[4]);
        RepositoryUtil.bootstrapLocalDb();
        CardScanner.scan();
        PySeat.Link[] links = new PySeat.Link[2];
        Socket[] sockets = {new Socket("127.0.0.1", portA), new Socket("127.0.0.1", portB)};
        for (int s = 0; s < 2; s++) {
            sockets[s].setTcpNoDelay(true);
            links[s] = new PySeat.Link(sockets[s].getInputStream(), sockets[s].getOutputStream());
        }
        String[] names = {"A", "B"};
        for (int g = 0; g < games; g++) {
            Game game = new TwoPlayerDuel(MultiplayerAttackOption.LEFT, RangeOfInfluence.ONE,
                MulliganType.GAME_DEFAULT.getMulligan(0), 40, 20, 7);
            Match match = new TwoPlayerMatch(new MatchOptions("two seat match", "Two Player Duel", false));
            PySeat[] seats = {new PySeat("A", links[0]), new PySeat("B", links[1])};
            String[] decks = {deckA, deckB};
            for (int s = 0; s < 2; s++) {
                seats[s].setTestMode(true);
                Deck deck = Deck.load(DeckImporter.importDeckFromFile(decks[s], true), false, false);
                game.loadCards(deck.getCards(), seats[s].getId());
                game.addPlayer(seats[s], deck);
                match.addPlayer(seats[s], deck);
            }
            GameOptions options = new GameOptions();
            options.testMode = true;
            options.stopOnTurn = 100;
            options.stopAtStep = PhaseStep.END_TURN;
            game.setGameOptions(options);
            game.setStartingPlayerId(seats[g % 2].getId());
            long start = System.nanoTime();
            game.start(null);
            double secs = (System.nanoTime() - start) / 1e9;
            String winner = seats[0].hasWon() ? "A" : seats[1].hasWon() ? "B" : null;
            System.out.printf("RESULT game=%d first=%s winner=%s turns=%d seconds=%.3f life_a=%d life_b=%d%n",
                g, names[g % 2], winner, game.getTurnNum(), secs, seats[0].getLife(), seats[1].getLife());
            for (int s = 0; s < 2; s++) {
                JsonObject end = new JsonObject();
                end.addProperty("type", "game_end");
                end.addProperty("game", g);
                end.addProperty("first", names[g % 2]);
                end.addProperty("winner", winner);
                end.addProperty("turns", game.getTurnNum());
                end.addProperty("life_a", seats[0].getLife());
                end.addProperty("life_b", seats[1].getLife());
                links[s].out.println(links[s].gson.toJson(end));
            }
        }
        for (int s = 0; s < 2; s++) {
            PySeat.Link l = links[s];
            System.out.println("SEAT " + names[s] + " ASKED " + l.asked + " FORCED " + l.forced + " FALLBACK " + l.fallback);
            System.out.println("SEAT " + names[s] + " LEAKS " + l.leaks + " UNSEEN_REFS " + l.unseenRefs);
            System.out.println("SEAT " + names[s] + " UNMAPPED_ABILITIES " + l.unmappedAbilities + " UNMAPPED_CHOICES " + l.unmappedChoices);
            System.out.println("SEAT " + names[s] + " REJECTED " + l.rejected.size() + " " + l.rejected);
            l.out.println("{\"type\":\"end\"}");
            sockets[s].close();
        }
        System.exit(0);
    }
}
