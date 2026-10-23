import mage.abilities.Ability;
import mage.abilities.TriggeredAbility;
import mage.cards.Card;
import mage.constants.*;
import mage.game.*;
import mage.game.mulligan.MulliganType;
import mage.game.permanent.Permanent;
import mage.player.ai.ComputerPlayer7;

/**
 * Regression check for our patched VeteranSurvivor.java: after its Survival trigger has exiled three cards, Veteran
 * Survivor must be 5/4 with hexproof. In XMage 1.4.62 the static ability counted a different exile zone than the one
 * the trigger used, so it stayed 2/1 and could be targeted (the reviewer saw it exile three cards in a batch-1 game,
 * then die to Scorching Dragonfire). Veteran Survivor enters from hand; its trigger resolves three times, each
 * exiling a card from the opponent's graveyard. Prints PASS or FAIL and exits 1 on FAIL.
 */
public class VeteranSurvivorCheck {
    public static void main(String[] args) throws Exception {
        mage.cards.repository.RepositoryUtil.bootstrapLocalDb();
        mage.cards.repository.CardScanner.scan();
        Game game = new TwoPlayerDuel(MultiplayerAttackOption.LEFT, RangeOfInfluence.ONE, MulliganType.GAME_DEFAULT.getMulligan(0), 40, 20, 7);
        game.setGameOptions(new GameOptions());
        ComputerPlayer7 me = new ComputerPlayer7("ME", RangeOfInfluence.ONE, 2), opp = new ComputerPlayer7("OPP", RangeOfInfluence.ONE, 2);
        mage.game.match.Match match = new TwoPlayerMatch(new mage.game.match.MatchOptions("veteran survivor check", "Two Player Duel", false));
        for (mage.players.Player p : new mage.players.Player[]{me, opp}) {
            p.setTestMode(true);
            mage.cards.decks.Deck deck = new mage.cards.decks.Deck();
            game.addPlayer(p, deck);
            match.addPlayer(p, deck);
        }
        Card survivor = ManaCheck.make(game, "Veteran Survivor", me.getId());
        me.getHand().add(survivor);
        game.getState().setZone(survivor.getId(), Zone.HAND);
        for (mage.players.Player p : new mage.players.Player[]{me, opp}) p.beginTurn(game);
        game.getState().setActivePlayerId(me.getId());
        me.moveCards(survivor, Zone.BATTLEFIELD, null, game);  // entering changes its zone change counter, as a cast does
        game.applyEffects();
        Permanent perm = game.getPermanent(survivor.getId());
        perm.setTapped(true);  // Survival: "if this creature is tapped", checked again on resolution
        TriggeredAbility survival = null;
        for (Ability a : perm.getAbilities()) if (a instanceof TriggeredAbility) survival = (TriggeredAbility) a;
        for (String name : new String[]{"Plains", "Island", "Swamp"}) {
            Card dead = ManaCheck.make(game, name, opp.getId());
            opp.getGraveyard().add(dead);
            game.getState().setZone(dead.getId(), Zone.GRAVEYARD);
            TriggeredAbility t = (TriggeredAbility) survival.copy();  // as the trigger goes on the stack
            t.newId();
            t.setControllerId(me.getId());
            t.initSourceObjectZoneChangeCounter(game, true);
            t.getTargets().get(0).add(dead.getId(), game);
            t.resolve(game);
            game.applyEffects();
        }
        int exiled = game.getExile().getAllCards(game).size();
        int power = perm.getPower().getValue(), toughness = perm.getToughness().getValue();
        boolean hexproof = perm.getAbilities(game).containsClass(mage.abilities.keyword.HexproofAbility.class);
        System.out.println("exiled " + exiled + "; Veteran Survivor " + power + "/" + toughness + (hexproof ? " with" : " without") + " hexproof (want 5/4 with)");
        boolean ok = exiled == 3 && power == 5 && toughness == 4 && hexproof;
        System.out.println(ok ? "PASS" : "FAIL");
        System.exit(ok ? 0 : 1);
    }
}
