import mage.cards.Card;
import mage.cards.repository.*;
import mage.constants.*;
import mage.game.*;
import mage.game.mulligan.MulliganType;
import mage.game.permanent.PermanentCard;
import mage.player.ai.ComputerPlayer7;
import mage.players.Player;
import java.util.*;

/**
 * Builds a combat board directly and asks XMage's AI to block, to chase the soak's "AI can't find good blocker
 * combination" crash deterministically. Our seat attacks; a stand-in for Python records any question it gets.
 *
 *   java ... BlockCheck <fastFail true|false> <attacker>... vs <untapped blocker>...
 *   java ... BlockCheck true "Irreverent Gremlin" "Screaming Nemesis" vs "Bashful Beastie"   # soak run 349's board
 * Prints the blocks and PASS when the AI blocks legally without crashing. None of the soak boards tried so far
 * crash here, so the crash needs more than the board (see experiments/coverage_soak/results-2026-10-20.md).
 */
public class BlockCheck {
    static PermanentCard put(Game game, String name, Player owner) {
        Card c = CardRepository.instance.findCards(new CardCriteria().setCodes("DSK").name(name)).get(0).createCard();
        game.loadCards(new HashSet<>(Collections.singletonList(c)), owner.getId());
        PermanentCard p = new PermanentCard(c, owner.getId(), game);
        game.addPermanent(p, 0);
        game.getState().setZone(c.getId(), Zone.BATTLEFIELD);
        p.removeSummoningSickness();
        return p;
    }

    public static void main(String[] args) throws Exception {
        boolean fastFail = Boolean.parseBoolean(args[0]);
        RepositoryUtil.bootstrapLocalDb();
        CardScanner.scan();
        Game game = new TwoPlayerDuel(MultiplayerAttackOption.LEFT, RangeOfInfluence.ONE, MulliganType.GAME_DEFAULT.getMulligan(0), 40, 20, 7);
        GameOptions options = new GameOptions();
        options.testMode = false;
        game.setGameOptions(options);
        mage.game.match.Match match = new TwoPlayerMatch(new mage.game.match.MatchOptions("block check", "Two Player Duel", false));
        // our seat attacks; a stand-in for Python answers in-process and records every question it gets
        java.io.PipedInputStream seatIn = new java.io.PipedInputStream(), fromSeat = new java.io.PipedInputStream();
        java.io.PrintWriter toSeat = new java.io.PrintWriter(new java.io.PipedOutputStream(seatIn), true);
        PySeat.Link link = new PySeat.Link(seatIn, new java.io.PipedOutputStream(fromSeat));
        List<String> asked = Collections.synchronizedList(new ArrayList<>());
        Thread python = new Thread(() -> {
            try (java.io.BufferedReader r = new java.io.BufferedReader(new java.io.InputStreamReader(fromSeat))) {
                for (String line; (line = r.readLine()) != null; ) {
                    com.google.gson.JsonObject m = com.google.gson.JsonParser.parseString(line).getAsJsonObject();
                    asked.add(m.get("kind").getAsString() + ": " + m.get("prompt").getAsString());
                    toSeat.println("{\"choice\":0}");
                }
            } catch (java.io.IOException ignored) { }
        });
        python.setDaemon(true);
        python.start();
        PySeat us = new PySeat("PY", link);
        ComputerPlayer7 ai = new ComputerPlayer7("AI", RangeOfInfluence.ONE, 2);
        ai.setMaxThinkTimeSecs(1);
        for (Player p : new Player[]{us, ai}) {
            p.setTestMode(true);
            p.setFastFailInTestMode(fastFail);
            mage.cards.decks.Deck deck = new mage.cards.decks.Deck();
            game.addPlayer(p, deck);
            match.addPlayer(p, deck);
        }
        // args[1..]: attackers, "vs", untapped blockers
        List<String> rest = Arrays.asList(args).subList(1, args.length);
        int vs = rest.indexOf("vs");
        List<PermanentCard> attackers = new ArrayList<>();
        for (String n : rest.subList(0, vs)) attackers.add(put(game, n, us));
        for (String n : rest.subList(vs + 1, rest.size())) put(game, n, ai);
        for (Player p : new Player[]{us, ai}) p.beginTurn(game);  // fills each player's range
        game.getState().setActivePlayerId(us.getId());

        game.getCombat().clear();
        game.getCombat().setAttacker(us.getId());
        game.getCombat().setDefenders(game);
        for (PermanentCard a : attackers) {
            if (!game.getCombat().declareAttacker(a.getId(), ai.getId(), us.getId(), game)) throw new IllegalStateException("could not attack with " + a.getName());
        }
        String outcome;
        try {
            game.getCombat().selectBlockers(null, null, game);
            outcome = "no crash";
        } catch (IllegalArgumentException e) {
            outcome = "crash: " + e.getMessage();
        }
        List<String> blocks = new ArrayList<>();
        for (mage.game.combat.CombatGroup g : game.getCombat().getGroups())
            for (UUID b : g.getBlockers()) blocks.add(game.getPermanent(b).getName() + " blocks " + game.getPermanent(g.getAttackers().get(0)).getName());
        boolean legal = game.getCombat().checkBlockRestrictions(ai, game);
        System.out.println("fast-fail " + fastFail + ": " + outcome + "; blocks " + blocks + "; blocks legal " + legal);
        System.out.println("our seat was asked during the AI's blocking: " + asked);
        boolean ok = outcome.equals("no crash") && legal;
        System.out.println(ok ? "PASS" : "FAIL");
        System.exit(ok ? 0 : 1);
    }
}
