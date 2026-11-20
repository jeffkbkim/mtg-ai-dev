/**
 * Kroxa, Titan of Death's Hunger was offered and then refused (cube02 part56, cube03 part17), with no choices asked:
 * - escape ({B}{B}{R}{R}, exile five other cards from your graveyard) on the cube02 board: Volcanic Island, Scrubland,
 *   Tundra, Island, Tropical Island, Raffine's Tower, Raucous Theater, Forest, every colour pair covered exactly once;
 * - the hand cast ({B}{R}) from Raucous Theater + Scrubland (cube03).
 * Both were the payer spending a dual land on the wrong colour (fixed in main before this check). Each must put
 * Kroxa on the stack; escape must exile five cards. Prints PASS or FAIL and exits 1 on FAIL.
 */
public class KroxaEscapeCheck {
    public static void main(String[] args) throws Exception {
        CubeCastHarness.bootstrap();
        CubeCastHarness.finish(escape() & handCast());
    }

    static boolean escape() throws Exception {
        CubeCastHarness h = new CubeCastHarness(".*Cast Kroxa.*with Escape");
        h.battlefield(h.py, "Volcanic Island", "Scrubland", "Tundra", "Island", "Tropical Island", "Raffine's Tower", "Raucous Theater", "Forest");
        mage.cards.Card kroxa = h.graveyard("Kroxa, Titan of Death's Hunger");
        for (String n : new String[]{"Ancestral Recall", "Sheoldred's Edict", "Mana Drain", "Wooded Foothills", "Savannah", "Entomb"}) h.graveyard(n);
        h.start();
        String refused = h.priority();
        boolean cast = h.game.getStack().getSpell(kroxa.getId()) != null;
        int exiled = h.game.getExile().getAllCards(h.game).size();
        System.out.println("escape: on the stack " + cast + ", exiled " + exiled + " " + refused + " " + h.log);
        return cast && exiled == 5;
    }

    static boolean handCast() throws Exception {
        CubeCastHarness h = new CubeCastHarness(".*Cast Kroxa.*");
        h.battlefield(h.py, "Raucous Theater", "Scrubland");
        mage.cards.Card kroxa = h.hand("Kroxa, Titan of Death's Hunger");
        h.start();
        String refused = h.priority();
        boolean cast = h.game.getStack().getSpell(kroxa.getId()) != null;
        System.out.println("hand cast: on the stack " + cast + " " + refused);
        return cast;
    }
}
