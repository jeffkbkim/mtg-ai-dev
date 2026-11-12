import mage.cards.Card;
import mage.cards.repository.*;
import mage.constants.*;
import mage.game.*;
import mage.game.mulligan.MulliganType;
import mage.player.ai.ComputerPlayer7;
import java.util.*;

/**
 * Hidden-information checks from the cube02 batch, where the leak check stopped 12 of the first 52 games:
 * - Chrome Mox's imprint (TargetCard in Zone.HAND) listed the opponent's hand too: only my own hand may be offered.
 * - Phyrexian Revoker's card-name choice listed every card name XMage knows (the library's among them): it offers this
 *   format's names (the cube list), and the leak check does not count those labels.
 * - False alarms: "keywords":["Flash"] named the card Flash in a library, and "Phlage, Titan of Fire's Fury" in my hand
 *   named Fury. Real mentions must still count: a library card's own name as a value, and "Fury" on its own.
 * Prints PASS or FAIL and exits 1 on FAIL.
 */
public class CubeLeakCheck {
    static Game game;
    static PySeat py;
    static ComputerPlayer7 ai;
    static final List<String> seen = Collections.synchronizedList(new ArrayList<>());

    static Card make(String name, UUID owner) {
        Card c = CardRepository.instance.findCards(name).get(0).createCard();
        game.loadCards(new HashSet<>(Collections.singletonList(c)), owner);
        return c;
    }

    static Card toZone(String name, UUID owner, Zone zone) {
        Card c = make(name, owner);
        mage.players.Player p = game.getPlayer(owner);
        if (zone == Zone.HAND) p.getHand().add(c);
        else if (zone == Zone.LIBRARY) p.getLibrary().putOnTop(c, game);
        game.getState().setZone(c.getId(), zone);
        return c;
    }

    static void setUp() throws Exception {
        java.io.PipedInputStream seatIn = new java.io.PipedInputStream(), fromSeat = new java.io.PipedInputStream();
        java.io.PrintWriter toSeat = new java.io.PrintWriter(new java.io.PipedOutputStream(seatIn), true);
        PySeat.Link link = new PySeat.Link(seatIn, new java.io.PipedOutputStream(fromSeat));
        Thread python = new Thread(() -> {
            try (java.io.BufferedReader r = new java.io.BufferedReader(new java.io.InputStreamReader(fromSeat))) {
                for (String line; (line = r.readLine()) != null; ) {
                    com.google.gson.JsonObject m = com.google.gson.JsonParser.parseString(line).getAsJsonObject();
                    com.google.gson.JsonArray opts = m.getAsJsonArray("options");
                    seen.add(m.get("kind").getAsString() + " options " + opts.size() + " leaks " + m.get("leaks"));
                    for (int i = 0; i < opts.size(); i++) seen.add("  " + opts.get(i).getAsJsonObject().get("label").getAsString());
                    int pick = 0;
                    for (int i = 0; i < opts.size(); i++) if (!opts.get(i).getAsJsonObject().get("label").getAsString().equals("DONE")) { pick = i; break; }
                    toSeat.println("{\"choice\":" + pick + "}");
                }
            } catch (java.io.IOException ignored) { }
        });
        python.setDaemon(true);
        python.start();
        game = new TwoPlayerDuel(MultiplayerAttackOption.LEFT, RangeOfInfluence.ONE, MulliganType.GAME_DEFAULT.getMulligan(0), 40, 20, 7);
        game.setGameOptions(new GameOptions());
        py = new PySeat("PY", link);
        ai = new ComputerPlayer7("AI", RangeOfInfluence.ONE, 2);
        mage.game.match.Match match = new TwoPlayerMatch(new mage.game.match.MatchOptions("cube leak check", "Two Player Duel", false));
        for (mage.players.Player p : new mage.players.Player[]{py, ai}) {
            p.setTestMode(true);
            mage.cards.decks.Deck deck = new mage.cards.decks.Deck();
            game.addPlayer(p, deck);
            match.addPlayer(p, deck);
        }
        for (String n : new String[]{"Swords to Plowshares", "Treasure Cruise", "Phlage, Titan of Fire's Fury", "Black Lotus"}) toZone(n, py.getId(), Zone.HAND);
        for (String n : new String[]{"Fire Covenant", "Grist, the Hunger Tide"}) toZone(n, ai.getId(), Zone.HAND);
        for (String n : new String[]{"Flash", "Fury"}) toZone(n, py.getId(), Zone.LIBRARY);
        for (mage.players.Player p : new mage.players.Player[]{py, ai}) p.beginTurn(game);
        game.getState().setActivePlayerId(py.getId());
        mage.game.turn.Phase main = game.getState().getTurn().getPhase(TurnPhase.PRECOMBAT_MAIN);
        main.setStep(new mage.game.turn.PreCombatMainStep());
        game.getState().getTurn().setPhase(main);
        game.applyEffects();
    }

