import com.google.gson.JsonObject;
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
 * Messages on the socket are PySeat's, plus: the first decision of each game carries "start" (game id, folder, seat
 * letter, deck file); {"type":"game_end", ...games.jsonl line} after each game; {"type":"end"} when the match ends.
 */
public class ClaudeSeat extends PySeat {

    private final transient Socket socket;
    private transient String startedGame;

    public ClaudeSeat(String name, RangeOfInfluence range, int skill) {
        this(name, connect());
    }

    private ClaudeSeat(String name, Socket socket) {
        super(name, link(socket));
        this.socket = socket;
    }

    public ClaudeSeat(final ClaudeSeat player) {
        super(player);
        this.socket = player.socket;
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
        synchronized (r) {
            if (!r.claudeSeats.contains(this)) r.claudeSeats.add(this);
        }
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
        msg.add("start", start);
    }

    @Override
    protected void onReply(JsonObject reply, Game game) {
        GameRecorder r = GameRecorder.find(game);
        if (r != null && reply.has("player")) r.setPlayerName(r.seat(playerId), reply.get("player").getAsString());
    }

    void sendGameEnd(JsonObject result) {
        JsonObject end = result.deepCopy();
        end.addProperty("type", "game_end");
        synchronized (link) {
            link.out.println(link.gson.toJson(end));
        }
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
