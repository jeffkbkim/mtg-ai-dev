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
import java.util.*;

/**
 * Cube mana (PySeat.costlyManaAsk). The automatic payer must never spend a mana source whose cost is more than {T}:
 * paying {1} from Black Lotus + Plains taps the Plains and keeps the Lotus; paying {2} from the same board fails
 * (the player activates the Lotus itself) and the Lotus stays; Lotus Petal + Forest paying {G} keeps the Petal.
 * Painful mana only when painless can't pay: Talisman of Progress + Island paying {1}{U} costs no life (Talisman's
 * {C}), paying {W}{U} costs 1 (its {W}). Without costlyManaAsk the old payer sacrificed the Lotus for {2}, which is
 * what this guards against. Also: manaCostClass of Black Lotus, Mana Confluence, Talisman, Forest, and the
 * observation's mana pool ("my_pool") after three black mana are added. At priority in our main phase the Lotus is
 * offered as a move (the Plains' mana is not); activating it asks the colour and floats {B}{B}{B}, and {1}{B} is then
 * paid from the pool, leaving {B} and the Plains untapped. No waste: {1} from Sol Ring + Plains taps the Plains,
 * {2} taps the Sol Ring. Coloured symbols before generic: {4}{R} from Talisman of Indulgence, Mox Sapphire, Mox Pearl,
 * Ancient Tomb, Island and Mightstone (its mana can't pay a nonartifact spell) is paid, with the Talisman's {R}.
 * Delve is the player's: Murderous Cut with five Swamps and six cards in the graveyard, the player exiling four, taps
 * one Swamp. Generic from noncreatures weighed together: {1} from Mountain, Mox Sapphire and Sol Ring with Pyrokinesis
 * in hand taps the Mox. Sol Ring (two mana at once) is offered at priority too.
 * Prints PASS or FAIL and exits 1 on FAIL.
 */
