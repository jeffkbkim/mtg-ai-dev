/**
 * Collective Brutality (escalate: discard a card for each mode beyond the first). XMage's Modes.choose asks for modes
 * until the maximum and takes a null answer as "done"; the seat never offered DONE, so the player was forced into a
 * second mode, escalate then needed a discard, and with Brutality alone in hand the cast was refused (cube02 part54,
 * three times). With Brutality alone in hand and a Grizzly Bears to shrink: the first mode prompt has no DONE, the
 * second has, the player picks -2/-2 then DONE, and Brutality goes on the stack with one mode. With an Island in hand
 * too: -2/-2 and the drain, then DONE is not needed (third mode is the reveal), the Island is discarded, two modes.
 * Prints PASS or FAIL and exits 1 on FAIL.
 */
public class EscalateCheck {
    public static void main(String[] args) throws Exception {
        CubeCastHarness.bootstrap();
        CubeCastHarness.finish(oneMode() & twoModes());
    }

    static boolean oneMode() throws Exception {
        CubeCastHarness h = new CubeCastHarness(".*Cast Collective Brutality.*", ".*-2/-2.*", "DONE");
        h.battlefield(h.py, "Swamp", "Swamp");
        h.battlefield(h.ai, "Grizzly Bears");
        mage.cards.Card spell = h.hand("Collective Brutality");
        h.start();
        String refused = h.priority();
        mage.game.stack.Spell s = h.game.getStack().getSpell(spell.getId());
        int modes = s == null ? 0 : s.getSpellAbility().getModes().getSelectedModes().size();
        java.util.List<String> modePrompts = new java.util.ArrayList<>();
        for (String l : h.log) if (l.startsWith("MODE")) modePrompts.add(l);
        boolean doneLater = modePrompts.size() >= 2 && !modePrompts.get(0).contains("DONE") && modePrompts.get(1).contains("DONE");
        System.out.println("alone in hand: on the stack " + (s != null) + ", modes " + modes + ", DONE from the second prompt " + doneLater + " " + refused);
        System.out.println("  " + modePrompts);
        return s != null && modes == 1 && doneLater;
    }

    static boolean twoModes() throws Exception {
        CubeCastHarness h = new CubeCastHarness(".*Cast Collective Brutality.*", ".*-2/-2.*", ".*loses 2 life.*", "Island");
        h.battlefield(h.py, "Swamp", "Swamp");
        h.battlefield(h.ai, "Grizzly Bears");
        mage.cards.Card spell = h.hand("Collective Brutality");
        mage.cards.Card island = h.hand("Island");
        h.start();
        String refused = h.priority();
        mage.game.stack.Spell s = h.game.getStack().getSpell(spell.getId());
        int modes = s == null ? 0 : s.getSpellAbility().getModes().getSelectedModes().size();
        boolean discarded = h.game.getState().getZone(island.getId()) == mage.constants.Zone.GRAVEYARD;
        System.out.println("with an Island: on the stack " + (s != null) + ", modes " + modes + ", Island discarded " + discarded + " " + refused);
        return s != null && modes == 2 && discarded;
    }
}
