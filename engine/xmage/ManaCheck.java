import mage.abilities.SpellAbility;
import mage.abilities.costs.mana.ManaCost;
import mage.abilities.costs.mana.ManaCostsImpl;
import mage.cards.Card;
import mage.cards.repository.*;
import mage.constants.*;
import mage.game.*;
import mage.game.mulligan.MulliganType;
import mage.game.permanent.Permanent;
import mage.game.permanent.PermanentCard;
import mage.player.ai.ComputerPlayer7;
import java.io.*;
import java.util.*;

/**
 * Regression check for automatic mana payment: our seat must not tap a creature for mana while lands can pay.
 * XMage's ComputerPlayer scores each mana source and taps the lowest first; a dual land (two mana abilities) ties with
 * a creature that Enduring Vitality lets tap for any colour, and ties break in hash order, so the reviewer saw an
 * Insect token tapped for an equip cost while Strangled Cemetery stayed untapped (and the creature then couldn't
 * block). Each trial builds a fresh board (Enduring Vitality, 3 Bashful Beastie, 2 Strangled Cemetery, 2 Forest) and
 * pays {4}, which the lands cover; then pays {6}, which needs two creatures. Prints PASS or FAIL and exits 1 on FAIL.
 */
public class ManaCheck {
    static Card make(Game game, String name, UUID owner) {
        Card c = CardRepository.instance.findCards(new CardCriteria().setCodes("DSK").name(name)).get(0).createCard();
        game.loadCards(new HashSet<>(Collections.singletonList(c)), owner);
        return c;
    }

    static Permanent put(Game game, String name, UUID owner) {
        Card c = make(game, name, owner);
        PermanentCard perm = new PermanentCard(c, owner, game);
        game.addPermanent(perm, 0);
        game.getState().setZone(c.getId(), Zone.BATTLEFIELD);
        perm.removeSummoningSickness();
        return perm;
    }

    /** [creatures tapped, lands left untapped, paid?] after paying cost on a fresh board. */
    static int[] trial(String cost) throws IOException {
        PySeat.Link link = new PySeat.Link(new PipedInputStream(new PipedOutputStream()), new ByteArrayOutputStream());
        Game game = new TwoPlayerDuel(MultiplayerAttackOption.LEFT, RangeOfInfluence.ONE, MulliganType.GAME_DEFAULT.getMulligan(0), 40, 20, 7);
        PySeat py = new PySeat("PY", link);
        ComputerPlayer7 ai = new ComputerPlayer7("AI", RangeOfInfluence.ONE, 2);
        mage.game.match.Match match = new TwoPlayerMatch(new mage.game.match.MatchOptions("mana check", "Two Player Duel", false));
        for (mage.players.Player p : new mage.players.Player[]{py, ai}) {
            p.setTestMode(true);
            mage.cards.decks.Deck deck = new mage.cards.decks.Deck();
            game.addPlayer(p, deck);
            match.addPlayer(p, deck);
        }
        List<Permanent> board = new ArrayList<>();
        for (String n : new String[]{"Enduring Vitality", "Bashful Beastie", "Bashful Beastie", "Bashful Beastie",
                "Strangled Cemetery", "Strangled Cemetery", "Forest", "Forest"})
            board.add(put(game, n, py.getId()));
        for (mage.players.Player p : new mage.players.Player[]{py, ai}) p.beginTurn(game);
        game.getState().setActivePlayerId(py.getId());
        game.applyEffects();
        Card spell = make(game, "Murder", py.getId());  // any spell of ours to pay for
        SpellAbility sa = spell.getSpellAbility();
        sa.setControllerId(py.getId());
        boolean paid = new ManaCostsImpl<ManaCost>(cost).pay(sa, game, sa, py.getId(), false, null);
        int creaturesTapped = 0, landsUntapped = 0;
        for (Permanent p : board) {
            if (p.isCreature(game) && p.isTapped()) creaturesTapped++;
            if (p.isLand(game) && !p.isTapped()) landsUntapped++;
        }
        return new int[]{creaturesTapped, landsUntapped, paid ? 1 : 0};
    }

    public static void main(String[] args) throws Exception {
        RepositoryUtil.bootstrapLocalDb();
        CardScanner.scan();
        int trials = 20, badFour = 0, unpaid = 0, badSix = 0;
        for (int t = 0; t < trials; t++) {
            int[] r = trial("{4}");
            if (r[2] == 0) unpaid++;
            else if (r[0] > 0) badFour++;
            int[] s = trial("{6}");
            if (s[2] == 0) unpaid++;
            else if (s[0] != 2 || s[1] != 0) badSix++;
        }
        System.out.println("{4} with 4 lands: a creature was tapped in " + badFour + "/" + trials + " trials");
        System.out.println("{6} with 4 lands: not exactly 4 lands + 2 creatures in " + badSix + "/" + trials + " trials; unpaid " + unpaid);
        boolean ok = badFour == 0 && badSix == 0 && unpaid == 0;
        System.out.println(ok ? "PASS" : "FAIL");
        System.exit(ok ? 0 : 1);
    }
}
