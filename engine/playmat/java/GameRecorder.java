import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import mage.cards.Card;
import mage.constants.Zone;
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
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Records one Playmat game for mtg-ai, in the layout play/match.py writes, so play/review.py, play/summarize.py and
 * engine/encode.py read it unchanged:
 *
 *   <root>/<date>/<game id>/game0.jsonl   every recorded decision of every seat, in time order (merged at the end)
 *                          /games.jsonl   one line: winner, turns, first, lives, players, decks
 *                          /config.json   seats, deck files, Playmat and mtg-ai commits
 *                          /seat-A.jsonl  the seat's own decisions as they happened (B likewise)
 *                          /deck-A.dck    the seat's 40 cards at its first decision (every zone, so a resumed game
 *                                         has them all too)
 *                          /game_log.jsonl the game log every player sees (the table's INFO and STATUS messages)
 *                          /superseded_by.json  when a later table carried this game on from one of its turns
 *
 * Take-backs. A turn rollback ("Player request: Rolling back to start of turn N") keeps the game and its folder: it
 * is listed in config.json's "rollbacks" ({ts, to_turn, from_turn}) and on the games.jsonl line, and at the merge
 * every decision recorded before it from turn N on gets "superseded": true (kept, never deleted); decisions after
 * the first rollback get "after_rollback": true. The seats are told (RecordedHuman drops what it holds, a Claude
 * seat's service restarts its conversation). A resume ("The game carries on from the start of turn N", Playmat's
 * "take back" / "try again" / a saved game) is a new game and folder: config.json gets "resumed_from_turn" and, when
 * the earlier recording is found (same players, reached turn N, ended at most ten minutes before this game started
 * or never ended), "resumed_from" (its game id), "resumed_from_dir" and "resumed_from_seats" (this game's seat
 * letter -> that game's). That folder gets superseded_by.json, "superseded_by" in config.json, "ended_by": "resumed
 * elsewhere" on its games.jsonl line, and its decisions from turn N on are marked superseded in game0.jsonl.
 * engine/playmat/fix_resumed_recordings.py applies the same marks to folders recorded before this.
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
    final List<Runnable> beforeEnd = new ArrayList<>();
    private boolean decksWritten = false, ended = false;
    private final long started = System.currentTimeMillis();
    /** turn rollbacks in this game: {ts, to_turn, from_turn} */
    final JsonArray rollbacks = new JsonArray();
    /** set when this game carries on a saved turn of an earlier one (see onResumed) */
    Integer resumedFromTurn;
    String resumedFrom;
    Path resumedFromDir;
    final Map<String, String> resumedSeats = new LinkedHashMap<>();
    /** set when a later game carried this one on: {game_id, from_turn, ts, dir} */
    JsonObject supersededBy;
    final JsonArray warnings = new JsonArray();

    static final Pattern ROLLBACK = Pattern.compile("Rolling back to start of turn (\\d+)");
    static final Pattern RESUMED = Pattern.compile("The game carries on from the start of turn (\\d+)");
    /** how long before this game started the earlier one may have ended to count as the one it resumes */
    static final long RESUME_WINDOW_MS = 10 * 60 * 1000L;
    static final Set<Zone> OWN_ZONES = EnumSet.of(Zone.LIBRARY, Zone.HAND, Zone.BATTLEFIELD, Zone.GRAVEYARD, Zone.EXILED,
            Zone.STACK, Zone.COMMAND);

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

    /** The log line our server patch writes when a player ends a decided game as a win (patch 0013). */
    static final String CLAIM_TEXT = "claims the win";
    volatile String endedBy;  // "human_claim" or "concede", for a game ended early

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

    /**
     * Each seat's deck, written at the first decision of the game: every card the seat owns in the game's zones
     * (library, hand, battlefield face up or down, graveyard, exile, stack, command), not tokens, copies or the
     * sideboard. At the start of a new game that is library and hand; a resumed game has cards everywhere. A resumed
     * game's deck is compared with the earlier recording's (a difference goes to config.json's "warnings").
     */
    synchronized void ensureDecks() {
        if (decksWritten) return;
        decksWritten = true;
        for (Map.Entry<UUID, String> e : seatOf.entrySet()) {
            Player p = game.getPlayer(e.getKey());
            if (p == null) continue;
            Map<String, Integer> counts = new TreeMap<>();
            Map<String, String> setOf = new HashMap<>();
            for (Card c : game.getCards()) {
                // gameCards holds each card once plus its parts (split halves, Room doors...): count the whole card
                if (c == null || !e.getKey().equals(c.getOwnerId()) || !c.getId().equals(c.getMainCard().getId()) || c.isCopy())
                    continue;
                Zone z = game.getState().getZone(c.getId());
                if (z == null || !OWN_ZONES.contains(z)) continue;
                counts.merge(c.getName(), 1, Integer::sum);
                setOf.putIfAbsent(c.getName(), c.getExpansionSetCode() + ":" + c.getCardNumber());
            }
            StringBuilder sb = new StringBuilder();
            int total = 0;
            for (Map.Entry<String, Integer> c : counts.entrySet()) {
                sb.append(c.getValue()).append(" [").append(setOf.get(c.getKey())).append("] ").append(c.getKey()).append('\n');
                total += c.getValue();
            }
            try {
                Files.write(deckFile(e.getValue()), sb.toString().getBytes(StandardCharsets.UTF_8));
            } catch (IOException ex) {
                throw new UncheckedIOException(ex);
            }
            if (total != 40) warnings.add("deck-" + e.getValue() + ".dck has " + total + " cards");
            String prevSeat = resumedSeats.get(e.getValue());
            if (resumedFromDir != null && prevSeat != null) {
                Path prev = resumedFromDir.resolve("deck-" + prevSeat + ".dck");
                try {
                    if (Files.exists(prev) && !sortedLines(prev).equals(sortedLines(deckFile(e.getValue()))))
                        warnings.add("deck-" + e.getValue() + ".dck differs from the resumed game's " + prev);
                } catch (IOException ex) {
                    warnings.add("could not compare deck-" + e.getValue() + ".dck with " + prev + ": " + ex.getMessage());
                }
            }
        }
        writeConfig();
    }

    private static List<String> sortedLines(Path f) throws IOException {
        List<String> l = new ArrayList<>();
        for (String s : Files.readAllLines(f, StandardCharsets.UTF_8)) if (!s.isBlank()) l.add(s.trim());
        Collections.sort(l);
        return l;
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
        if (!rec.has("ts")) rec.addProperty("ts", System.currentTimeMillis());
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
        if (endedBy != null) c.addProperty("ended_by", endedBy);
        if (rollbacks.size() > 0) {
            c.addProperty("has_rollback", true);
            c.add("rollbacks", rollbacks.deepCopy());
        }
        if (resumedFromTurn != null) {
            c.addProperty("resumed_from_turn", resumedFromTurn);
            c.addProperty("resumed_from", resumedFrom);
            if (resumedFromDir != null) c.addProperty("resumed_from_dir", resumedFromDir.toString());
            JsonObject m = new JsonObject();
            for (Map.Entry<String, String> e : resumedSeats.entrySet()) m.addProperty(e.getKey(), e.getValue());
            c.add("resumed_from_seats", m);
        }
        if (supersededBy != null) c.add("superseded_by", supersededBy.deepCopy());
        if (warnings.size() > 0) c.add("warnings", warnings.deepCopy());
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

    synchronized void setSeatInfo(String seat, String key, String value) {
        JsonObject i = seatInfo.get(seat);
        if (i != null) {
            i.addProperty(key, value);
            writeConfig();
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
        for (Runnable r : beforeEnd) r.run();  // decisions a seat still holds (RecordedHuman's last blocks)
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
        if (endedBy != null) g.addProperty("ended_by", endedBy);
        if (rollbacks.size() > 0) g.add("rollbacks", rollbacks.deepCopy());
        if (resumedFromTurn != null) {
            g.addProperty("resumed_from", resumedFrom);
            g.addProperty("resumed_from_turn", resumedFromTurn);
        }
        if (supersededBy != null) markEnded(g, supersededBy);
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

    /** A games.jsonl line of a game a later table carried on: the result stays, but it isn't how the game ended. */
    static void markEnded(JsonObject g, JsonObject by) {
        g.addProperty("ended_by", "resumed elsewhere");
        g.addProperty("superseded_by", by.get("game_id").getAsString());
        g.addProperty("superseded_from_turn", by.get("from_turn").getAsInt());
    }

    // ---------- take-backs ----------

    /** A turn rollback in this game (from the game log's "Player request: Rolling back to start of turn N"). */
    void onRollback(int toTurn, long ts) {
        synchronized (this) {
            if (ended) return;
            JsonObject rb = new JsonObject();
            rb.addProperty("ts", ts);
            rb.addProperty("to_turn", toTurn);
            rb.addProperty("from_turn", game.getTurnNum());  // the log line comes before the state is put back
            rollbacks.add(rb);
            writeConfig();
        }
        for (UUID id : new ArrayList<>(seatOf.keySet())) {
            Player p = game.getPlayer(id);
            if (p instanceof RecordedHuman) ((RecordedHuman) p).onRollback(game);
        }
        for (ClaudeSeat c : new ArrayList<>(claudeSeats)) c.sendRollback(toTurn);
    }

    /** The players of a seat map, as "kind|name", sorted: what a resumed table has in common with the old one. */
    static List<String> players(Map<String, JsonObject> seats) {
        List<String> out = new ArrayList<>();
        for (JsonObject i : seats.values())
            out.add(i.get("kind").getAsString() + "|" + i.get("name").getAsString());
        Collections.sort(out);
        return out;
    }

    /** this game's seat letter -> the other game's, by player name */
    private Map<String, String> seatMap(Map<String, JsonObject> other) {
        Map<String, String> m = new LinkedHashMap<>();
        for (Map.Entry<String, JsonObject> mine : seatInfo.entrySet())
            for (Map.Entry<String, JsonObject> o : other.entrySet())
                if (o.getValue().get("name").getAsString().equals(mine.getValue().get("name").getAsString())
                        && o.getValue().get("kind").getAsString().equals(mine.getValue().get("kind").getAsString()))
                    m.put(mine.getKey(), o.getKey());
        return m;
    }

    /**
     * This game carries on from the start of turn N of an earlier one (Playmat's take-back, "try this turn again", or
     * a saved game). The earlier recording is a game still held here (it usually ends a moment after this one
     * starts) or a folder of today or yesterday, with the same players, that reached turn N, not already carried on
     * elsewhere, and that ended at most RESUME_WINDOW_MS before this game started or never ended; the latest such.
     */
    void onResumed(int fromTurn, long ts) {
        List<String> mine;
        synchronized (this) {
            if (resumedFromTurn != null) return;
            resumedFromTurn = fromTurn;
            mine = players(seatInfo);
        }
        GameRecorder live = null;
        for (GameRecorder o : GAMES.values()) {
            if (o == this || o.started > started) continue;
            synchronized (o) {
                if (o.supersededBy != null || o.game.getTurnNum() < fromTurn || !players(o.seatInfo).equals(mine)) continue;
            }
            if (live == null || o.started > live.started) live = o;
        }
        JsonObject by = new JsonObject();
        by.addProperty("game_id", game.getId().toString());
        by.addProperty("from_turn", fromTurn);
        by.addProperty("ts", ts);
        by.addProperty("dir", dir.toString());
        Path prevDir = null;
        Map<String, String> map = null;
        if (live != null) {
            prevDir = live.dir;
            synchronized (live) {
                map = seatMap(live.seatInfo);
            }
            try {
                live.supersede(by);
            } catch (RuntimeException e) {
                synchronized (this) {
                    warnings.add("could not mark " + live.dir + " as carried on here: " + e);
                }
            }
        } else {
            Path best = findPrevious(dir, started, mine, fromTurn);
            JsonObject bestCfg = null;
            if (best != null) {
                try {
                    bestCfg = JsonParser.parseString(Files.readString(best.resolve("config.json"))).getAsJsonObject();
                } catch (IOException | RuntimeException e) {
                    best = null;
                }
            }
            if (best != null) {
                prevDir = best;
                map = seatMap(seatsOf(bestCfg));
                try {
                    supersedeFolder(best, by);
                } catch (IOException | RuntimeException e) {
                    synchronized (this) {
                        warnings.add("could not mark " + best + " as carried on here: " + e);
                    }
                }
            }
        }
        synchronized (this) {
            if (prevDir != null) {
                resumedFromDir = prevDir;
                resumedFrom = prevDir.getFileName().toString();
                resumedSeats.putAll(map);
            } else {
                warnings.add("resumed from turn " + fromTurn + " but no earlier recording of these players was found");
            }
            writeConfig();
        }
    }

    /**
     * The recorded folder a game in {@code dir} (started at {@code started}, players {@code mine}) carries on from turn
     * {@code fromTurn}, among the folders of its day and the day before (see onResumed), or null.
     */
    static Path findPrevious(Path dir, long started, List<String> mine, int fromTurn) {
        Path best = null;
        long bestStart = Long.MIN_VALUE;
        Path root = dir.getParent().getParent();
        String today = dir.getParent().getFileName().toString();
        for (String day : new String[]{today, LocalDate.parse(today).minusDays(1).toString()}) {
            Path d = root.resolve(day);
            if (!Files.isDirectory(d)) continue;
            try (DirectoryStream<Path> ds = Files.newDirectoryStream(d)) {
                for (Path f : ds) {
                    if (f.equals(dir) || Files.exists(f.resolve("superseded_by.json")) || !Files.exists(f.resolve("config.json")))
                        continue;
                    try {
                        JsonObject cfg = JsonParser.parseString(Files.readString(f.resolve("config.json"))).getAsJsonObject();
                        long st = cfg.has("started_ms") ? cfg.get("started_ms").getAsLong() : 0L;
                        if (st > started || st <= bestStart || !cfg.has("seats")) continue;
                        if (!players(seatsOf(cfg)).equals(mine) || lastTurn(f) < fromTurn) continue;
                        Path gj = f.resolve("games.jsonl");
                        if (Files.exists(gj) && Files.getLastModifiedTime(gj).toMillis() < started - RESUME_WINDOW_MS) continue;
                        best = f;
                        bestStart = st;
                    } catch (IOException | RuntimeException ignored) {
                        // an unreadable folder isn't the one
                    }
                }
            } catch (IOException | RuntimeException ignored) {
                // no such day
            }
        }
        return best;
    }

    static Map<String, JsonObject> seatsOf(JsonObject cfg) {
        Map<String, JsonObject> m = new LinkedHashMap<>();
        for (Map.Entry<String, com.google.gson.JsonElement> e : cfg.getAsJsonObject("seats").entrySet())
            m.put(e.getKey(), e.getValue().getAsJsonObject());
        return m;
    }

    /** The last turn a recorded folder reached: its games.jsonl, else its game log's last line. */
    static int lastTurn(Path f) throws IOException {
        Path gj = f.resolve("games.jsonl");
        if (Files.exists(gj)) {
            for (String l : Files.readAllLines(gj, StandardCharsets.UTF_8))
                if (!l.isBlank()) return JsonParser.parseString(l).getAsJsonObject().get("turns").getAsInt();
        }
        int t = 0;
        Path log = f.resolve("game_log.jsonl");
        if (Files.exists(log))
            for (String l : Files.readAllLines(log, StandardCharsets.UTF_8))
                if (!l.isBlank()) t = Math.max(t, JsonParser.parseString(l).getAsJsonObject().get("turn").getAsInt());
        return t;
    }

    /** A later game carries this one (still held here) on: marked now, and again at its end. */
    synchronized void supersede(JsonObject by) {
        supersededBy = by.deepCopy();
        try {
            Files.write(dir.resolve("superseded_by.json"), PRETTY.toJson(by).getBytes(StandardCharsets.UTF_8));
            if (ended) {
                // ended while the new game was being linked: its games.jsonl is already written
                rewriteGames(dir, by);
            }
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
        merge();
        writeConfig();
    }

    /** The same marks on a folder no longer held here (a restart, or a game recorded before this code). */
    static void supersedeFolder(Path f, JsonObject by) throws IOException {
        Files.write(f.resolve("superseded_by.json"), PRETTY.toJson(by).getBytes(StandardCharsets.UTF_8));
        Path cf = f.resolve("config.json");
        JsonObject cfg = JsonParser.parseString(Files.readString(cf)).getAsJsonObject();
        cfg.add("superseded_by", by.deepCopy());
        Files.write(cf, PRETTY.toJson(cfg).getBytes(StandardCharsets.UTF_8));
        rewriteGames(f, by);
        List<String> seats = new ArrayList<>(seatsOf(cfg).keySet());
        mergeFolder(f, seats, cfg.has("rollbacks") ? cfg.getAsJsonArray("rollbacks") : new JsonArray(), by);
    }

    private static void rewriteGames(Path f, JsonObject by) throws IOException {
        Path gj = f.resolve("games.jsonl");
        if (!Files.exists(gj)) return;
        StringBuilder sb = new StringBuilder();
        for (String l : Files.readAllLines(gj, StandardCharsets.UTF_8)) {
            if (l.isBlank()) continue;
            JsonObject g = JsonParser.parseString(l).getAsJsonObject();
            markEnded(g, by);
            sb.append(GSON.toJson(g)).append('\n');
        }
        Files.write(gj, sb.toString().getBytes(StandardCharsets.UTF_8));
    }

    /** game0.jsonl: every seat file merged by time (Claude's lines carry "ts" too), with the take-back marks. */
    synchronized void merge() {
        try {
            mergeFolder(dir, new ArrayList<>(seatInfo.keySet()), rollbacks, supersededBy);
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    /**
     * Merges a folder's seat files into game0.jsonl. A decision that didn't stand (see supersededHow) gets
     * "superseded": true and "superseded_by" ("rollback" or "resume:<game id>"); decisions after the first rollback
     * get "after_rollback": true. The seat files stay as they were written.
     */
    static void mergeFolder(Path dir, List<String> seats, JsonArray rollbacks, JsonObject by) throws IOException {
        List<JsonObject> all = new ArrayList<>();
        for (String seat : seats) {
            Path f = dir.resolve("seat-" + seat + ".jsonl");
            if (!Files.exists(f)) continue;
            for (String line : Files.readAllLines(f, StandardCharsets.UTF_8))
                if (!line.isBlank()) all.add(JsonParser.parseString(line).getAsJsonObject());
        }
        all.sort(Comparator.comparingLong(o -> o.has("ts") ? o.get("ts").getAsLong() : 0L));
        long firstRollback = Long.MAX_VALUE;
        for (com.google.gson.JsonElement e : rollbacks) firstRollback = Math.min(firstRollback, e.getAsJsonObject().get("ts").getAsLong());
        StringBuilder sb = new StringBuilder();
        for (JsonObject o : all) {
            String how = supersededHow(o, rollbacks, by);
            if (how != null) {
                o.addProperty("superseded", true);
                o.addProperty("superseded_by", how);
            }
            if (o.has("ts") && o.get("ts").getAsLong() > firstRollback) o.addProperty("after_rollback", true);
            sb.append(GSON.toJson(o)).append('\n');
        }
        Files.write(dir.resolve("game0.jsonl"), sb.toString().getBytes(StandardCharsets.UTF_8));
    }

    /**
     * Why a decision didn't stand, or null: "rollback" (recorded before a rollback to a turn at or before its own) or
     * "resume:<game id>" (from the turn a later game carried on from). engine/playmat/fix_resumed_recordings.py's
     * superseded() is the same rule.
     */
    static String supersededHow(JsonObject rec, JsonArray rollbacks, JsonObject by) {
        int turn;
        try {
            turn = rec.getAsJsonObject("obs").getAsJsonArray("entries").get(0).getAsJsonObject().get("turn").getAsInt();
        } catch (RuntimeException e) {
            return null;
        }
        long ts = rec.has("ts") ? rec.get("ts").getAsLong() : 0L;
        for (com.google.gson.JsonElement e : rollbacks) {
            JsonObject rb = e.getAsJsonObject();
            if (ts < rb.get("ts").getAsLong() && turn >= rb.get("to_turn").getAsInt()) return "rollback";
        }
        if (by != null && turn >= by.get("from_turn").getAsInt()) return "resume:" + by.get("game_id").getAsString();
        return null;
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
                    String text = m.replaceAll("<[^>]+>", "");
                    o.addProperty("text", text);
                    o.addProperty("raw", m);
                    synchronized (r) {
                        append(r.dir.resolve("game_log.jsonl"), GSON.toJson(o));
                    }
                    long ts = o.get("ts").getAsLong();
                    Matcher rb = ROLLBACK.matcher(text);
                    if (rb.find()) r.onRollback(Integer.parseInt(rb.group(1)), ts);
                    Matcher rs = RESUMED.matcher(text);
                    if (event.getEventType() == TableEvent.EventType.INFO && rs.find()) r.onResumed(Integer.parseInt(rs.group(1)), ts);
                    // how a decided game was ended early (Jeff 2026-10-24): the player claimed it, or Claude conceded
                    if (text.contains(CLAIM_TEXT)) r.endedBy = "human_claim";
                    else if (text.contains(ClaudeSeat.CONCEDE_TEXT) && r.endedBy == null) r.endedBy = "concede";
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
