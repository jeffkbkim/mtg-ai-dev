import com.google.gson.Gson;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import mage.cards.decks.Deck;
import mage.cards.decks.importer.DeckImporter;
import mage.cards.repository.CardScanner;
import mage.cards.repository.RepositoryUtil;
import mage.constants.*;
import mage.game.*;
import mage.game.match.*;
import mage.game.mulligan.MulliganType;
import java.net.Socket;
import java.nio.file.*;
import java.util.*;

/**
 * Replays recorded games: both seats are ReplaySeats on one socket, so one Python script answers both sides.
 *
 *   java ... ReplayMatch <port> <games.jsonl>
 *
 * Each line of games.jsonl: {"id": ..., "deck_a": path, "deck_b": path, "first": "A"|"B",
 *   "draws_a": [names A draws first, in order: its opening hands, then ...], "draws_b": [...],
 *   "reset_on_shuffle": ["B"]}   (seats whose draw queue starts over when a mulligan shuffles the hand back)
 * After each game: {"type":"game_end", "id", "state": true state, ...}; after the last, {"type":"end"}.
 */
public class ReplayMatch {
    public static void main(String[] args) throws Exception {
        int port = Integer.parseInt(args[0]);
        List<String> lines = Files.readAllLines(Path.of(args[1]));
        RepositoryUtil.bootstrapLocalDb();
        CardScanner.scan();
        Socket socket = new Socket("127.0.0.1", port);
        socket.setTcpNoDelay(true);
        PySeat.Link link = new PySeat.Link(socket.getInputStream(), socket.getOutputStream());
        Gson gson = new Gson();
        for (String line : lines) {
            if (line.isBlank()) continue;
            JsonObject spec = gson.fromJson(line, JsonObject.class);
            Game game = new TwoPlayerDuel(MultiplayerAttackOption.LEFT, RangeOfInfluence.ONE,
                    MulliganType.GAME_DEFAULT.getMulligan(0), 40, 20, 7);
            Match match = new TwoPlayerMatch(new MatchOptions("replay", "Two Player Duel", false));
            ReplaySeat.Shared shared = new ReplaySeat.Shared();
            shared.seed = spec.has("seed") ? spec.get("seed").getAsLong() : spec.get("id").getAsString().hashCode();
            mage.util.RandomUtil.setSeed(shared.seed);
            ReplaySeat[] seats = {new ReplaySeat("A", link, shared), new ReplaySeat("B", link, shared)};
            shared.queue.put("A", names(spec, "draws_a"));
            shared.queue.put("B", names(spec, "draws_b"));
            if (spec.has("reset_on_shuffle")) for (JsonElement e : spec.getAsJsonArray("reset_on_shuffle")) shared.resetOnShuffle.add(e.getAsString());
            String[] decks = {spec.get("deck_a").getAsString(), spec.get("deck_b").getAsString()};
            for (int s = 0; s < 2; s++) {
                seats[s].setTestMode(true);
                seats[s].setFastFailInTestMode(false);
                Deck deck = Deck.load(DeckImporter.importDeckFromFile(decks[s], true), false, false);
                game.loadCards(deck.getCards(), seats[s].getId());
                game.addPlayer(seats[s], deck);
                match.addPlayer(seats[s], deck);
            }
            GameOptions options = new GameOptions();
            options.testMode = false;
            options.stopOnTurn = 70;
            options.stopAtStep = PhaseStep.END_TURN;
            options.rollbackTurnsAllowed = true;
            game.setGameOptions(options);
            game.setStartingPlayerId(seats["A".equals(spec.get("first").getAsString()) ? 0 : 1].getId());
            String error = null;
            long start = System.nanoTime();
            try {
                game.start(null);
            } catch (RuntimeException e) {
                error = e.toString();
                e.printStackTrace();
            }
            JsonObject end = new JsonObject();
            end.addProperty("type", "game_end");
            end.add("id", spec.get("id"));
            end.addProperty("turn", game.getTurnNum());
            end.addProperty("winner", seats[0].hasWon() ? "A" : seats[1].hasWon() ? "B" : null);
            end.addProperty("rollbacks", shared.rollbacks);
            end.addProperty("seconds", (System.nanoTime() - start) / 1e9);
            if (error != null) end.addProperty("error", error);
            end.add("state", ReplaySeat.dump(game));
            link.out.println(gson.toJson(end));
            link.in.readLine();  // Python acknowledges before the next game
        }
        System.out.println("REJECTED " + link.rejected.size() + " LEAKS " + link.leaks + " SIMULATED " + link.simulated);
        link.out.println("{\"type\":\"end\"}");
        socket.close();
        System.exit(0);
    }

    private static List<String> names(JsonObject spec, String key) {
        List<String> out = new ArrayList<>();
        if (spec.has(key)) for (JsonElement n : spec.getAsJsonArray(key)) out.add(n.getAsString());
        return out;
    }
}
