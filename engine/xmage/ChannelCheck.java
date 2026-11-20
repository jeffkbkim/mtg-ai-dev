/**
 * Channel ("until end of turn, any time you could activate a mana ability, you may pay 1 life; if you do, add {C}").
 * XMage makes it a SpecialAction (SPECIAL_MANA_PAYMENT) kept in the game state, on no object: getPlayable never lists
 * it, ComputerPlayer's payer never uses it and the available mana never counts it, so Emrakul/Ulamog were never
 * offered (cube02 review, 4 games). After Channel resolves, with one Forest and one Mountain untapped and Emrakul, the
 * Aeons Torn ({15}) in hand, at 20 life: priority must offer Channel's "Pay 1 life: Add {C}" and the Emrakul cast;
 * taking Channel's action floats {C} for 1 life; casting Emrakul then puts it on the stack, tapping both lands and
 * paying the other 12 with life (20 - 1 - 12 = 7). Prints PASS or FAIL and exits 1 on FAIL.
 */
public class ChannelCheck {
    public static void main(String[] args) throws Exception {
        CubeCastHarness.bootstrap();
        CubeCastHarness h = new CubeCastHarness(".*Cast Channel.*");
        h.battlefield(h.py, "Forest", "Forest", "Forest", "Mountain");
        mage.cards.Card emrakul = h.hand("Emrakul, the Aeons Torn");
        h.hand("Channel");
        h.start();
        String refused = h.priority();
        boolean channelCast = h.stackTop() != null && h.stackTop().getName().equals("Channel");
        if (channelCast) h.resolveTop();
        h.log.clear();
        h.prefs.clear();
        h.prefs.add(".*Pay 1 life: Add \\{C\\}.*");
        refused += h.priority();
        boolean offeredChannel = h.log.stream().anyMatch(l -> l.startsWith("PRIORITY") && l.contains("Pay 1 life: Add {C}"));
        boolean offeredEmrakul = h.log.stream().anyMatch(l -> l.startsWith("PRIORITY") && l.contains("Cast Emrakul"));
        boolean floated = h.py.getManaPool().getMana().getColorless() == 1 && h.py.getLife() == 19;
        h.prefs.clear();
        h.prefs.add(".*Cast Emrakul.*");
        refused += h.priority();
        boolean cast = h.game.getStack().getSpell(emrakul.getId()) != null;
        long untapped = h.game.getBattlefield().getAllActivePermanents(h.py.getId()).stream().filter(p -> !p.isTapped()).count();
        System.out.println("Channel resolved " + channelCast + "; offered Channel's mana " + offeredChannel + ", Emrakul " + offeredEmrakul
                + "; floated {C} for 1 life " + floated + "; Emrakul on the stack " + cast + ", life " + h.py.getLife()
                + ", untapped lands " + untapped + " " + refused);
        h.log.forEach(l -> System.out.println("  " + l));
        CubeCastHarness.finish(channelCast && offeredChannel && offeredEmrakul && floated && cast && h.py.getLife() == 7 && untapped == 0);
    }
}
