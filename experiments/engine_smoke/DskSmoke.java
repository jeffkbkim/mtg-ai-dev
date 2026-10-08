import mage.cards.Card;
import mage.cards.decks.Deck;
import mage.cards.decks.importer.DeckImporter;
import mage.cards.repository.CardScanner;
import mage.cards.repository.RepositoryUtil;
import mage.constants.*;
import mage.game.*;
import mage.game.match.*;
import mage.game.mulligan.MulliganType;
import mage.player.ai.ComputerPlayer7;
import mage.players.Player;
import mage.util.RandomUtil;
import java.nio.file.*;
import java.util.*;

/** Rules-engine smoke test using the bundled heuristic bot; no learned policy. */
public class DskSmoke {
    static Deck load(String path) throws Exception {
        Deck deck = Deck.load(DeckImporter.importDeckFromFile(path, true), false, false);
        Map<String, Integer> wanted = new TreeMap<>(), actual = new TreeMap<>();
        for (String line : Files.readAllLines(Path.of(path))) {
            if (!line.matches("^[0-9]+ .*")) continue;
            String name = line.substring(line.indexOf("] ") + 2);
            wanted.merge(name, Integer.parseInt(line.split(" ")[0]), Integer::sum);
        }
        for (Card card : deck.getMaindeckCards()) actual.merge(card.getName(), 1, Integer::sum);
        if (!wanted.equals(actual) || deck.getMaindeckCards().size() != 40)
            throw new IllegalStateException("Deck mismatch: expected=" + wanted + " actual=" + actual);
        System.out.println("DECK_OK " + path + " cards=40 distinct=" + actual.size());
        return deck;
    }
    public static void main(String[] args) throws Exception {
        long boot = System.nanoTime();
        RepositoryUtil.bootstrapLocalDb();
        CardScanner.scan();
        System.out.printf("BOOT_SECONDS %.3f%n", (System.nanoTime()-boot)/1e9);
        for (int i=0; i<4; i++) {
            long seed = 20261007L + i/2;
            RandomUtil.setSeed(seed);
            Game game = new TwoPlayerDuel(MultiplayerAttackOption.LEFT, RangeOfInfluence.ONE,
                MulliganType.GAME_DEFAULT.getMulligan(0), 40, 20, 7);
            Match match = new TwoPlayerMatch(new MatchOptions("DSK smoke", "Two Player Duel", false));
            ComputerPlayer7 a = new ComputerPlayer7("UG", RangeOfInfluence.ONE, 2);
            ComputerPlayer7 b = new ComputerPlayer7("UW", RangeOfInfluence.ONE, 2);
            a.setMaxThinkTimeSecs(1);
            b.setMaxThinkTimeSecs(1);
            for (int seat=0; seat<2; seat++) {
                Player p = seat==0 ? a : b;
                p.setTestMode(true);
                Deck deck = load(args[seat]);
                game.loadCards(deck.getCards(), p.getId());
                game.addPlayer(p, deck);
                match.addPlayer(p, deck);
            }
            GameOptions options = new GameOptions();
            options.testMode = true;
            options.stopOnTurn = 100;
            options.stopAtStep = PhaseStep.END_TURN;
            game.setGameOptions(options);
            game.setStartingPlayerId(i%2==0 ? a.getId() : b.getId());
            long start = System.nanoTime();
            game.start(null);
            boolean terminal = a.hasWon() || b.hasWon() || (a.hasLost() && b.hasLost());
            System.out.printf("RESULT index=%d seed=%d first=%s terminal=%s winner=%s turns=%d seconds=%.3f life_ug=%d life_uw=%d%n",
                i, seed, i%2==0 ? "UG":"UW", terminal, game.getWinner(), game.getTurnNum(),
                (System.nanoTime()-start)/1e9, a.getLife(), b.getLife());
            if (!terminal) throw new IllegalStateException("Game reached cap without a terminal result");
        }
        System.exit(0);
    }
}
