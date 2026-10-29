import mage.abilities.*;
import mage.abilities.effects.Effect;
import mage.cards.Card;
import mage.constants.*;
import mage.game.*;
import mage.game.mulligan.MulliganType;
import mage.game.permanent.Permanent;
import mage.game.turn.Phase;
import mage.player.ai.ComputerPlayer7;
import mage.players.Player;
import java.util.*;

/**
 * Regression check: Unnerving Grasp ("Return up to one target nonland permanent to its owner's hand. Manifest dread.")
 * on a Room. For a Room owned by the caster and one owned by the opponent, with one door unlocked and with both: the
 * Room can be targeted, goes to its owner's hand as one card, the caster manifests dread, and the owner can cast
 * either door again for that door's cost alone; the recast Room has only that door unlocked (a new object). Prints
 * PASS or FAIL and exits 1 on FAIL.
 */
public class RoomBounceCheck {
    static final List<String> failures = new ArrayList<>();
    static final String ROOM = "Bottomless Pool // Locker Room";

    static void expect(boolean ok, String what) {
        System.out.println((ok ? "  ok   " : "  FAIL ") + what);
        if (!ok) failures.add(what);
    }

    static long faceDown(Game game, Player p) {
        return game.getBattlefield().getAllActivePermanents(p.getId()).stream().filter(x -> x.isFaceDown(game)).count();
    }

    static void mainPhase(Game game, Player active) {
        game.getState().setActivePlayerId(active.getId());
        game.getState().setPriorityPlayerId(active.getId());
        Phase main = game.getState().getTurn().getPhase(TurnPhase.PRECOMBAT_MAIN);
        main.setStep(new mage.game.turn.PreCombatMainStep());
        game.getState().getTurn().setPhase(main);
        game.applyEffects();
    }

    static void scenario(Game game, Player caster, Player owner, boolean bothUnlocked) {
        String label = (owner == caster ? "own" : "opponent's") + " Room, " + (bothUnlocked ? "both doors" : "one door") + " unlocked";
        System.out.println(label);
        Card src = ManaCheck.make(game, "Murder", caster.getId());
        Ability sa = src.getSpellAbility();
        sa.setControllerId(caster.getId());
        Permanent room = ManaCheck.put(game, ROOM, owner.getId());
        room.unlockDoor(game, sa, true);
        if (bothUnlocked) room.unlockDoor(game, sa, false);
        game.applyEffects();
        for (int i = 0; i < 2; i++) {
            Card top = ManaCheck.make(game, "Bashful Beastie", caster.getId());
            caster.getLibrary().putOnTop(top, game);
            game.getState().setZone(top.getId(), Zone.LIBRARY);
        }
        mainPhase(game, caster);

        Card grasp = ManaCheck.make(game, "Unnerving Grasp", caster.getId());
        SpellAbility ga = grasp.getSpellAbility();
        ga.setControllerId(caster.getId());
        expect(ga.getTargets().get(0).canTarget(caster.getId(), room.getId(), ga, game), "the Room can be targeted");
        ga.getTargets().get(0).addTarget(room.getId(), ga, game, true);
        long downBefore = faceDown(game, caster);
        for (Effect effect : ga.getEffects()) effect.apply(game, ga);
        game.applyEffects();
        expect(game.getPermanent(room.getId()) == null, "the Room left the battlefield");
        Card inHand = owner.getHand().get(room.getId(), game);
        expect(inHand != null, "it is in its owner's hand as one card (" + (inHand == null ? "missing" : inHand.getName()) + ")");
        expect(owner == caster || !caster.getHand().contains(room.getId()), "not in the caster's hand");
        expect(faceDown(game, caster) == downBefore + 1, "the caster manifested dread (face-down " + downBefore + " -> " + faceDown(game, caster) + ")");
        if (inHand == null) return;

        // the owner casts it again: either door, for that door's cost
        for (int i = 0; i < 5; i++) ManaCheck.put(game, "Island", owner.getId());
        mainPhase(game, owner);
        List<String> offers = new ArrayList<>();
        ActivatedAbility left = null;
        for (ActivatedAbility ab : owner.getPlayable(game, true)) {
            Card source = game.getCard(ab.getSourceId());
            if (source == null || !inHand.getId().equals(source.getMainCard().getId())) continue;
            String name = game.getObject(ab.getSourceId()) == null ? "?" : game.getObject(ab.getSourceId()).getName();
            offers.add(name + " " + ab.getManaCostsToPay().getText());
            if ("Bottomless Pool".equals(name) && ab instanceof SpellAbility) left = ab;
        }
        System.out.println("  owner's options for it: " + offers);
        expect(offers.stream().anyMatch(o -> o.startsWith("Bottomless Pool {U}")), "Bottomless Pool castable for {U}");
        expect(offers.stream().anyMatch(o -> o.startsWith("Locker Room {4}{U}")), "Locker Room castable for {4}{U}");
        if (left == null) return;
        owner.cast((SpellAbility) left, game, true, null);
        mage.game.stack.StackObject spell = game.getStack().getFirst();
        System.out.println("  on the stack: " + (spell == null ? "nothing" : spell.getName() + " " + spell.getManaCost().getText()));
        if (spell == null) return;
        spell.resolve(game);
        game.getStack().remove(spell, game);
        game.applyEffects();
        Permanent back = game.getBattlefield().getAllActivePermanents(owner.getId()).stream()
                .filter(p -> ROOM.equals(p.getName()) || p.getName().contains("Bottomless Pool")).reduce((a, b) -> b).orElse(null);
        expect(back != null, "recast Room is on the battlefield");
        if (back != null) {
            expect(back.isLeftDoorUnlocked() && !back.isRightDoorUnlocked(), "only the cast door (Bottomless Pool) is unlocked: left "
                    + back.isLeftDoorUnlocked() + ", right " + back.isRightDoorUnlocked());
            game.getBattlefield().removePermanent(back.getId());
        }
        owner.getHand().clear();
        for (Permanent p : game.getBattlefield().getAllActivePermanents(owner.getId())) if ("Island".equals(p.getName())) game.getBattlefield().removePermanent(p.getId());
    }

    public static void main(String[] args) throws Exception {
        mage.cards.repository.RepositoryUtil.bootstrapLocalDb();
        mage.cards.repository.CardScanner.scan();
        Game game = new TwoPlayerDuel(MultiplayerAttackOption.LEFT, RangeOfInfluence.ONE, MulliganType.GAME_DEFAULT.getMulligan(0), 40, 20, 7);
        game.setGameOptions(new GameOptions());
        ComputerPlayer7 me = new ComputerPlayer7("ME", RangeOfInfluence.ONE, 2);
        ComputerPlayer7 opp = new ComputerPlayer7("OPP", RangeOfInfluence.ONE, 2);
        mage.game.match.Match match = new TwoPlayerMatch(new mage.game.match.MatchOptions("room bounce check", "Two Player Duel", false));
        for (Player p : new Player[]{me, opp}) {
            p.setTestMode(true);
            mage.cards.decks.Deck deck = new mage.cards.decks.Deck();
            game.addPlayer(p, deck);
            match.addPlayer(p, deck);
        }
        for (Player p : new Player[]{me, opp}) p.beginTurn(game);
        scenario(game, me, me, false);
        scenario(game, me, me, true);
        scenario(game, me, opp, false);
        scenario(game, me, opp, true);
        System.out.println(failures.isEmpty() ? "PASS" : "FAIL " + failures);
        System.exit(failures.isEmpty() ? 0 : 1);
    }
}
