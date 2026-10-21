import com.google.gson.*;
import mage.abilities.SpellAbility;
import mage.cards.Card;
import mage.constants.*;
import mage.game.*;
import mage.game.mulligan.MulliganType;
import mage.player.ai.ComputerPlayer7;
import mage.target.common.TargetCreaturePermanent;
import java.io.*;
import java.util.*;

/**
 * Regression check: choosing "one or two" targets, picking one and then DONE must take exactly two prompts. XMage
 * calls chooseTarget again whenever the previous call added a target, so DONE used to be asked a second time (the
 * reviewer saw it in crew, Coordinated Clobbering, Elegant Rotunda, Get Out and Untimely Malfunction prompts).
 * Prints PASS or FAIL and exits 1 on FAIL.
 */
public class TargetCheck {
    public static void main(String[] args) throws Exception {
        mage.cards.repository.RepositoryUtil.bootstrapLocalDb();
        mage.cards.repository.CardScanner.scan();
        PipedInputStream seatIn = new PipedInputStream(), fromSeat = new PipedInputStream();
        PrintWriter toSeat = new PrintWriter(new PipedOutputStream(seatIn), true);
        PySeat.Link link = new PySeat.Link(seatIn, new PipedOutputStream(fromSeat));
        List<String> asked = Collections.synchronizedList(new ArrayList<>());
        Thread python = new Thread(() -> {  // picks the first creature, then DONE whenever DONE is offered
            try (BufferedReader r = new BufferedReader(new InputStreamReader(fromSeat))) {
                for (String line; (line = r.readLine()) != null; ) {
                    JsonObject m = JsonParser.parseString(line).getAsJsonObject();
                    JsonArray opts = m.getAsJsonArray("options");
                    asked.add(m.get("kind").getAsString() + " " + m.get("prompt").getAsString() + " " + opts.size() + " options");
                    toSeat.println("{\"choice\":0}");  // DONE is listed first when it is offered
                }
            } catch (IOException ignored) { }
        });
        python.setDaemon(true);
        python.start();

        Game game = new TwoPlayerDuel(MultiplayerAttackOption.LEFT, RangeOfInfluence.ONE, MulliganType.GAME_DEFAULT.getMulligan(0), 40, 20, 7);
        PySeat py = new PySeat("PY", link);
        ComputerPlayer7 ai = new ComputerPlayer7("AI", RangeOfInfluence.ONE, 2);
        mage.game.match.Match match = new TwoPlayerMatch(new mage.game.match.MatchOptions("target check", "Two Player Duel", false));
        for (mage.players.Player p : new mage.players.Player[]{py, ai}) {
            p.setTestMode(true);
            mage.cards.decks.Deck deck = new mage.cards.decks.Deck();
            game.addPlayer(p, deck);
            match.addPlayer(p, deck);
        }
        for (int i = 0; i < 3; i++) ManaCheck.put(game, "Bashful Beastie", ai.getId());
        for (mage.players.Player p : new mage.players.Player[]{py, ai}) p.beginTurn(game);
        game.getState().setActivePlayerId(py.getId());
        Card spell = ManaCheck.make(game, "Murder", py.getId());
        SpellAbility sa = spell.getSpellAbility();
        sa.setControllerId(py.getId());
        TargetCreaturePermanent target = new TargetCreaturePermanent(1, 2);
        boolean chosen = target.chooseTarget(Outcome.Damage, py.getId(), sa, game);
        Thread.sleep(300);
        System.out.println("prompts " + asked);
        System.out.println("chosen " + chosen + ", targets " + target.getTargets().size());
        boolean ok = chosen && target.getTargets().size() == 1 && asked.size() == 2;
        System.out.println(ok ? "PASS" : "FAIL");
        System.exit(ok ? 0 : 1);
    }
}
