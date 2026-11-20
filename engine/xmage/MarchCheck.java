/**
 * March of Otherworldly Light ({X}{W}; "as an additional cost to cast this spell, you may exile any number of white
 * cards from your hand. This spell costs {2} less to cast for each card exiled this way"). XMage's
 * ExileCardsFromHandAdjuster asks Player.getAmount(0, white cards in hand, "Choose how many white cards from your hand
 * to exile") and then which cards (a TargetCardInHand). The seat's getAmount was XMage's AI (fallback AMOUNT), so
 * the number was taken without asking: cube02 review, 5 games. Two Plains, March and Swords to Plowshares in hand,
 * X = 1 on Thraben Inspector: the player must be asked how many white cards to exile, and answering 1 (an option
 * labelled with 1) must exile Swords, cast March for {W}{1} - {2} = {W}, leaving a Plains untapped.
 * Prints PASS or FAIL and exits 1 on FAIL.
 */
public class MarchCheck {
    public static void main(String[] args) throws Exception {
        CubeCastHarness.bootstrap();
        CubeCastHarness h = new CubeCastHarness(".*Cast March of Otherworldly Light.*", "X = 1", "(.*\\D)?1", "Swords to Plowshares");
        h.battlefield(h.py, "Plains", "Plains");
        h.battlefield(h.ai, "Thraben Inspector");
        mage.cards.Card march = h.hand("March of Otherworldly Light");
        mage.cards.Card swords = h.hand("Swords to Plowshares");
        h.start();
        String refused = h.priority();
        boolean cast = h.game.getStack().getSpell(march.getId()) != null;
        boolean asked = h.log.stream().anyMatch(l -> l.toLowerCase().contains("white cards"));
        boolean exiled = h.game.getState().getZone(swords.getId()) == mage.constants.Zone.EXILED;
        long untapped = h.game.getBattlefield().getAllActivePermanents(h.py.getId()).stream().filter(p -> !p.isTapped()).count();
        System.out.println("asked how many white cards " + asked + "; March on the stack " + cast + ", Swords exiled " + exiled
                + ", untapped Plains " + untapped + " " + refused);
        h.log.forEach(l -> System.out.println("  " + l));
        CubeCastHarness.finish(asked && cast && exiled && untapped == 1);
    }
}
