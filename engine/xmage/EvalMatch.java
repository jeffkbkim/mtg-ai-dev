import com.google.gson.JsonObject;
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
import java.nio.file.*;
import java.util.*;

/**
 * Evaluation games from a schedule (play/eval_games.py writes it). Seat A is the player being evaluated, always driven
 * from Python over its own socket. Seat B is the opponent: either Python too (a port), or XMage's own AI ("ai").
 *
 *   EvalMatch <schedule.tsv> <port A> <port B | ai> [ai skill, default 2] [ai think seconds, default 1]
 *
 * Each schedule line is one game: deck_a TAB deck_b TAB first (A or B = who is on the play). The schedule decides
 * seat balance (which deck each side plays, who starts), so this class just plays it in order. After each game the
 * Python sockets get {"type":"game_end", ...}; after the last, {"type":"end"}.
 */
public class EvalMatch {
    public static void main(String[] args) throws Exception {
        List<String[]> schedule = new ArrayList<>();
        for (String line : Files.readAllLines(Paths.get(args[0]))) {
            if (!line.isBlank()) schedule.add(line.split("\t"));
        }
        boolean aiOpponent = args[2].equals("ai");
        int skill = args.length > 3 ? Integer.parseInt(args[3]) : 2;
        int thinkSecs = args.length > 4 ? Integer.parseInt(args[4]) : 1;
        RepositoryUtil.bootstrapLocalDb();
        CardScanner.scan();
        int seatsOnSockets = aiOpponent ? 1 : 2;
        PySeat.Link[] links = new PySeat.Link[seatsOnSockets];
        Socket[] sockets = new Socket[seatsOnSockets];
        for (int s = 0; s < seatsOnSockets; s++) {
            sockets[s] = new Socket("127.0.0.1", Integer.parseInt(args[1 + s]));
            sockets[s].setTcpNoDelay(true);
            links[s] = new PySeat.Link(sockets[s].getInputStream(), sockets[s].getOutputStream());
        }
        String[] names = {"A", "B"};
        for (int g = 0; g < schedule.size(); g++) {
            String[] row = schedule.get(g);
            String[] decks = {row[0], row[1]};
            int first = row[2].trim().equals("A") ? 0 : 1;
            Game game = new TwoPlayerDuel(MultiplayerAttackOption.LEFT, RangeOfInfluence.ONE,
                MulliganType.GAME_DEFAULT.getMulligan(0), 40, 20, 7);
            Match match = new TwoPlayerMatch(new MatchOptions("eval match", "Two Player Duel", false));
            Player[] seats = new Player[2];
            seats[0] = new PySeat("A", links[0]);
            if (aiOpponent) {
                ComputerPlayer7 ai = new ComputerPlayer7("B", RangeOfInfluence.ONE, skill);
                ai.setMaxThinkTimeSecs(thinkSecs);
                seats[1] = ai;
            } else {
                seats[1] = new PySeat("B", links[1]);
            }
            for (int s = 0; s < 2; s++) {
                seats[s].setTestMode(true);
                // as in TwoSeatMatch: a real XMage server logs some AI warnings and carries on, test mode would end
                // the whole match ("AI can't find good blocker combination")
                seats[s].setFastFailInTestMode(false);
                Deck deck = Deck.load(DeckImporter.importDeckFromFile(decks[s], true), false, false);
                game.loadCards(deck.getCards(), seats[s].getId());
                game.addPlayer(seats[s], deck);
                match.addPlayer(seats[s], deck);
            }
            GameOptions options = new GameOptions();
            options.testMode = false; // true skips the opening hands
            options.stopOnTurn = 100;
            options.stopAtStep = PhaseStep.END_TURN;
            game.setGameOptions(options);
            game.setStartingPlayerId(seats[first].getId());
            long start = System.nanoTime();
            String error = null;
            try {
                game.start(null);
            } catch (Exception e) {
                // one broken game must not end the run; it is reported as an error, not as a result
                error = e.getClass().getSimpleName() + ": " + e.getMessage();
                e.printStackTrace(System.out);
            }
            double secs = (System.nanoTime() - start) / 1e9;
            Observer.forget(game);
            String winner = seats[0].hasWon() ? "A" : seats[1].hasWon() ? "B" : null;
            System.out.printf("RESULT game=%d first=%s winner=%s turns=%d seconds=%.3f life_a=%d life_b=%d error=%s%n",
                g, names[first], winner, game.getTurnNum(), secs, seats[0].getLife(), seats[1].getLife(), error);
            for (int s = 0; s < seatsOnSockets; s++) {
                JsonObject end = new JsonObject();
                end.addProperty("type", "game_end");
                end.addProperty("game", g);
                end.addProperty("first", names[first]);
                end.addProperty("winner", winner);
                end.addProperty("turns", game.getTurnNum());
                end.addProperty("seconds", Math.round(secs * 1000) / 1000.0);
                end.addProperty("life_a", seats[0].getLife());
                end.addProperty("life_b", seats[1].getLife());
                end.addProperty("deck_a", Paths.get(decks[0]).getFileName().toString());
                end.addProperty("deck_b", Paths.get(decks[1]).getFileName().toString());
                if (error != null) end.addProperty("error", error);
                links[s].out.println(links[s].gson.toJson(end));
            }
        }
        for (int s = 0; s < seatsOnSockets; s++) {
            PySeat.Link l = links[s];
            System.out.println("SEAT " + names[s] + " ASKED " + l.asked + " FORCED " + l.forced + " FALLBACK " + l.fallback + " SIMULATED " + l.simulated);
            System.out.println("SEAT " + names[s] + " LEAKS " + l.leaks + " UNSEEN_REFS " + l.unseenRefs);
            System.out.println("SEAT " + names[s] + " UNMAPPED_ABILITIES " + l.unmappedAbilities + " UNMAPPED_CHOICES " + l.unmappedChoices);
            System.out.println("SEAT " + names[s] + " REJECTED " + l.rejected.size() + " " + l.rejected);
            l.out.println("{\"type\":\"end\"}");
            sockets[s].close();
        }
        System.exit(0);
    }
}