    public static void main(String[] args) throws Exception {
        RepositoryUtil.bootstrapLocalDb();
        CardScanner.scan();
        List<String> fails = new ArrayList<>();
        setUp();
        Observer.Obs obs = Observer.build(game, py.getId(), null);

        // false alarms gone, real mentions still caught
        List<String> kw = Observer.scanText("{\"keywords\":[\"Flash\",\"Haste\"]}", game, obs);
        if (!kw.isEmpty()) fails.add("keyword Flash flagged: " + kw);
        List<String> phlage = Observer.scanText(obs.json.toString(), game, obs);
        if (!phlage.isEmpty()) fails.add("observation with Phlage in hand flagged: " + phlage);
        if (Observer.scanText("{\"name\":\"Flash\"}", game, obs).isEmpty()) fails.add("Flash as a name not flagged");
        if (Observer.scanText("{\"label\":\"| Fury | Cast Fury\"}", game, obs).isEmpty()) fails.add("Fury on its own not flagged");

        // Chrome Mox: TargetCard(Zone.HAND) offers only my own hand
        mage.filter.FilterCard filter = new mage.filter.FilterCard("nonartifact, nonland card from your hand");
        filter.add(mage.filter.predicate.Predicates.not(CardType.ARTIFACT.getPredicate()));
        filter.add(mage.filter.predicate.Predicates.not(CardType.LAND.getPredicate()));
        mage.abilities.Ability src = make("Chrome Mox", py.getId()).getSpellAbility();
        src.setControllerId(py.getId());
        seen.clear();
        py.choose(Outcome.Benefit, new mage.target.TargetCard(Zone.HAND, filter).withNotTarget(true), src, game);
        Thread.sleep(200);
        String imprint = String.join("\n", seen);
        if (imprint.contains("Fire Covenant") || imprint.contains("Grist") || !imprint.contains("Swords to Plowshares") || !imprint.contains("leaks []"))
            fails.add("Chrome Mox imprint options:\n" + imprint);

        // Phyrexian Revoker: a card-name choice offers the cube's names, with no leak flagged
        mage.choices.Choice names = new mage.choices.ChoiceImpl(true);
        names.setMessage("Choose a card name");
        names.setChoices(new HashSet<>(CardRepository.instance.getNames()));
        seen.clear();
        py.choose(Outcome.Detriment, names, game);
        Thread.sleep(200);
        String head = seen.isEmpty() ? "nothing asked" : seen.get(0);
        long offered = seen.stream().filter(l -> l.startsWith("  ")).count();
        boolean cubeOnly = seen.stream().filter(l -> l.startsWith("  ")).allMatch(l -> CubeList.NAMES.contains(l.substring(2)));
        if (!head.contains("leaks []") || offered < 400 || offered > 600 || !cubeOnly || !names.isChosen())
            fails.add("card-name choice: " + head + ", " + offered + " offered, all cube names " + cubeOnly + ", chosen " + names.isChosen());

        System.out.println("CUBE_LEAK failures " + fails.size() + "/7");
        fails.forEach(f -> System.out.println("  " + f));
        System.out.println(fails.isEmpty() ? "PASS" : "FAIL");
        System.exit(fails.isEmpty() ? 0 : 1);
    }
}
