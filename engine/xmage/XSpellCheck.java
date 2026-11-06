import com.google.gson.*;
import mage.cards.Card;
import mage.constants.*;
import mage.game.*;
import mage.game.mulligan.MulliganType;
import mage.game.stack.Spell;
import mage.game.turn.Phase;
import mage.player.ai.ComputerPlayer7;
import java.io.*;
import java.util.*;

/**
 * Regression check: a spell with {X}{X} in its cost must be castable. X is still picked by XMage's AI (the largest
 * value the untapped mana sources cover), but its formula assumes one X: with 7 Forests, Valgavoth's Onslaught
 * ({X}{X}{G}) got X = 6, needing 13 mana, so every cast was refused (seen by the batch-2 reviewer in two games).
 * Board in our precombat main: 7 Forest; hand: Valgavoth's Onslaught. Casting it must put it on the stack with X = 3.
 * With PySeat.askX the player is asked for X instead (options X = 0 to 3); picking "X = 1" must put it on the stack
 * with X = 1.
 * Prints PASS or FAIL and exits 1 on FAIL.
 */
public class XSpellCheck {
    public static void main(String[] args) throws Exception {
        mage.cards.repository.RepositoryUtil.bootstrapLocalDb();
        mage.cards.repository.CardScanner.scan();
        boolean ok = run(false, 3) & run(true, 1);
        System.out.println(ok ? "PASS" : "FAIL");
        System.exit(ok ? 0 : 1);
    }

    static boolean run(boolean askX, int want) throws Exception {
        PipedInputStream seatIn = new PipedInputStream(), fromSeat = new PipedInputStream();
        PrintWriter toSeat = new PrintWriter(new PipedOutputStream(seatIn), true);
        PySeat.Link link = new PySeat.Link(seatIn, new PipedOutputStream(fromSeat));
        List<String> asked = Collections.synchronizedList(new ArrayList<>());
        Thread python = new Thread(() -> {  // casts the Onslaught when offered, otherwise picks the first option
            try (BufferedReader r = new BufferedReader(new InputStreamReader(fromSeat))) {
                for (String line; (line = r.readLine()) != null; ) {
                    JsonObject m = JsonParser.parseString(line).getAsJsonObject();
                    JsonArray opts = m.getAsJsonArray("options");
                    asked.add(m.get("kind").getAsString() + ": " + m.get("prompt").getAsString());
                    int pick = 0;
                    for (int i = 0; i < opts.size(); i++)
                        if (opts.get(i).getAsJsonObject().get("label").getAsString().matches(".*Cast Valgavoth's Onslaught.*|X = 1")) pick = i;
                    toSeat.println("{\"choice\":" + pick + "}");
                }
            } catch (IOException ignored) { }
        });
        python.setDaemon(true);
        python.start();

        Game game = new TwoPlayerDuel(MultiplayerAttackOption.LEFT, RangeOfInfluence.ONE, MulliganType.GAME_DEFAULT.getMulligan(0), 40, 20, 7);
        game.setGameOptions(new GameOptions());
        PySeat py = new PySeat("PY", link);
        py.askX = askX;
        ComputerPlayer7 ai = new ComputerPlayer7("AI", RangeOfInfluence.ONE, 2);
        mage.game.match.Match match = new TwoPlayerMatch(new mage.game.match.MatchOptions("x spell check", "Two Player Duel", false));
        for (mage.players.Player p : new mage.players.Player[]{py, ai}) {
            p.setTestMode(true);
            mage.cards.decks.Deck deck = new mage.cards.decks.Deck();
            game.addPlayer(p, deck);
            match.addPlayer(p, deck);
        }
        for (int i = 0; i < 7; i++) ManaCheck.put(game, "Forest", py.getId());
        Card onslaught = ManaCheck.make(game, "Valgavoth's Onslaught", py.getId());
        py.getHand().add(onslaught);
        game.getState().setZone(onslaught.getId(), Zone.HAND);
        for (mage.players.Player p : new mage.players.Player[]{py, ai}) p.beginTurn(game);
        game.getState().setActivePlayerId(py.getId());
        Phase main = game.getState().getTurn().getPhase(TurnPhase.PRECOMBAT_MAIN);
        main.setStep(new mage.game.turn.PreCombatMainStep());
        game.getState().getTurn().setPhase(main);
        game.applyEffects();
        String refused = "";
        try {
            py.priority(game);
        } catch (NullPointerException e) {  // a refused cast rolls the game back, which this unstarted game can't do
            refused = " (cast refused: " + e.getStackTrace()[0] + ")";
        }
        Thread.sleep(300);
        Spell spell = game.getStack().getSpell(onslaught.getId());
        Object tag = spell == null ? null : spell.getSpellAbility().getCostsTagMap() == null ? null : spell.getSpellAbility().getCostsTagMap().get("X");
        int x = tag instanceof Integer ? (Integer) tag : -1;
        System.out.println("asked " + asked);
        System.out.println((askX ? "askX: " : "") + "on the stack: " + (spell != null) + ", X = " + x + " (want " + want + ")" + refused);
        boolean askedX = asked.stream().anyMatch(a -> a.startsWith("X:"));
        return spell != null && x == want && askedX == askX;
    }
}
