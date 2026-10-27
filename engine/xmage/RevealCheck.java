import com.google.gson.*;
import mage.cards.Card;
import mage.cards.CardsImpl;
import mage.constants.*;
import mage.game.*;
import mage.game.mulligan.MulliganType;
import mage.game.turn.Phase;
import mage.player.ai.ComputerPlayer7;
import mage.players.Player;
import java.util.*;

/**
 * Regression check: a card the opponent reveals from its hand stays visible to this seat while it stays in that hand.
 * XMage empties its game-wide revealed map at every priority and update event, so the card used to vanish from the
 * observation before this seat's next decision (and a reveal cleared before any decision was never seen at all).
 * Opponent's hand: Glimmerburst, Jump Scare, Bashful Beastie, Enduring Vitality. Glimmerburst is revealed while an
 * observation is built, Jump Scare is revealed and cleared with no observation in between; both must show as
 * zone HAND, revealed:true after priority and update events. Bashful Beastie, never revealed, must never show.
 * Then Glimmerburst is shuffled into the library and put back into the hand (a new object: must not show), Jump Scare
 * is discarded (must not show), Overgrown Zealot is revealed from the library and put into the hand (must show: a
 * reveal is to every player), and Enduring Vitality is revealed and the turn rolled back (must
 * not show).
 * Then Jump Scare goes from the graveyard back to the hand and a second Bashful Beastie is bounced from the battlefield:
 * both public moves, so both show as HAND revealed (the first, never-revealed Bashful Beastie still not).
 * Every observation must pass the leak checks. Prints PASS or FAIL and exits 1 on FAIL.
 */
public class RevealCheck {
    static final List<String> failures = new ArrayList<>();

    static void expect(boolean ok, String what) {
        System.out.println((ok ? "  ok   " : "  FAIL ") + what);
        if (!ok) failures.add(what);
    }

    /** Observation entries naming this card: "zone[ revealed]" each. */
    static List<String> shown(JsonObject json, String name) {
        List<String> out = new ArrayList<>();
        for (JsonElement el : json.getAsJsonArray("entries")) {
            JsonObject e = el.getAsJsonObject();
            if (e.has("name") && name.equals(e.get("name").getAsString()))
                out.add(e.get("zone").getAsString() + (e.has("revealed") && e.get("revealed").getAsBoolean() ? " revealed" : "")
                        + (e.get("mine").getAsBoolean() ? " mine" : ""));
        }
        return out;
    }

    static Observer.Obs observe(Game game, Player me, String label) {
        Observer.Obs obs = Observer.build(game, me.getId(), null);
        List<String> leaks = new ArrayList<>(obs.violations);
        leaks.addAll(Observer.scanText(obs.json.toString(), game, obs));
        System.out.println(label);
        expect(leaks.isEmpty(), "no leaks " + leaks);
        return obs;
    }