public class CostlyManaCheck {
    static Card make(Game game, String name, UUID owner) {
        Card c = CardRepository.instance.findCards(name).get(0).createCard();
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

    static Game game;
    static PySeat py;
    static String[] handCards = {};  // put in the seat's hand by trial (the payer plans for them)
    static int lifeBefore;

    static int lifeLost() {
        return lifeBefore - py.getLife();
    }

    /** Pays cost on a fresh board; returns whether it was paid. */
    static boolean trial(boolean costly, String cost, String... cards) throws Exception {
        game = new TwoPlayerDuel(MultiplayerAttackOption.LEFT, RangeOfInfluence.ONE, MulliganType.GAME_DEFAULT.getMulligan(0), 40, 20, 7);
        py = new PySeat("PY", ManaCheck.link());
        py.payerV2 = true;
        py.costlyManaAsk = costly;
        ComputerPlayer7 ai = new ComputerPlayer7("AI", RangeOfInfluence.ONE, 2);
        mage.game.match.Match match = new TwoPlayerMatch(new mage.game.match.MatchOptions("costly mana check", "Two Player Duel", false));
        for (mage.players.Player p : new mage.players.Player[]{py, ai}) {
            p.setTestMode(true);
            mage.cards.decks.Deck deck = new mage.cards.decks.Deck();
            game.addPlayer(p, deck);
            match.addPlayer(p, deck);
        }
        for (String n : cards) put(game, n, py.getId());
        for (String n : handCards) {
            Card c = make(game, n, py.getId());
            py.getHand().add(c);
            game.getState().setZone(c.getId(), Zone.HAND);
        }
        for (mage.players.Player p : new mage.players.Player[]{py, ai}) p.beginTurn(game);
        game.getState().setActivePlayerId(py.getId());
        game.applyEffects();
        Card spell = make(game, "Lightning Bolt", py.getId());  // any spell of ours to pay for
        mage.abilities.Ability sa = spell.getSpellAbility();
        sa.setControllerId(py.getId());
        lifeBefore = py.getLife();
        return new ManaCostsImpl<ManaCost>(cost).pay(sa, game, sa, py.getId(), false, null);
    }

    static boolean onBattlefield(String name) {
        return game.getBattlefield().getAllActivePermanents(py.getId()).stream().anyMatch(p -> p.getName().equals(name));
    }

    static boolean tapped(String name) {
        return game.getBattlefield().getAllActivePermanents(py.getId()).stream().anyMatch(p -> p.getName().equals(name) && p.isTapped());
    }

    static int costClass(String name) {
        int k = -1;
        for (mage.abilities.Ability a : make(game, name, py.getId()).getAbilities())
            if (a instanceof mage.abilities.mana.ActivatedManaAbilityImpl) k = Math.max(k, PySeat.manaCostClass((mage.abilities.mana.ActivatedManaAbilityImpl) a));
        return k;
    }

    /** Precombat main with Black Lotus and a Plains: priority must offer the Lotus; Python activates it and picks
     *  Black. Returns "" when the pool then holds {B}{B}{B}, the Lotus is gone and the colour was asked. */
    static String activateLotus() throws Exception {
        java.io.PipedInputStream seatIn = new java.io.PipedInputStream(), fromSeat = new java.io.PipedInputStream();
        java.io.PrintWriter toSeat = new java.io.PrintWriter(new java.io.PipedOutputStream(seatIn), true);
        PySeat.Link link = new PySeat.Link(seatIn, new java.io.PipedOutputStream(fromSeat));
        List<String> seen = Collections.synchronizedList(new ArrayList<>());
        Thread python = new Thread(() -> {
            try (java.io.BufferedReader r = new java.io.BufferedReader(new java.io.InputStreamReader(fromSeat))) {
                for (String line; (line = r.readLine()) != null; ) {
                    com.google.gson.JsonObject m = com.google.gson.JsonParser.parseString(line).getAsJsonObject();
                    com.google.gson.JsonArray opts = m.getAsJsonArray("options");
                    int pick = 0;
                    for (int i = 0; i < opts.size(); i++) {
                        String l = opts.get(i).getAsJsonObject().get("label").getAsString();
                        seen.add(m.get("kind").getAsString() + ": " + l);
                        if (l.contains("Black Lotus") || l.equals("Black")) pick = i;
                    }
                    toSeat.println("{\"choice\":" + pick + "}");
                }
            } catch (java.io.IOException ignored) { }
        });
        python.setDaemon(true);
        python.start();
        game = new TwoPlayerDuel(MultiplayerAttackOption.LEFT, RangeOfInfluence.ONE, MulliganType.GAME_DEFAULT.getMulligan(0), 40, 20, 7);
        game.setGameOptions(new GameOptions());
        py = new PySeat("PY", link);
        py.payerV2 = py.costlyManaAsk = true;
        ComputerPlayer7 ai = new ComputerPlayer7("AI", RangeOfInfluence.ONE, 2);
        mage.game.match.Match match = new TwoPlayerMatch(new mage.game.match.MatchOptions("costly mana check", "Two Player Duel", false));
        for (mage.players.Player p : new mage.players.Player[]{py, ai}) {
            p.setTestMode(true);
            mage.cards.decks.Deck deck = new mage.cards.decks.Deck();
            game.addPlayer(p, deck);
            match.addPlayer(p, deck);
        }
        put(game, "Black Lotus", py.getId());
        put(game, "Plains", py.getId());
        put(game, "Sol Ring", py.getId());
        for (mage.players.Player p : new mage.players.Player[]{py, ai}) p.beginTurn(game);
        game.getState().setActivePlayerId(py.getId());
        mage.game.turn.Phase main = game.getState().getTurn().getPhase(TurnPhase.PRECOMBAT_MAIN);
        main.setStep(new mage.game.turn.PreCombatMainStep());
        game.getState().getTurn().setPhase(main);
        game.applyEffects();
        py.priority(game);
        Thread.sleep(300);
        String pool = Observer.poolText(py.getManaPool());
        boolean asked = seen.stream().anyMatch(l -> l.startsWith("CHOICE") && l.endsWith("Black"));
        boolean offeredPlains = seen.stream().anyMatch(l -> l.startsWith("PRIORITY") && l.contains("Plains") && !l.contains("Play"));
        boolean offeredRing = seen.stream().anyMatch(l -> l.startsWith("PRIORITY") && l.contains("Sol Ring"));  // makes two at once
        // a spell is then paid from the pool first: {1}{B} leaves {B} floating and the Plains untapped
        Card spell = make(game, "Lightning Bolt", py.getId());
        mage.abilities.Ability sa = spell.getSpellAbility();
        sa.setControllerId(py.getId());
        boolean paid = new ManaCostsImpl<ManaCost>("{1}{B}").pay(sa, game, sa, py.getId(), false, null);
        String after = Observer.poolText(py.getManaPool());
        if (pool.equals("{B}{B}{B}") && !onBattlefield("Black Lotus") && asked && !offeredPlains && offeredRing && paid && after.equals("{B}") && !tapped("Plains")) return "";
        return "Lotus at priority: pool '" + pool + "', Lotus " + (onBattlefield("Black Lotus") ? "still there" : "gone")
                + ", colour asked " + asked + ", Plains mana offered " + offeredPlains + ", Sol Ring offered " + offeredRing + ", {1}{B} paid " + paid + " leaving '" + after
                + "', Plains tapped " + tapped("Plains") + "; seen " + seen;
    }

    /** Murderous Cut ({4}{B}, delve) with five Swamps and six cards in the graveyard; Python exiles cards whenever the
     *  prompt is about delve. Returns "" when it is paid with four cards exiled and one Swamp tapped. */
    static String delve() throws Exception {
        java.io.PipedInputStream seatIn = new java.io.PipedInputStream(), fromSeat = new java.io.PipedInputStream();
        java.io.PrintWriter toSeat = new java.io.PrintWriter(new java.io.PipedOutputStream(seatIn), true);
        PySeat.Link link = new PySeat.Link(seatIn, new java.io.PipedOutputStream(fromSeat));
        List<String> prompts = Collections.synchronizedList(new ArrayList<>());
        Thread python = new Thread(() -> {
            try (java.io.BufferedReader r = new java.io.BufferedReader(new java.io.InputStreamReader(fromSeat))) {
                for (String line; (line = r.readLine()) != null; ) {
                    com.google.gson.JsonObject m = com.google.gson.JsonParser.parseString(line).getAsJsonObject();
                    String prompt = m.get("prompt").getAsString();
                    prompts.add(m.get("kind").getAsString() + ": " + prompt);
                    com.google.gson.JsonArray opts = m.getAsJsonArray("options");
                    int pick = 0;
                    if (prompt.contains("Delve"))
                        for (int i = 0; i < opts.size(); i++)
                            if (!opts.get(i).getAsJsonObject().get("label").getAsString().equals("DONE")) { pick = i; break; }
                    toSeat.println("{\"choice\":" + pick + "}");
                }
            } catch (java.io.IOException ignored) { }
        });
        python.setDaemon(true);
        python.start();
        game = new TwoPlayerDuel(MultiplayerAttackOption.LEFT, RangeOfInfluence.ONE, MulliganType.GAME_DEFAULT.getMulligan(0), 40, 20, 7);
        game.setGameOptions(new GameOptions());
        py = new PySeat("PY", link);
        py.payerV2 = py.costlyManaAsk = true;
        ComputerPlayer7 ai = new ComputerPlayer7("AI", RangeOfInfluence.ONE, 2);
        mage.game.match.Match match = new TwoPlayerMatch(new mage.game.match.MatchOptions("costly mana check", "Two Player Duel", false));
        for (mage.players.Player p : new mage.players.Player[]{py, ai}) {
            p.setTestMode(true);
            mage.cards.decks.Deck deck = new mage.cards.decks.Deck();
            game.addPlayer(p, deck);
            match.addPlayer(p, deck);
        }
        for (int k = 0; k < 5; k++) put(game, "Swamp", py.getId());
        for (String n : new String[]{"Lightning Bolt", "Counterspell", "Dark Ritual", "Brainstorm", "Ponder", "Duress"}) {
            Card c = make(game, n, py.getId());
            py.getGraveyard().add(c);
            game.getState().setZone(c.getId(), Zone.GRAVEYARD);
        }
        for (mage.players.Player p : new mage.players.Player[]{py, ai}) p.beginTurn(game);
        game.getState().setActivePlayerId(py.getId());
        mage.game.turn.Phase main = game.getState().getTurn().getPhase(TurnPhase.PRECOMBAT_MAIN);
        main.setStep(new mage.game.turn.PreCombatMainStep());
        game.getState().getTurn().setPhase(main);
        game.applyEffects();
        Card cut = make(game, "Murderous Cut", py.getId());
        mage.abilities.SpellAbility sa = cut.getSpellAbility();
        sa.setControllerId(py.getId());
        game.getStack().push(game, new mage.game.stack.Spell(cut, sa, py.getId(), Zone.HAND, game));  // paid while on the stack
        game.getState().setZone(cut.getId(), Zone.STACK);
        boolean paid;
        try {
            paid = new ManaCostsImpl<ManaCost>("{4}{B}").pay(sa, game, sa, py.getId(), false, null);
        } catch (RuntimeException e) {
            return "delve: " + e + "; asked " + prompts;
        }
        long swampsTapped = game.getBattlefield().getAllActivePermanents(py.getId()).stream().filter(Permanent::isTapped).count();
        int left = py.getGraveyard().size();
        if (paid && swampsTapped == 1 && left == 2 && prompts.stream().anyMatch(l -> l.contains("Delve"))) return "";
        return "delve: Murderous Cut paid " + paid + ", Swamps tapped " + swampsTapped + ", graveyard left " + left + "; asked " + prompts;
    }

    public static void main(String[] args) throws Exception {
        RepositoryUtil.bootstrapLocalDb();
        CardScanner.scan();
        List<String> fails = new ArrayList<>();
        int trials = 5;
        for (int t = 0; t < trials; t++) {
            if (!trial(true, "{1}", "Black Lotus", "Plains") || !tapped("Plains") || !onBattlefield("Black Lotus"))
                fails.add("{1} from Lotus + Plains: Plains not tapped or Lotus spent");
            trial(true, "{2}", "Black Lotus", "Plains");
            if (!onBattlefield("Black Lotus")) fails.add("{2} from Lotus + Plains: the payer sacrificed the Lotus");
            if (!trial(true, "{G}", "Lotus Petal", "Forest") || !onBattlefield("Lotus Petal"))
                fails.add("{G} from Petal + Forest: unpaid or Petal spent");
            if (!trial(true, "{1}{U}", "Talisman of Progress", "Island") || lifeLost() != 0)
                fails.add("{1}{U} from Talisman + Island: unpaid or life lost (" + lifeLost() + ")");
            if (!trial(true, "{W}{U}", "Talisman of Progress", "Island") || lifeLost() != 1)
                fails.add("{W}{U} from Talisman + Island: unpaid or wrong life lost (" + lifeLost() + ")");
        }
        // the player activates the Lotus itself: offered at priority (PySeat.playerManaAbility), its colour asked
        String lotusRun = activateLotus();
        if (!lotusRun.isEmpty()) fails.add(lotusRun);
        for (int t = 0; t < trials; t++)  // no waste: {1} from Sol Ring + Plains taps the Plains, {2} taps the Sol Ring
            if (!trial(true, "{1}", "Sol Ring", "Plains") || !tapped("Plains") || tapped("Sol Ring")
                    || !trial(true, "{2}", "Sol Ring", "Plains") || !tapped("Sol Ring") || tapped("Plains"))
                fails.add("Sol Ring + Plains: {1} should tap the Plains, {2} the Sol Ring");
        String delveRun = delve();  // cube pilot: delve was never used
        if (!delveRun.isEmpty()) fails.add(delveRun);
        handCards = new String[]{"Pyrokinesis"};
        for (int t = 0; t < trials; t++)  // cube pilot: Chromatic Star's {1} took a Mountain while Moxen were untapped
            if (!trial(true, "{1}", "Mountain", "Mox Sapphire", "Sol Ring") || tapped("Mountain") || tapped("Sol Ring"))
                fails.add("{1} from Mountain, Mox Sapphire, Sol Ring with Pyrokinesis in hand: should tap the Mox");
        handCards = new String[]{};
        for (int t = 0; t < trials; t++)  // cube pilot: Talisman's painless {C} paid generic and its {R} was then missing
            if (!trial(true, "{4}{R}", "Talisman of Indulgence", "Mox Sapphire", "Mox Pearl", "Ancient Tomb", "Island", "The Mightstone and Weakstone"))
                fails.add("{4}{R} (Pyrokinesis) from Talisman, two Moxen, Ancient Tomb, Island, Mightstone: unpaid");
        trial(false, "{2}", "Black Lotus", "Plains");
        boolean oldSpends = !onBattlefield("Black Lotus");  // the fault this check is for, seen without the flag
        int lotus = costClass("Black Lotus"), confluence = costClass("Mana Confluence"), talisman = costClass("Talisman of Progress"), forest = costClass("Forest");
        if (lotus != 2 || confluence != 1 || talisman != 1 || forest != 0)
            fails.add("manaCostClass Lotus " + lotus + " Confluence " + confluence + " Talisman " + talisman + " Forest " + forest + " (want 2 1 1 0)");
        trial(true, "{0}", "Plains");
        mage.abilities.Ability src = make(game, "Lightning Bolt", py.getId()).getSpellAbility();
        src.setControllerId(py.getId());
        py.getManaPool().addMana(mage.Mana.BlackMana(3), game, src);
        String pool = Observer.build(game, py.getId(), Collections.emptyList()).entries.get(0).toString();
        if (!pool.contains("\"my_pool\":\"{B}{B}{B}\"")) fails.add("observation pool: " + pool);
        System.out.println("COSTLY_MANA old payer spent the Lotus for {2}: " + oldSpends + "; failures " + fails.size() + "/" + (8 * trials + 4));
        fails.stream().distinct().forEach(f -> System.out.println("  " + f));
        System.out.println(fails.isEmpty() ? "PASS" : "FAIL");
        System.exit(fails.isEmpty() ? 0 : 1);
    }
}
