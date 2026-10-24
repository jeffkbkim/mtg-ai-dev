import com.google.gson.JsonObject;
import mage.cards.Card;
import mage.cards.decks.Deck;
import mage.constants.RangeOfInfluence;
import mage.game.Game;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.net.Socket;

/**
 * The "Computer - claude" player type in Playmat: our PySeat (same decisions, observation and leak checks as
 * play/match.py games), connected to the Python service engine/playmat/claude_service.py on localhost
 * (-Dmtgai.claudePort, default 17180), which runs play/players.py's ClaudePlayer and writes its decisions to the
 * game's folder (see GameRecorder). A table whose service isn't running can't seat this player: the join fails.
 *
 * Messages on the socket are PySeat's, plus: {"type":"hello", model, effort} when the seat is created (the table is
 * set up); {"type":"prewarm", deck} when the game is dealt its deck, so the service can start the model before the first
 * decision; the first decision of each game carries "start" (game id, folder, seat letter, deck file);
 * {"type":"game_end", ...games.jsonl line} after each game; {"type":"rollback", "to_turn": N} when the game goes back
 * to the start of turn N (a take-back; the service restarts the conversation and marks the undone part of the log);
 * {"type":"end"} when the match ends. None of these is answered. When the game carries on a saved turn of an earlier
 * recording (GameRecorder.onResumed), "start" also has "resumed_from": {dir, seat (this player's seat letter there),
 * turn}, so the service can give the model the log of the earlier game.
 *
 * The model and effort come from the seat's skill, which the web client sets (see 0006's claudeSkill): model index * 3
 * + effort index + 1, Opus 5.5 then Sonnet 5.5, low/medium/high. Any other skill is Opus 5.5 high.
 */
public class ClaudeSeat extends PySeat {

    static final String[] MODELS = {"claude-opus-5-5", "claude-sonnet-5-5"};
    static final String[] EFFORTS = {"low", "medium", "high"};

    private final transient Socket socket;
    private transient String startedGame;
    final String model, effort;

    public ClaudeSeat(String name, RangeOfInfluence range, int skill) {
        this(name, connect(), skill >= 1 && skill <= 6 ? skill : 3);
    }

    private ClaudeSeat(String name, Socket socket, int skill) {
        super(name, link(socket));
        this.socket = socket;
        this.model = MODELS[(skill - 1) / 3];
        this.effort = EFFORTS[(skill - 1) % 3];
        JsonObject hello = new JsonObject();
        hello.addProperty("type", "hello");
        hello.addProperty("model", model);
        hello.addProperty("effort", effort);
        send(hello);
    }

    public ClaudeSeat(final ClaudeSeat player) {
        super(player);
        this.socket = player.socket;
        this.model = player.model;
        this.effort = player.effort;
    }

    private void send(JsonObject msg) {
        synchronized (link) {
            link.out.println(link.gson.toJson(msg));
        }
    }

    @Override
    public ClaudeSeat copy() {
        return new ClaudeSeat(this);
    }

    private static Socket connect() {
        int port = Integer.getInteger("mtgai.claudePort", 17180);
        try {
            Socket s = new Socket("127.0.0.1", port);
            s.setTcpNoDelay(true);
            return s;
        } catch (IOException e) {
            throw new UncheckedIOException("the Claude service is not running on port " + port, e);
        }
    }

    private static Link link(Socket s) {
        try {
            return new Link(s.getInputStream(), s.getOutputStream());
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    @Override
    public void init(Game game) {
        super.init(game);
        if (game.isSimulation()) return;
        GameRecorder r = GameRecorder.of(game);
        r.register(this, "claude", getClass().getName(), 0);
        r.setSeatInfo(r.seat(playerId), "model", model);
        r.setSeatInfo(r.seat(playerId), "effort", effort);
        synchronized (r) {
            if (!r.claudeSeats.contains(this)) r.claudeSeats.add(this);
        }
    }

    /** The game's deck, in GameRecorder's .dck format: the service starts the model on it before the first decision. */
    @Override
    public void useDeck(Deck deck, Game game) {
        super.useDeck(deck, game);
        if (game.isSimulation()) return;
        GameRecorder rec = GameRecorder.find(game);
        if (rec != null) rec.setSeatInfo(rec.seat(playerId), "deck_name", String.valueOf(deck.getName()));
        java.util.Map<String, Integer> counts = new java.util.TreeMap<>();
        java.util.Map<String, String> setOf = new java.util.HashMap<>();
        for (Card c : deck.getMaindeckCards()) {
            counts.merge(c.getName(), 1, Integer::sum);
            setOf.putIfAbsent(c.getName(), c.getExpansionSetCode() + ":" + c.getCardNumber());
        }
        StringBuilder sb = new StringBuilder();
        for (java.util.Map.Entry<String, Integer> c : counts.entrySet())
            sb.append(c.getValue()).append(" [").append(setOf.get(c.getKey())).append("] ").append(c.getKey()).append('\n');
        JsonObject warm = new JsonObject();
        warm.addProperty("type", "prewarm");
        warm.addProperty("deck", sb.toString());
        send(warm);
    }

    @Override
    protected void decorate(JsonObject msg, Game game) {
        GameRecorder r = GameRecorder.find(game);
        if (r == null || game.getId().toString().equals(startedGame)) return;
        startedGame = game.getId().toString();
        r.ensureDecks();
        String seat = r.seat(playerId);
        JsonObject start = new JsonObject();
        start.addProperty("game_id", startedGame);
        start.addProperty("dir", r.dir.toString());
        start.addProperty("seat", seat);
        start.addProperty("deck", r.deckFile(seat).toString());
        synchronized (r) {
            if (r.resumedFromTurn != null) {
                JsonObject from = new JsonObject();
                from.addProperty("turn", r.resumedFromTurn);
                if (r.resumedFromDir != null && r.resumedSeats.containsKey(seat)) {
                    from.addProperty("dir", r.resumedFromDir.toString());
                    from.addProperty("seat", r.resumedSeats.get(seat));
                }
                start.add("resumed_from", from);
            }
        }
        msg.add("start", start);
    }

    @Override
    protected void onReply(JsonObject reply, Game game) {
        GameRecorder r = GameRecorder.find(game);
        if (r != null && reply.has("player")) r.setPlayerName(r.seat(playerId), reply.get("player").getAsString());
    }

    void sendRollback(int toTurn) {
        JsonObject rb = new JsonObject();
        rb.addProperty("type", "rollback");
        rb.addProperty("to_turn", toTurn);
        send(rb);
    }

    void sendGameEnd(JsonObject result) {
        JsonObject end = result.deepCopy();
        end.addProperty("type", "game_end");
        send(end);
    }

    @Override
    public void cleanUpOnMatchEnd() {
        super.cleanUpOnMatchEnd();
        try {
            synchronized (link) {
                link.out.println("{\"type\":\"end\"}");
            }
            socket.close();
        } catch (IOException | RuntimeException ignored) {
            // already closed
        }
    }
}