    public static void main(String[] args) throws Exception {
        mage.cards.repository.RepositoryUtil.bootstrapLocalDb();
        mage.cards.repository.CardScanner.scan();
        Game game = new TwoPlayerDuel(MultiplayerAttackOption.LEFT, RangeOfInfluence.ONE, MulliganType.GAME_DEFAULT.getMulligan(0), 40, 20, 7);
        GameOptions options = new GameOptions();
        options.rollbackTurnsAllowed = true;
        game.setGameOptions(options);
        ComputerPlayer7 me = new ComputerPlayer7("ME", RangeOfInfluence.ONE, 2);
        ComputerPlayer7 opp = new ComputerPlayer7("OPP", RangeOfInfluence.ONE, 2);
        mage.game.match.Match match = new TwoPlayerMatch(new mage.game.match.MatchOptions("reveal check", "Two Player Duel", false));
        for (Player p : new Player[]{me, opp}) {
            p.setTestMode(true);
            mage.cards.decks.Deck deck = new mage.cards.decks.Deck();
            game.addPlayer(p, deck);
            match.addPlayer(p, deck);
        }
        Map<String, Card> c = new LinkedHashMap<>();
        for (String n : new String[]{"Glimmerburst", "Jump Scare", "Bashful Beastie", "Enduring Vitality"}) {
            Card card = ManaCheck.make(game, n, opp.getId());
            opp.getHand().add(card);
            game.getState().setZone(card.getId(), Zone.HAND);
            c.put(n, card);
        }
        Card mine = ManaCheck.make(game, "Murder", me.getId());
        me.getHand().add(mine);
        game.getState().setZone(mine.getId(), Zone.HAND);
        for (Player p : new Player[]{me, opp}) p.beginTurn(game);
        game.getState().setActivePlayerId(me.getId());
        Phase main = game.getState().getTurn().getPhase(TurnPhase.PRECOMBAT_MAIN);
        main.setStep(new mage.game.turn.PreCombatMainStep());
        game.getState().getTurn().setPhase(main);
        game.applyEffects();

        Observer.Obs o = observe(game, me, "before any reveal");
        for (String n : c.keySet()) expect(shown(o.json, n).isEmpty(), n + " not shown: " + shown(o.json, n));
        expect(shown(o.json, "Murder").equals(List.of("HAND mine")), "my own hand card shown: " + shown(o.json, "Murder"));

        opp.revealCards("check", new CardsImpl(c.get("Glimmerburst")), game);
        o = observe(game, me, "while Glimmerburst is revealed");
        expect(shown(o.json, "Glimmerburst").equals(List.of("REVEALED")), "Glimmerburst is a REVEALED entry: " + shown(o.json, "Glimmerburst"));

        game.firePriorityEvent(me.getId());
        expect(game.getState().getRevealed().isEmpty(), "the priority event emptied XMage's revealed map");
        opp.revealCards("check", new CardsImpl(c.get("Jump Scare")), game);
        game.fireUpdatePlayersEvent();  // cleared with no observation built in between
        expect(game.getState().getRevealed().isEmpty(), "the update event emptied XMage's revealed map");
        game.firePriorityEvent(opp.getId());
        o = observe(game, me, "after priority and update events");
        expect(shown(o.json, "Glimmerburst").equals(List.of("HAND revealed")), "Glimmerburst stays as HAND revealed: " + shown(o.json, "Glimmerburst"));
        expect(shown(o.json, "Jump Scare").equals(List.of("HAND revealed")), "Jump Scare (cleared unseen) shows as HAND revealed: " + shown(o.json, "Jump Scare"));
        expect(shown(o.json, "Bashful Beastie").isEmpty(), "never-revealed Bashful Beastie not shown: " + shown(o.json, "Bashful Beastie"));
        expect(shown(o.json, "Enduring Vitality").isEmpty(), "never-revealed Enduring Vitality not shown");
        Observer.Obs asOpp = observe(game, opp, "the revealing player's own view");
        expect(shown(asOpp.json, "Glimmerburst").equals(List.of("HAND mine")), "opponent sees its own card once, as its hand: " + shown(asOpp.json, "Glimmerburst"));

        opp.shuffleCardsToLibrary(c.get("Glimmerburst"), game, null);
        opp.discard(c.get("Jump Scare"), false, null, game);
        game.fireUpdatePlayersEvent();
        o = observe(game, me, "after Glimmerburst is shuffled away and Jump Scare discarded");
        expect(shown(o.json, "Glimmerburst").isEmpty(), "Glimmerburst in the library not shown: " + shown(o.json, "Glimmerburst"));
        expect(shown(o.json, "Jump Scare").equals(List.of("GRAVEYARD")), "Jump Scare only in the graveyard: " + shown(o.json, "Jump Scare"));

        opp.moveCards(c.get("Glimmerburst"), Zone.HAND, null, game);
        expect(opp.getHand().contains(c.get("Glimmerburst").getId()), "Glimmerburst is back in the opponent's hand");
        o = observe(game, me, "after Glimmerburst returns to the hand (a new object)");
        expect(shown(o.json, "Glimmerburst").isEmpty(), "Glimmerburst back in hand not shown: " + shown(o.json, "Glimmerburst"));

        // revealed from the library to everyone, then put into the hand: public, so known
        Card top = ManaCheck.make(game, "Overgrown Zealot", opp.getId());
        opp.getLibrary().putOnTop(top, game);
        game.getState().setZone(top.getId(), Zone.LIBRARY);
        opp.revealCards("check", new CardsImpl(top), game);
        opp.moveCards(top, Zone.HAND, null, game);
        game.fireUpdatePlayersEvent();
        o = observe(game, me, "after Overgrown Zealot is revealed from the library and put into the hand");
        expect(opp.getHand().contains(top.getId()), "Overgrown Zealot is in the opponent's hand");
        // revealed to every player, so known in the hand (2026-10-27)
        expect(shown(o.json, "Overgrown Zealot").equals(List.of("HAND revealed")), "Overgrown Zealot, revealed from the library, shows as HAND revealed: " + shown(o.json, "Overgrown Zealot"));

        // a public card that goes back to the hand is known (2026-10-27): Jump Scare from the graveyard, a permanent bounced
        opp.moveCards(c.get("Jump Scare"), Zone.HAND, null, game);
        game.fireUpdatePlayersEvent();
        o = observe(game, me, "after Jump Scare returns from the graveyard to the hand");
        expect(shown(o.json, "Jump Scare").equals(List.of("HAND revealed")), "Jump Scare back from the graveyard shows as HAND revealed: " + shown(o.json, "Jump Scare"));
        Card bear = ManaCheck.make(game, "Bashful Beastie", opp.getId());
        opp.moveCards(bear, Zone.BATTLEFIELD, null, game);
        o = observe(game, me, "with a second Bashful Beastie on the battlefield");
        opp.moveCards(game.getPermanent(bear.getId()) != null ? game.getCard(bear.getId()) : bear, Zone.HAND, null, game);
        game.fireUpdatePlayersEvent();
        o = observe(game, me, "after that Bashful Beastie is bounced to the hand");
        expect(shown(o.json, "Bashful Beastie").equals(List.of("HAND revealed")), "the bounced Bashful Beastie shows as HAND revealed, the never-revealed one not: " + shown(o.json, "Bashful Beastie"));

        // a reveal in a turn that is then rolled back did not happen
        game.getState().setTurnNum(2);
        ((GameImpl) game).saveRollBackGameState();
        opp.revealCards("check", new CardsImpl(c.get("Enduring Vitality")), game);
        game.fireUpdatePlayersEvent();
        o = observe(game, me, "Enduring Vitality revealed in turn 2");
        expect(shown(o.json, "Enduring Vitality").equals(List.of("HAND revealed")), "Enduring Vitality shows as HAND revealed: " + shown(o.json, "Enduring Vitality"));
        // XMage runs a requested rollback from its game loop, which this check doesn't run: call that step directly
        java.lang.reflect.Method rollback = GameImpl.class.getDeclaredMethod("rollbackTurnsExecution", int.class);
        rollback.setAccessible(true);
        java.lang.reflect.Field players = GameImpl.class.getDeclaredField("playerList");  // set by start(), not run here
        players.setAccessible(true);
        players.set(game, game.getState().getPlayerList());
        rollback.invoke(game, 2);
        expect(game.getPlayer(opp.getId()).getHand().contains(c.get("Enduring Vitality").getId()), "Enduring Vitality still in the opponent's hand after the rollback");
        o = observe(game, me, "after rolling back to the start of turn 2");
        expect(shown(o.json, "Enduring Vitality").isEmpty(), "Enduring Vitality forgotten after the rollback: " + shown(o.json, "Enduring Vitality"));

        Observer.forget(game);
        System.out.println(failures.isEmpty() ? "PASS" : "FAIL " + failures);
        System.exit(failures.isEmpty() ? 0 : 1);
    }
}
