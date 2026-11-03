import com.google.gson.*;
import mage.constants.*;
import mage.game.*;
import mage.game.combat.CombatGroup;
import mage.game.mulligan.MulliganType;
import mage.game.permanent.Permanent;
import mage.game.turn.Phase;
import mage.player.ai.ComputerPlayer7;
import java.io.*;
import java.util.*;

/**
 * Regression check: an attacker blocked by two creatures lets its player divide the damage. The seat let XMage's AI
 * answer this silently (lethal damage to each blocker in order), so damage among blockers was never asked (data
 * batches 2026-10-30/31). Two boards on our turn: Bashful Beastie (5/4) blocked by Friendly Teddy (2/2) and Soul
 * Rat (1/1), where the player gives Teddy 1 and so the Rat 4, which XMage's AI never would; then Fear of Exposure
 * (5/4 trample) blocked by the same two, where the player assigns the least it may (lethal: 2 and 1) and 2 tramples
 * over. Prints PASS or FAIL and exits 1 on FAIL.
 */
public class DamageCheck {
    public static void main(String[] args) throws Exception {
        mage.cards.repository.RepositoryUtil.bootstrapLocalDb();
        mage.cards.repository.CardScanner.scan();
        boolean ok = run("Bashful Beastie", 1, 4, 0) & run("Fear of Exposure", 2, 1, 2);
        System.out.println(ok ? "PASS" : "FAIL");
        System.exit(ok ? 0 : 1);
    }

    /** Teddy and the Rat block the attacker; the player's picks should leave this much damage on each and trample over this much. */
    static boolean run(String attackerName, int teddyWant, int ratWant, int trampleWant) throws Exception {
        PipedInputStream seatIn = new PipedInputStream(), fromSeat = new PipedInputStream();
        PrintWriter toSeat = new PrintWriter(new PipedOutputStream(seatIn), true);
        PySeat.Link link = new PySeat.Link(seatIn, new PipedOutputStream(fromSeat));
        List<String> asked = Collections.synchronizedList(new ArrayList<>());
        Thread python = new Thread(() -> {  // non-trample: 1 to Teddy; otherwise the least offered
            try (BufferedReader r = new BufferedReader(new InputStreamReader(fromSeat))) {
                for (String line; (line = r.readLine()) != null; ) {
                    JsonObject m = JsonParser.parseString(line).getAsJsonObject();
                    JsonArray opts = m.getAsJsonArray("options");
                    int pick = 0;
                    List<String> labels = new ArrayList<>();
                    for (int i = 0; i < opts.size(); i++) {
                        String label = opts.get(i).getAsJsonObject().get("label").getAsString();
                        labels.add(label);
                        if (label.equals("1 damage to Friendly Teddy")) pick = i;
                    }
                    asked.add(m.get("kind").getAsString() + " " + m.get("prompt").getAsString() + " " + labels);
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
        mage.game.match.Match match = new TwoPlayerMatch(new mage.game.match.MatchOptions("damage check", "Two Player Duel", false));
        for (mage.players.Player p : new mage.players.Player[]{py, ai}) {
            p.setTestMode(true);
            mage.cards.decks.Deck deck = new mage.cards.decks.Deck();
            game.addPlayer(p, deck);
            match.addPlayer(p, deck);
        }
        Permanent attacker = ManaCheck.put(game, attackerName, py.getId());
        Permanent teddy = ManaCheck.put(game, "Friendly Teddy", ai.getId());
        Permanent rat = ManaCheck.put(game, "Innocuous Rat", ai.getId());
        for (mage.players.Player p : new mage.players.Player[]{py, ai}) p.beginTurn(game);
        game.getState().setActivePlayerId(py.getId());
        Phase combat = game.getState().getTurn().getPhase(TurnPhase.COMBAT);
        combat.setStep(new mage.game.turn.CombatDamageStep(false));
        game.getState().getTurn().setPhase(combat);
        game.applyEffects();
        game.getCombat().clear();
        game.getCombat().setAttacker(py.getId());
        game.getCombat().setDefenders(game);
        if (!game.getCombat().declareAttacker(attacker.getId(), ai.getId(), py.getId(), game)) throw new IllegalStateException("could not attack");
        CombatGroup group = game.getCombat().getGroups().get(0);
        group.addBlocker(teddy.getId(), ai.getId(), game);
        group.addBlocker(rat.getId(), ai.getId(), game);
        group.setBlocked(true, game);
        int lifeBefore = ai.getLife();
        group.assignDamageToBlockers(false, game);
        for (Permanent p : game.getBattlefield().getAllActivePermanents()) p.applyDamage(game);
        int trample = lifeBefore - ai.getLife();
        System.out.println(attackerName + ": asked " + asked);
        System.out.println("  damage on Teddy " + teddy.getDamage() + " (want " + teddyWant + "), Rat " + rat.getDamage()
                + " (want " + ratWant + "); trampled over " + trample + " (want " + trampleWant + ")");
        return !asked.isEmpty() && teddy.getDamage() == teddyWant && rat.getDamage() == ratWant && trample == trampleWant;
    }
}
