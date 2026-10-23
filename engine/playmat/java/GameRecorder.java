import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import mage.cards.Card;
import mage.game.Game;
import mage.game.events.Listener;
import mage.game.events.TableEvent;
import mage.players.Player;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.LocalDate;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Records one Playmat game for mtg-ai, in the layout play/match.py writes, so play/review.py, play/summarize.py and
 * engine/encode.py read it unchanged:
 *
 *   <root>/<date>/<game id>/game0.jsonl   every recorded decision of every seat, in time order (merged at the end)
 *                          /games.jsonl   one line: winner, turns, first, lives, players, decks
 *                          /config.json   seats, deck files, Playmat and mtg-ai commits
 *                          /seat-A.jsonl  the seat's own decisions as they happened (B likewise)
 *                          /deck-A.dck    the seat's 40 cards at its first decision
 *                          /game_log.jsonl the game log every player sees (the table's INFO and STATUS messages)
 *
 * Seats are lettered in the order XMage seats them (A first). Our three seat classes register here from init(game):
 * ClaudeSeat (its decisions are written by the Python service), RecordedHuman and RecordedMad (written here).
 * Root: -Dmtgai.recordDir, default ~/mtg-data/playmat-games.
 */
public final class GameRecorder {

    static final Map<UUID, GameRecorder> GAMES = new ConcurrentHashMap<>();
    static final Gson GSON = new Gson();
    private static final Gson PRETTY = new GsonBuilder().setPrettyPrinting().create();

    final Game game;
    final Path dir;
    final int matchGame;  // always 0: each game of a match gets its own folder
    final Map<UUID, String> seatOf = new LinkedHashMap<>();
    final Map<String, JsonObject> seatInfo = new LinkedHashMap<>();
    final Map<String, Integer> nextIdx = new HashMap<>();
    final List<ClaudeSeat> claudeSeats = new ArrayList<>();
    private boolean decksWritten = false, ended = false;
    private final long started = System.currentTimeMillis();

    private GameRecorder(Game game, int matchGame) {
        this.game = game;
        this.matchGame = matchGame;
        String root = System.getProperty("mtgai.recordDir", System.getProperty("user.home") + "/mtg-data/playmat-games");
        this.dir = Paths.get(root, LocalDate.now().toString(), game.getId().toString());
        try {
            Files.createDirectories(dir);
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
        game.addTableEventListener(new LogListener(game.getId()));
    }

    /** The recorder of a real (non-simulated) game, created by the first seat that registers. */
    static synchronized GameRecorder of(Game game) {
        return GAMES.computeIfAbsent(game.getId(), id -> new GameRecorder(game, 0));
    }

    static GameRecorder find(Game game) {
        return game == null ? null : GAMES.get(game.getId());
    }

    /** Called from a seat's init(game), in seating order. kind: claude, human or xmage_ai. */
    synchronized String register(Player p, String kind, String className, int skill) {
        String seat = seatOf.get(p.getId());
        if (seat != null) return seat;
        seat = String.valueOf((char) ('A' + seatOf.size()));
        seatOf.put(p.getId(), seat);
        JsonObject info = new JsonObject();
        info.addProperty("name", p.getName());
        info.addProperty("kind", kind);
        info.addProperty("class", className);
        info.addProperty("skill", skill);
        info.addProperty("player_id", p.getId().toString());
        seatInfo.put(seat, info);
        writeConfig();
        return seat;
    }

    synchronized String seat(UUID playerId) {
        return seatOf.get(playerId);
    }

    Path deckFile(String seat) {
        return dir.resolve("deck-" + seat + ".dck");
    }

    /** Each seat's deck, written at the first decision of the game (all 40 cards are in library and hand then). */
    synchronized void ensureDecks() {
        if (decksWritten) return;
        decksWritten = true;
        for (Map.Entry<UUID, String> e : seatOf.entrySet()) {
            Player p = game.getPlayer(e.getKey());
            if (p == null) continue;
            Map<String, Integer> counts = new TreeMap<>();
            Map<String, String> setOf = new HashMap<>();
            List<Card> cards = new ArrayList<>(p.getLibrary().getCards(game));
            cards.addAll(p.getHand().getCards(game));
            for (Card c : cards) {
                counts.merge(c.getName(), 1, Integer::sum);
                setOf.putIfAbsent(c.getName(), c.getExpansionSetCode() + ":" + c.getCardNumber());
            }
            StringBuilder sb = new StringBuilder();
            for (Map.Entry<String, Integer> c : counts.entrySet())
                sb.append(c.getValue()).append(" [").append(setOf.get(c.getKey())).append("] ").append(c.getKey()).append('\n');
            try {
                Files.write(deckFile(e.getValue()), sb.toString().getBytes(StandardCharsets.UTF_8));
            } catch (IOException ex) {
                throw new UncheckedIOException(ex);
            }
        }
        writeConfig();
    }

    /** Appends one decision of a Java-recorded seat (human or XMage AI) to its seat file. */
    synchronized void writeDecision(UUID playerId, String player, JsonObject msg, int choice, JsonObject extra) {
        String seat = seatOf.get(playerId);
        if (seat == null || ended) return;
        JsonObject rec = new JsonObject();
        rec.addProperty("game", 0);
        rec.addProperty("seat", seat);
        rec.addProperty("player", player);
        int idx = nextIdx.merge(seat, 1, Integer::sum) - 1;
        rec.addProperty("idx", idx);
        rec.addProperty("kind", msg.get("kind").getAsString());
        rec.addProperty("prompt", msg.get("prompt").getAsString());
        rec.add("obs", msg.get("obs"));
        rec.add("options", msg.get("options"));
        rec.add("leaks", msg.get("leaks"));
        rec.addProperty("choice", choice);
        for (Map.Entry<String, com.google.gson.JsonElement> e : extra.entrySet()) rec.add(e.getKey(), e.getValue());
        rec.addProperty("ts", System.currentTimeMillis());
        append(dir.resolve("seat-" + seat + ".jsonl"), GSON.toJson(rec));
    }

    static void append(Path file, String line) {
        try (Writer w = Files.newBufferedWriter(file, StandardCharsets.UTF_8, StandardOpenOption.CREATE, StandardOpenOption.APPEND)) {
            w.write(line);
            w.write('\n');
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    private void writeConfig() {
        JsonObject c = new JsonObject();
        c.addProperty("source", "playmat");
        c.addProperty("game_id", game.getId().toString());
        c.addProperty("table_id", String.valueOf(game.getTableId()));
        c.addProperty("match_game", matchGame);
        c.addProperty("xmage", "1.4.62");
        c.addProperty("playmat_commit", System.getProperty("mtgai.playmatSha", "unknown"));
        c.addProperty("code_commit", System.getProperty("mtgai.codeSha", "unknown"));
        JsonObject seats = new JsonObject();
        for (Map.Entry<String, JsonObject> e : seatInfo.entrySet()) {
            seats.add(e.getKey(), e.getValue());
            c.addProperty("deck_" + e.getKey().toLowerCase(), deckFile(e.getKey()).toString());
            c.addProperty(e.getKey().toLowerCase(), playerName(e.getKey()));
        }
        c.add("seats", seats);
        c.addProperty("started_ms", started);
        try {
            Files.write(dir.resolve("config.json"), PRETTY.toJson(c).getBytes(StandardCharsets.UTF_8));
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    /** The "player" field the seat's records carry (a Claude seat's comes from Python; see ClaudeSeat). */
    String playerName(String seat) {
        JsonObject i = seatInfo.get(seat);
        if (i == null) return "?";
        switch (i.get("kind").getAsString()) {
            case "human": return "human:" + i.get("name").getAsString();
            case "xmage_ai": return "xmage_ai:mad:skill" + i.get("skill").getAsInt();
            default: return i.has("player") ? i.get("player").getAsString() : "claude";
        }
    }

    synchronized void setPlayerName(String seat, String name) {
        JsonObject i = seatInfo.get(seat);
        if (i != null && !name.equals(i.has("player") ? i.get("player").getAsString() : null)) {
            i.addProperty("player", name);
            writeConfig();
        }
    }

    /** Game over: result, merged decisions, Claude seats told. Called once, from END_GAME_INFO. */
    synchronized void end() {
        if (ended) return;
        ended = true;
        JsonObject g = new JsonObject();
        g.addProperty("game", 0);
        String winner = null;
        for (Map.Entry<UUID, String> e : seatOf.entrySet()) {
            Player p = game.getPlayer(e.getKey());
            if (p == null) continue;
            if (p.hasWon()) winner = e.getValue();
            g.addProperty("life_" + e.getValue().toLowerCase(), p.getLife());
        }
        g.addProperty("winner", winner);
        g.addProperty("draw", game.isADraw());
        g.addProperty("turns", game.getTurnNum());
        UUID firstId = game.getStartingPlayerId();
        String first = firstId == null ? null : seatOf.get(firstId);
        g.addProperty("first", first);
        g.addProperty("seconds", (System.currentTimeMillis() - started) / 1000.0);
        for (String seat : seatInfo.keySet()) {
            g.addProperty(seat.toLowerCase(), playerName(seat));
            g.addProperty("deck_" + seat.toLowerCase(), deckFile(seat).getFileName().toString());
        }
        g.addProperty("winner_text", game.getWinner());
        try {
            Files.write(dir.resolve("games.jsonl"), (GSON.toJson(g) + "\n").getBytes(StandardCharsets.UTF_8));
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
        for (ClaudeSeat c : claudeSeats) c.sendGameEnd(g);
        merge();
        writeConfig();
        GAMES.remove(game.getId());
    }

    /** game0.jsonl: every seat file merged by time (Claude's lines carry "ts" too). */
    void merge() {
        List<JsonObject> all = new ArrayList<>();
        for (String seat : seatInfo.keySet()) {
            Path f = dir.resolve("seat-" + seat + ".jsonl");
            if (!Files.exists(f)) continue;
            try {
                for (String line : Files.readAllLines(f, StandardCharsets.UTF_8))
                    if (!line.isBlank()) all.add(JsonParser.parseString(line).getAsJsonObject());
            } catch (IOException e) {
                throw new UncheckedIOException(e);
            }
        }
        all.sort(Comparator.comparingLong(o -> o.has("ts") ? o.get("ts").getAsLong() : 0L));
        StringBuilder sb = new StringBuilder();
        for (JsonObject o : all) sb.append(GSON.toJson(o)).append('\n');
        try {
            Files.write(dir.resolve("game0.jsonl"), sb.toString().getBytes(StandardCharsets.UTF_8));
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    /** The table's log messages (what every player's game log shows) and the end of the game. */
    static final class LogListener implements Listener<TableEvent> {
        private final UUID gameId;

        LogListener(UUID gameId) {
            this.gameId = gameId;
        }

        @Override
        public void event(TableEvent event) {
            GameRecorder r = GAMES.get(gameId);
            if (r == null) return;
            switch (event.getEventType()) {
                case INFO:
                case STATUS: {
                    JsonObject o = new JsonObject();
                    o.addProperty("ts", System.currentTimeMillis());
                    o.addProperty("type", event.getEventType().name());
                    o.addProperty("turn", r.game.getTurnNum());
                    o.addProperty("step", String.valueOf(r.game.getTurnStepType()));
                    String m = event.getMessage() == null ? "" : event.getMessage();
                    o.addProperty("text", m.replaceAll("<[^>]+>", ""));
                    o.addProperty("raw", m);
                    synchronized (r) {
                        append(r.dir.resolve("game_log.jsonl"), GSON.toJson(o));
                    }
                    break;
                }
                case END_GAME_INFO:
                    r.end();
                    break;
                default:
            }
        }
    }
}
