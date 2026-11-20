import com.google.gson.*;
import mage.cards.Card;
import mage.cards.repository.*;
import mage.constants.*;
import mage.game.*;
import mage.game.mulligan.MulliganType;
import mage.game.stack.Spell;
import mage.player.ai.ComputerPlayer7;
import java.io.*;
import java.util.*;

/**
 * PySeat.askAmounts: amounts are the player's, not XMage's AI (cube02/03 reviews, ~40 bug flags). Fire Covenant with
 * Badlands, Badlands, Mountain and two opposing Grizzly Bears: the player is asked X (the life to pay) and picks
 * "X = 4", then divides the damage: a TARGET (the first bear), an AMOUNT ("2 to ..."), and the second bear gets the
 * other 2 without a question. The spell is on the stack with 2 damage on each bear and 4 life paid. getAmount (0 to 5)
 * asks an AMOUNT and returns the pick (3); Manamorphose-style mana (two mana among five colours) asks one AMOUNT per
 * colour until the two are placed. Without askAmounts none of these is asked (the old fallback).
 * Prints PASS or FAIL and exits 1 on FAIL.
 */
public class AmountCheck {
    static final List<String> asked = Collections.synchronizedList(new ArrayList<>());

    static Card make(Game game, String name, UUID owner) {
        Card c = CardRepository.instance.findCards(name).get(0).createCard();
        game.loadCards(new HashSet<>(Collections.singletonList(c)), owner);
        return c;
    }

    static mage.game.permanent.Permanent put(Game game, String name, UUID owner) {
        Card c = make(game, name, owner);
        mage.game.permanent.PermanentCard perm = new mage.game.permanent.PermanentCard(c, owner, game);
        game.addPermanent(perm, 0);
        game.getState().setZone(c.getId(), Zone.BATTLEFIELD);
        perm.removeSummoningSickness();
        return perm;
    }

    static PySeat.Link link(String... wanted) throws IOException {
        PipedInputStream seatIn = new PipedInputStream(), fromSeat = new PipedInputStream();
        PrintWriter toSeat = new PrintWriter(new PipedOutputStream(seatIn), true);
        PySeat.Link link = new PySeat.Link(seatIn, new PipedOutputStream(fromSeat));
        Thread python = new Thread(() -> {
            try (BufferedReader r = new BufferedReader(new InputStreamReader(fromSeat))) {
                for (String line; (line = r.readLine()) != null; ) {
                    JsonObject m = JsonParser.parseString(line).getAsJsonObject();
                    JsonArray opts = m.getAsJsonArray("options");
                    asked.add(m.get("kind").getAsString() + ": " + m.get("prompt").getAsString() + " " + opts.size() + " options");
                    int pick = 0;
                    outer:
                    for (String w : wanted)
                        for (int i = 0; i < opts.size(); i++)
                            if (opts.get(i).getAsJsonObject().get("label").getAsString().matches(w)) { pick = i; break outer; }
                    toSeat.println("{\"choice\":" + pick + "}");
                }
            } catch (IOException ignored) { }
        });
        python.setDaemon(true);
        python.start();
        return link;
    }

    static Game game;
    static PySeat py;
    static ComputerPlayer7 ai;

    static void setUp(boolean askAmounts, String... wanted) throws Exception {
        game = new TwoPlayerDuel(MultiplayerAttackOption.LEFT, RangeOfInfluence.ONE, MulliganType.GAME_DEFAULT.getMulligan(0), 40, 20, 7);
        game.setGameOptions(new GameOptions());
        py = new PySeat("PY", link(wanted));
        py.payerV2 = py.askX = py.costlyManaAsk = true;
        py.askAmounts = askAmounts;
        ai = new ComputerPlayer7("AI", RangeOfInfluence.ONE, 2);
        mage.game.match.Match match = new TwoPlayerMatch(new mage.game.match.MatchOptions("amount check", "Two Player Duel", false));
        for (mage.players.Player p : new mage.players.Player[]{py, ai}) {
            p.setTestMode(true);
            mage.cards.decks.Deck deck = new mage.cards.decks.Deck();
            game.addPlayer(p, deck);
            match.addPlayer(p, deck);
        }
    }

