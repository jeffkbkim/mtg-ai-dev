import com.google.gson.*;
import mage.abilities.Ability;
import mage.cards.Card;
import mage.cards.repository.*;
import mage.constants.*;
import mage.game.*;
import mage.game.mulligan.MulliganType;
import mage.game.permanent.PermanentCard;
import mage.player.ai.ComputerPlayer7;
import java.io.*;
import java.util.*;

/**
 * Regression check for the opponent-hand leak found by the coverage soak: when the opponent's ability makes our
 * seat pay a cost (Osseous Sticktwister: "each opponent may sacrifice a nonland permanent or discard a card"),
 * the cards offered must come from our hand, and the discarded card must leave our hand.
 * Runs the real card effect on a hand-built board, with Python's side answered in-process.
 * Prints PASS or FAIL lines and exits 1 on any FAIL.
 */
public class SeatChoiceCheck {
    static Card make(Game game, String name, UUID owner) {
        Card c = CardRepository.instance.findCards(new CardCriteria().setCodes("DSK").name(name)).get(0).createCard();
        game.loadCards(new HashSet<>(Collections.singletonList(c)), owner);
        return c;
    }

    public static void main(String[] args) throws Exception {
        RepositoryUtil.bootstrapLocalDb();
        CardScanner.scan();
        PipedInputStream seatIn = new PipedInputStream(), fromSeat = new PipedInputStream();
        PrintWriter toSeat = new PrintWriter(new PipedOutputStream(seatIn), true);
        PySeat.Link link = new PySeat.Link(seatIn, new PipedOutputStream(fromSeat));
        List<JsonObject> asked = Collections.synchronizedList(new ArrayList<>());
        Thread python = new Thread(() -> {  // stands in for Python: say yes, choose "discard", take the first card
            try (BufferedReader r = new BufferedReader(new InputStreamReader(fromSeat))) {
                for (String line; (line = r.readLine()) != null; ) {
                    JsonObject m = JsonParser.parseString(line).getAsJsonObject();
                    asked.add(m);
                    JsonArray opts = m.getAsJsonArray("options");
                    int pick = 0;
                    for (int i = 0; i < opts.size(); i++) {
                        String label = opts.get(i).getAsJsonObject().get("label").getAsString();
                        if (label.startsWith("YES") || label.toLowerCase().contains("discard")) { pick = i; break; }
                    }
                    toSeat.println("{\"choice\":" + pick + "}");
                }
            } catch (IOException ignored) { }
        });
        python.setDaemon(true);
        python.start();

        Game game = new TwoPlayerDuel(MultiplayerAttackOption.LEFT, RangeOfInfluence.ONE, MulliganType.GAME_DEFAULT.getMulligan(0), 40, 20, 7);
        PySeat py = new PySeat("PY", link);
        ComputerPlayer7 ai = new ComputerPlayer7("AI", RangeOfInfluence.ONE, 2);
        mage.game.match.Match match = new mage.game.TwoPlayerMatch(new mage.game.match.MatchOptions("seat check", "Two Player Duel", false));
        for (mage.players.Player p : new mage.players.Player[]{py, ai}) {
            p.setTestMode(true);
            mage.cards.decks.Deck deck = new mage.cards.decks.Deck();
            game.addPlayer(p, deck);
            match.addPlayer(p, deck);
        }
        String[] pyHand = {"Glimmer Seeker", "Cult Healer"}, aiHand = {"Murder", "Pyroclasm", "Vile Mutilator"};
        for (String n : pyHand) { Card c = make(game, n, py.getId()); py.getHand().add(c); game.getState().setZone(c.getId(), Zone.HAND); }
        for (String n : aiHand) { Card c = make(game, n, ai.getId()); ai.getHand().add(c); game.getState().setZone(c.getId(), Zone.HAND); }
        Card stick = make(game, "Osseous Sticktwister", ai.getId());
        PermanentCard perm = new PermanentCard(stick, ai.getId(), game);
        game.addPermanent(perm, 0);
        game.getState().setZone(stick.getId(), Zone.BATTLEFIELD);
        Ability trigger = perm.getAbilities().stream().filter(a -> a instanceof mage.abilities.TriggeredAbility).findFirst().get();
        trigger.setControllerId(ai.getId());
        trigger.setSourceId(perm.getId());
        for (mage.players.Player p : new mage.players.Player[]{py, ai}) p.beginTurn(game);  // fills each player's range
        trigger.getEffects().get(0).apply(game, trigger);

        boolean ok = true;
        List<String> offered = new ArrayList<>();
        for (JsonObject m : asked)
            if (m.get("prompt").getAsString().contains("discard cost"))
                for (JsonElement o : m.getAsJsonArray("options")) offered.add(o.getAsJsonObject().get("label").getAsString());
        System.out.println("prompts " + asked.stream().map(m -> m.get("kind").getAsString() + ": " + m.get("prompt").getAsString()).toList());
        System.out.println("discard options " + offered);
        System.out.println("hands after: PY " + py.getHand().size() + "/" + pyHand.length + ", AI " + ai.getHand().size() + "/" + aiHand.length);
        System.out.println("leaks " + link.leaks);
        if (offered.isEmpty()) { System.out.println("FAIL no discard choice was asked"); ok = false; }
        for (String l : offered) if (!Arrays.asList(pyHand).contains(l)) { System.out.println("FAIL offered a card not in our hand: " + l); ok = false; }
        if (py.getHand().size() != pyHand.length - 1) { System.out.println("FAIL our hand should lose one card"); ok = false; }
        if (ai.getHand().size() != aiHand.length) { System.out.println("FAIL opponent's hand changed"); ok = false; }
        if (!link.leaks.isEmpty()) { System.out.println("FAIL leak checker fired"); ok = false; }
        System.out.println(ok ? "PASS" : "FAILED");
        System.exit(ok ? 0 : 1);
    }
}
