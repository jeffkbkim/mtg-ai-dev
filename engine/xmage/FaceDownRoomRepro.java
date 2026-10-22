import mage.abilities.*;
import mage.cards.Card;
import mage.constants.*;
import mage.game.*;
import mage.game.permanent.Permanent;
import java.util.*;
/**
 * Reproduces an XMage 1.4.62 bug (see README, Known XMage bugs): a Room that is manifested face down keeps both
 * doors' abilities, locked ones included. A face-down Ticket Booth // Tunnel of Hate still has Tunnel of Hate's
 * "Whenever you attack, target attacking creature gains double strike" (seen deciding a combat in a Claude game,
 * plan-pairs batch01 part11 game1). Prints the face-down permanent's abilities, then BUG PRESENT or FIXED.
 */
public class FaceDownRoomRepro {
    public static void main(String[] a) throws Exception {
        mage.cards.repository.RepositoryUtil.bootstrapLocalDb();
        mage.cards.repository.CardScanner.scan();
        PySeat.Link link = ManaCheck.link();
        Game game = new TwoPlayerDuel(MultiplayerAttackOption.LEFT, RangeOfInfluence.ONE, mage.game.mulligan.MulliganType.GAME_DEFAULT.getMulligan(0), 40, 20, 7);
        PySeat py = new PySeat("PY", link);
        mage.player.ai.ComputerPlayer7 ai = new mage.player.ai.ComputerPlayer7("AI", RangeOfInfluence.ONE, 2);
        mage.game.match.Match match = new TwoPlayerMatch(new mage.game.match.MatchOptions("face-down room repro", "Two Player Duel", false));
        for (mage.players.Player p : new mage.players.Player[]{py, ai}) { p.setTestMode(true); mage.cards.decks.Deck d = new mage.cards.decks.Deck(); game.addPlayer(p, d); match.addPlayer(p, d); }
        for (mage.players.Player p : new mage.players.Player[]{py, ai}) p.beginTurn(game);
        game.getState().setActivePlayerId(py.getId());
        Card room = ManaCheck.make(game, "Ticket Booth // Tunnel of Hate", py.getId());
        py.getLibrary().putOnTop(room, game);
        Card src = ManaCheck.make(game, "Murder", py.getId());
        Ability sa = src.getSpellAbility(); sa.setControllerId(py.getId());
        List<Permanent> made = mage.abilities.effects.keyword.ManifestEffect.doManifestCards(game, sa, py, new HashSet<>(Collections.singletonList(room)));
        game.applyEffects();
        Permanent p = made.get(0);
        System.out.println("face down " + p.isFaceDown(game) + ", " + p.getPower().getValue() + "/" + p.getToughness().getValue());
        int doorAbilities = 0;
        for (Ability ab : p.getAbilities(game)) {
            System.out.println("ability on the face-down permanent: " + ab.getClass().getSimpleName() + ": " + ab.getRule());
            if (ab instanceof TriggeredAbility) doorAbilities++;
        }
        System.out.println(doorAbilities > 0 ? "BUG PRESENT" : "FIXED");
        System.exit(0);
    }
}