    static void ourMain() {
        for (mage.players.Player p : new mage.players.Player[]{py, ai}) {
            p.beginTurn(game);
            p.setLife(20, game, (mage.abilities.Ability) null);  // an unstarted game has 0 life, so no life could be paid
        }
        game.getState().setActivePlayerId(py.getId());
        mage.game.turn.Phase main = game.getState().getTurn().getPhase(TurnPhase.PRECOMBAT_MAIN);
        main.setStep(new mage.game.turn.PreCombatMainStep());
        game.getState().getTurn().setPhase(main);
        game.applyEffects();
    }

    /** Fire Covenant cast at priority; returns what is wrong, or "". */
    static String fireCovenant(boolean askAmounts) throws Exception {
        asked.clear();
        setUp(askAmounts, ".*Cast Fire Covenant.*", "X = 4", "2 to .*");
        for (String n : new String[]{"Badlands", "Badlands", "Mountain"}) put(game, n, py.getId());
        mage.game.permanent.Permanent b1 = put(game, "Grizzly Bears", ai.getId()), b2 = put(game, "Grizzly Bears", ai.getId());
        Card fc = make(game, "Fire Covenant", py.getId());
        py.getHand().add(fc);
        game.getState().setZone(fc.getId(), Zone.HAND);
        ourMain();
        String refused = "";
        try {
            py.priority(game);
        } catch (NullPointerException e) {
            refused = " (cast refused: " + e.getStackTrace()[0] + ")";
        }
        Thread.sleep(300);
        Spell spell = game.getStack().getSpell(fc.getId());
        String kinds = String.join(" | ", asked);
        if (!askAmounts) return kinds.contains("AMOUNT") || kinds.contains("X: choose X") ? "without askAmounts an amount was asked: " + kinds : "";
        if (spell == null) return "Fire Covenant not on the stack" + refused + "; asked " + kinds;
        mage.target.Target t = spell.getSpellAbility().getTargets().get(0);
        int d1 = t.getTargetAmount(b1.getId()), d2 = t.getTargetAmount(b2.getId());
        int life = 20 - py.getLife();
        boolean askedX = kinds.contains("X: choose X"), askedTarget = kinds.contains("TARGET:"), askedAmount = kinds.contains("AMOUNT:");
        if (d1 + d2 != 4 || d1 != 2 || life != 4 || !askedX || !askedTarget || !askedAmount)
            return "Fire Covenant: damage " + d1 + "+" + d2 + " (want 2+2), life paid " + life + " (want 4), asked " + kinds;
        return "";
    }

    public static void main(String[] args) throws Exception {
        RepositoryUtil.bootstrapLocalDb();
        CardScanner.scan();
        List<String> fails = new ArrayList<>();
        String f = fireCovenant(true);
        if (!f.isEmpty()) fails.add(f);
        f = fireCovenant(false);
        if (!f.isEmpty()) fails.add(f);

        // getAmount (Galvanic Discharge's energy)
        asked.clear();
        setUp(true, "3");
        ourMain();
        mage.abilities.Ability src = make(game, "Galvanic Discharge", py.getId()).getSpellAbility();
        src.setControllerId(py.getId());
        int got = py.getAmount(0, 5, "Pay any amount of {E}", src, game);
        if (got != 3 || asked.stream().noneMatch(a -> a.startsWith("AMOUNT:") && a.endsWith(" 6 options")))
            fails.add("getAmount 0..5: got " + got + " (want 3), asked " + asked);

        // multi-amount mana (Manamorphose: two mana in any combination of colours)
        asked.clear();
        setUp(true, "1 .*");
        ourMain();
        List<mage.util.MultiAmountMessage> msgs = new ArrayList<>();
        for (String c : new String[]{"White", "Blue", "Black", "Red", "Green"}) msgs.add(new mage.util.MultiAmountMessage(c + " mana", 0, 2));
        List<Integer> split = py.getMultiAmountWithIndividualConstraints(Outcome.PutManaInPool, msgs, 2, 2, MultiAmountType.MANA, game);
        int sum = split.stream().mapToInt(Integer::intValue).sum();
        if (sum != 2 || !split.equals(Arrays.asList(1, 1, 0, 0, 0)) || asked.stream().filter(a -> a.startsWith("AMOUNT:")).count() != 2)
            fails.add("mana split: " + split + " (want [1, 1, 0, 0, 0] from two AMOUNT questions), asked " + asked);

        System.out.println("AMOUNT failures " + fails.size() + "/4");
        fails.forEach(x -> System.out.println("  " + x));
        System.out.println(fails.isEmpty() ? "PASS" : "FAIL");
        System.exit(fails.isEmpty() ? 0 : 1);
    }
}
