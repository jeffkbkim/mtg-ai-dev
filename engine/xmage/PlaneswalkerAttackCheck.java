import com.google.gson.*;
import mage.constants.*;
import mage.counters.CounterType;
import mage.game.*;
import mage.game.mulligan.MulliganType;
import mage.game.permanent.Permanent;
import mage.game.turn.Phase;
import mage.player.ai.ComputerPlayer7;
import java.io.*;
import java.util.*;

/**
 * Regression check: an opponent's planeswalker must be offered as an attack target. The seat only offered attacks
 * at the opponent, so Kaito, Bane of Nightmares (a planeswalker on its controller's opponent's turn) could never be
 * attacked (effort/data batches 2026-10-30, data-pairs part33). Board on our turn, declare attackers: we have an
 * untapped Bashful Beastie, the opponent has Kaito with 4 loyalty. The player picks "attacks Kaito". Prints PASS
 * or FAIL and exits 1 on FAIL.
 */
public class PlaneswalkerAttackCheck {
    public static void main(String[] args) throws Exception {
        mage.cards.repository.RepositoryUtil.bootstrapLocalDb();
        mage.cards.repository.CardScanner.scan();
        PipedInputStream seatIn = new PipedInputStream(), fromSeat = new PipedInputStream();
        PrintWriter toSeat = new PrintWriter(new PipedOutputStream(seatIn), true);
        PySeat.Link link = new PySeat.Link(seatIn, new PipedOutputStream(fromSeat));
        List<String> labels = Collections.synchronizedList(new ArrayList<>());
        Thread python = new Thread(() -> {  // attacks Kaito when offered, then DONE
            try (BufferedReader r = new BufferedReader(new InputStreamReader(fromSeat))) {
                for (String line; (line = r.readLine()) != null; ) {
                    JsonObject m = JsonParser.parseString(line).getAsJsonObject();
                    JsonArray opts = m.getAsJsonArray("options");
                    int pick = 0;
                    for (int i = 0; i < opts.size(); i++) {
                        String label = opts.get(i).getAsJsonObject().get("label").getAsString();
                        labels.add(label);
                        if (label.endsWith("attacks Kaito, Bane of Nightmares")) pick = i;
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
        mage.game.match.Match match = new TwoPlayerMatch(new mage.game.match.MatchOptions("planeswalker attack check", "Two Player Duel", false));
        for (mage.players.Player p : new mage.players.Player[]{py, ai}) {
            p.setTestMode(true);
            mage.cards.decks.Deck deck = new mage.cards.decks.Deck();
            game.addPlayer(p, deck);
            match.addPlayer(p, deck);
        }
        Permanent beastie = ManaCheck.put(game, "Bashful Beastie", py.getId());
        Permanent kaito = ManaCheck.put(game, "Kaito, Bane of Nightmares", ai.getId());
        kaito.addCounters(CounterType.LOYALTY.createInstance(4), ai.getId(), null, game);
        for (mage.players.Player p : new mage.players.Player[]{py, ai}) p.beginTurn(game);
        game.getState().setActivePlayerId(py.getId());
        Phase combat = game.getState().getTurn().getPhase(TurnPhase.COMBAT);
        combat.setStep(new mage.game.turn.DeclareAttackersStep());
        game.getState().getTurn().setPhase(combat);
        game.applyEffects();
        game.getCombat().clear();
        game.getCombat().setAttacker(py.getId());
        game.getCombat().setDefenders(game);
        py.selectAttackers(game, py.getId());
        UUID defender = game.getCombat().getDefenderId(beastie.getId());
        System.out.println("options seen " + labels);
        System.out.println("Kaito is a creature now: " + kaito.isCreature(game) + "; Beastie attacking " + beastie.isAttacking()
                + " at " + (defender == null ? null : defender.equals(kaito.getId()) ? "Kaito" : defender.equals(ai.getId()) ? "the opponent" : defender));
        boolean ok = beastie.isAttacking() && kaito.getId().equals(defender)
                && labels.stream().anyMatch(l -> l.equals("Bashful Beastie attacks"));
        System.out.println(ok ? "PASS" : "FAIL");
        System.exit(ok ? 0 : 1);
    }
}
