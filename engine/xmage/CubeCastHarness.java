import com.google.gson.*;
import mage.cards.Card;
import mage.constants.*;
import mage.game.*;
import mage.game.mulligan.MulliganType;
import mage.game.stack.StackObject;
import mage.game.turn.Phase;
import mage.player.ai.ComputerPlayer7;
import java.io.*;
import java.util.*;

/**
 * Shared set-up for the cube cast checks (KroxaEscapeCheck, EscalateCheck, ChannelCheck, MarchCheck): a two-player
 * game in this seat's precombat main with a Cube seat (payerV2, costlyManaAsk, askX) whose Python side is a thread
 * that answers each decision with the first option whose label matches one of the preference patterns (in order;
 * otherwise option 0). Every decision is logged as "KIND: prompt" with its option labels.
 */
public class CubeCastHarness {
    Game game;
    PySeat py;
    ComputerPlayer7 ai;
    final List<String> log = Collections.synchronizedList(new ArrayList<>());
    final List<String> prefs = Collections.synchronizedList(new ArrayList<>());

    CubeCastHarness(String... prefs) throws Exception {
        this.prefs.addAll(Arrays.asList(prefs));
        PipedInputStream seatIn = new PipedInputStream(), fromSeat = new PipedInputStream();
        PrintWriter toSeat = new PrintWriter(new PipedOutputStream(seatIn), true);
        PySeat.Link link = new PySeat.Link(seatIn, new PipedOutputStream(fromSeat));
        Thread python = new Thread(() -> {
            try (BufferedReader r = new BufferedReader(new InputStreamReader(fromSeat))) {
                for (String line; (line = r.readLine()) != null; ) {
                    JsonObject m = JsonParser.parseString(line).getAsJsonObject();
                    JsonArray opts = m.getAsJsonArray("options");
                    List<String> labels = new ArrayList<>();
                    for (int i = 0; i < opts.size(); i++) labels.add(opts.get(i).getAsJsonObject().get("label").getAsString());
                    log.add(m.get("kind").getAsString() + ": " + m.get("prompt").getAsString() + " " + labels);
                    int pick = -1;
                    synchronized (this.prefs) {
                        for (String p : this.prefs) {
                            for (int i = 0; i < labels.size() && pick < 0; i++) if (labels.get(i).matches(p)) pick = i;
                            if (pick >= 0) break;
                        }
                    }
                    toSeat.println("{\"choice\":" + Math.max(pick, 0) + "}");
                }
            } catch (IOException ignored) { }
        });
        python.setDaemon(true);
        python.start();
        game = new TwoPlayerDuel(MultiplayerAttackOption.LEFT, RangeOfInfluence.ONE, MulliganType.GAME_DEFAULT.getMulligan(0), 40, 20, 7);
        game.setGameOptions(new GameOptions());
        py = new PySeat("PY", link);
        py.payerV2 = py.costlyManaAsk = py.askX = true;
        try {  // TwoSeatMatch's amount decisions (askAmounts), where this build has them
            PySeat.class.getField("askAmounts").setBoolean(py, true);
        } catch (NoSuchFieldException ignored) { }
        ai =new ComputerPlayer7("AI", RangeOfInfluence.ONE, 2);
        mage.game.match.Match match = new TwoPlayerMatch(new mage.game.match.MatchOptions("cube cast check", "Two Player Duel", false));
        for (mage.players.Player p : new mage.players.Player[]{py, ai}) {
            p.setTestMode(true);
            mage.cards.decks.Deck deck = new mage.cards.decks.Deck();
            game.addPlayer(p, deck);
            match.addPlayer(p, deck);
        }
    }

    void battlefield(mage.players.Player owner, String... names) {
        for (String n : names) CostlyManaCheck.put(game, n, owner.getId());
    }

    Card hand(String name) {
        Card c = CostlyManaCheck.make(game, name, py.getId());
        py.getHand().add(c);
        game.getState().setZone(c.getId(), Zone.HAND);
        return c;
    }

    Card graveyard(String name) {
        Card c = CostlyManaCheck.make(game, name, py.getId());
        py.getGraveyard().add(c);
        game.getState().setZone(c.getId(), Zone.GRAVEYARD);
        return c;
    }

    /** Starts our precombat main with 20 life each. */
    void start() {
        for (mage.players.Player p : new mage.players.Player[]{py, ai}) {
            p.beginTurn(game);
            p.setLife(20, game, null);
        }
        game.getState().setActivePlayerId(py.getId());
        Phase main = game.getState().getTurn().getPhase(TurnPhase.PRECOMBAT_MAIN);
        main.setStep(new mage.game.turn.PreCombatMainStep());
        game.getState().getTurn().setPhase(main);
        game.applyEffects();
    }

    /** One priority for the seat; "" or why the move was refused. */
    String priority() throws InterruptedException {
        String refused = "";
        try {
            py.priority(game);
        } catch (NullPointerException e) {  // a refused cast rolls the game back, which this unstarted game can't do
            refused = "cast refused (" + e.getStackTrace()[0] + ")";
        }
        Thread.sleep(200);
        return refused;
    }

    /** Resolves the top of the stack (the game loop isn't running). */
    void resolveTop() {
        StackObject top = game.getStack().peek();
        top.resolve(game);
        game.getStack().remove(top, game);
        game.applyEffects();
    }

    StackObject stackTop() {
        return game.getStack().isEmpty() ? null : game.getStack().peek();
    }

    static void bootstrap() {
        mage.cards.repository.RepositoryUtil.bootstrapLocalDb();
        mage.cards.repository.CardScanner.scan();
    }

    static void finish(boolean ok) {
        System.out.println(ok ? "PASS" : "FAIL");
        System.exit(ok ? 0 : 1);
    }
}
