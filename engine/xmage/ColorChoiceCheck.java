import com.google.gson.*;
import mage.ObjectColor;
import mage.cards.Card;
import mage.constants.*;
import mage.game.*;
import mage.game.mulligan.MulliganType;
import mage.game.turn.Phase;
import mage.player.ai.ComputerPlayer7;
import java.io.*;
import java.util.*;

/**
 * Regression check: "As this land enters, choose a color" must be asked of the player. XMage flags every colour
 * choice as a mana colour choice, which the seat answers in Java, so Valgavoth's Lair took XMage's AI pick: in a
 * batch-1 game it never made green in a black-green deck, and the green cards in hand were never castable.
 * Board in our precombat main: hand Valgavoth's Lair; the player plays it and answers "Green". Prints PASS or FAIL and
 * exits 1 on FAIL.
 */
public class ColorChoiceCheck {
    public static void main(String[] args) throws Exception {
        mage.cards.repository.RepositoryUtil.bootstrapLocalDb();
        mage.cards.repository.CardScanner.scan();
        PipedInputStream seatIn = new PipedInputStream(), fromSeat = new PipedInputStream();
        PrintWriter toSeat = new PrintWriter(new PipedOutputStream(seatIn), true);
        PySeat.Link link = new PySeat.Link(seatIn, new PipedOutputStream(fromSeat));
        List<String> asked = Collections.synchronizedList(new ArrayList<>());
        Thread python = new Thread(() -> {  // plays the Lair, answers Green, otherwise picks the first option
            try (BufferedReader r = new BufferedReader(new InputStreamReader(fromSeat))) {
                for (String line; (line = r.readLine()) != null; ) {
                    JsonObject m = JsonParser.parseString(line).getAsJsonObject();
                    JsonArray opts = m.getAsJsonArray("options");
                    asked.add(m.get("kind").getAsString() + ": " + m.get("prompt").getAsString());
                    int pick = 0;
                    for (int i = 0; i < opts.size(); i++) {
                        String label = opts.get(i).getAsJsonObject().get("label").getAsString();
                        if (label.contains("Play Valgavoth's Lair") || label.equals("Green")) pick = i;
                    }
                    toSeat.println("{\"choice\":" + pick + "}");
                }
            } catch (IOException ignored) { }
        });
        python.setDaemon(true);
        python.start();

        Game game = new TwoPlayerDuel(MultiplayerAttackOption.LEFT, RangeOfInfluence.ONE, MulliganType.GAME_DEFAULT.getMulligan(0), 40, 20, 7);
        game.setGameOptions(new GameOptions());
        PySeat py = new PySeat("PY", link);
        ComputerPlayer7 ai = new ComputerPlayer7("AI", RangeOfInfluence.ONE, 2);
        mage.game.match.Match match = new TwoPlayerMatch(new mage.game.match.MatchOptions("color choice check", "Two Player Duel", false));
        for (mage.players.Player p : new mage.players.Player[]{py, ai}) {
            p.setTestMode(true);
            mage.cards.decks.Deck deck = new mage.cards.decks.Deck();
            game.addPlayer(p, deck);
            match.addPlayer(p, deck);
        }
        Card lair = ManaCheck.make(game, "Valgavoth's Lair", py.getId());
        py.getHand().add(lair);
        game.getState().setZone(lair.getId(), Zone.HAND);
        for (mage.players.Player p : new mage.players.Player[]{py, ai}) p.beginTurn(game);
        game.getState().setActivePlayerId(py.getId());
        Phase main = game.getState().getTurn().getPhase(TurnPhase.PRECOMBAT_MAIN);
        main.setStep(new mage.game.turn.PreCombatMainStep());
        game.getState().getTurn().setPhase(main);
        game.applyEffects();
        py.priority(game);
        Thread.sleep(300);
        Object color = game.getState().getValue(lair.getId() + "_color");
        boolean onBattlefield = game.getPermanent(lair.getId()) != null;
        System.out.println("asked " + asked);
        System.out.println("Lair on the battlefield: " + onBattlefield + ", chosen color " + color + " (want G)");
        boolean ok = onBattlefield && color instanceof ObjectColor && ((ObjectColor) color).isGreen() && ((ObjectColor) color).getColorCount() == 1
                && asked.stream().anyMatch(a -> a.startsWith("CHOICE"));
        System.out.println(ok ? "PASS" : "FAIL");
        System.exit(ok ? 0 : 1);
    }
}
