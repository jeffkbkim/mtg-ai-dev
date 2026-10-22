import mage.abilities.*;
import mage.abilities.common.RoomUnlockAbility;
import mage.abilities.effects.common.continuous.GainAbilityTargetEffect;
import mage.abilities.keyword.FlyingAbility;
import mage.cards.Card;
import mage.constants.*;
import mage.game.*;
import mage.game.permanent.Permanent;
import mage.target.targetpointer.FixedTarget;
import java.util.*;

/**
 * Regression check for our patch to XMage 1.4.62 (BecomesFaceDownCreatureEffect.java here; README, Our patches to
 * XMage): a Room manifested face down must be a vanilla 2/2. Unpatched, it kept both doors' abilities, locked ones
 * included: a face-down Ticket Booth // Tunnel of Hate still had "Whenever you attack, target attacking creature gains
 * double strike" (it decided a combat in plan-pairs batch01 part11 game1). Also checks what the patch must not break:
 * an ability the face-down Room gains from another effect stays, and a face-up Room has only its unlocked doors'
 * abilities plus "unlock" for a locked door. Prints PASS or FAIL and exits 1 on FAIL.
 */
public class FaceDownRoomCheck {
    static boolean has(Permanent p, Game game, Class<?> kind) {
        for (Ability ab : p.getAbilities(game)) if (kind.isInstance(ab)) return true;
        return false;
    }

    public static void main(String[] a) throws Exception {
        mage.cards.repository.RepositoryUtil.bootstrapLocalDb();
        mage.cards.repository.CardScanner.scan();
        PySeat.Link link = ManaCheck.link();
        Game game = new TwoPlayerDuel(MultiplayerAttackOption.LEFT, RangeOfInfluence.ONE, mage.game.mulligan.MulliganType.GAME_DEFAULT.getMulligan(0), 40, 20, 7);
        PySeat py = new PySeat("PY", link);
        mage.player.ai.ComputerPlayer7 ai = new mage.player.ai.ComputerPlayer7("AI", RangeOfInfluence.ONE, 2);
        mage.game.match.Match match = new TwoPlayerMatch(new mage.game.match.MatchOptions("face-down room check", "Two Player Duel", false));
        for (mage.players.Player p : new mage.players.Player[]{py, ai}) { p.setTestMode(true); mage.cards.decks.Deck d = new mage.cards.decks.Deck(); game.addPlayer(p, d); match.addPlayer(p, d); }
        for (mage.players.Player p : new mage.players.Player[]{py, ai}) p.beginTurn(game);
        game.getState().setActivePlayerId(py.getId());
        Card src = ManaCheck.make(game, "Murder", py.getId());
        Ability sa = src.getSpellAbility(); sa.setControllerId(py.getId());

        // 1. manifested face down: no door abilities, through several rounds of continuous effects
        Card room = ManaCheck.make(game, "Ticket Booth // Tunnel of Hate", py.getId());
        py.getLibrary().putOnTop(room, game);
        Permanent down = mage.abilities.effects.keyword.ManifestEffect.doManifestCards(game, sa, py, new HashSet<>(Collections.singletonList(room))).get(0);
        for (int i = 0; i < 3; i++) game.applyEffects();
        List<String> left = new ArrayList<>();
        for (Ability ab : down.getAbilities(game)) left.add(ab.getClass().getSimpleName());
        boolean vanilla = down.isFaceDown(game) && down.getPower().getValue() == 2 && down.getToughness().getValue() == 2
                && !has(down, game, TriggeredAbility.class) && !has(down, game, SpellAbility.class) && !has(down, game, RoomUnlockAbility.class);
        System.out.println("face-down Room: " + down.getPower().getValue() + "/" + down.getToughness().getValue() + ", abilities " + left + (vanilla ? " (vanilla, ok)" : " (BUG: door abilities kept)"));

        // 2. an ability it gains from another effect stays
        GainAbilityTargetEffect gain = new GainAbilityTargetEffect(FlyingAbility.getInstance(), Duration.EndOfGame);
        gain.setTargetPointer(new FixedTarget(down, game));
        game.addEffect(gain, sa);
        game.applyEffects();
        boolean gained = has(down, game, FlyingAbility.class);
        System.out.println("gained flying kept: " + gained);

        // 3. face up: only unlocked doors' abilities, and unlock for the locked door
        Permanent up = ManaCheck.put(game, "Ticket Booth // Tunnel of Hate", py.getId());
        up.unlockDoor(game, sa, true);  // Ticket Booth unlocked, Tunnel of Hate locked
        game.applyEffects();
        boolean oneDoor = !has(up, game, mage.abilities.common.AttacksWithCreaturesTriggeredAbility.class) && has(up, game, RoomUnlockAbility.class);
        up.unlockDoor(game, sa, false);
        game.applyEffects();
        boolean bothDoors = has(up, game, mage.abilities.common.AttacksWithCreaturesTriggeredAbility.class) && !has(up, game, RoomUnlockAbility.class);
        System.out.println("face-up Room, one door unlocked: locked door's ability absent, unlock offered: " + oneDoor + "; both unlocked: " + bothDoors);

        boolean ok = vanilla && gained && oneDoor && bothDoors;
        System.out.println(ok ? "PASS" : "FAIL");
        System.exit(ok ? 0 : 1);
    }
}
