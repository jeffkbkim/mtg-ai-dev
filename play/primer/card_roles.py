"""Write play/primer/dsk_card_roles.json: a one-line playing role per DSK card, used by primer v2 (players.py).

Rule-based from engine/vocab/dsk_card_text.json (types, cost, P/T, rules text), then hand corrections in OVERRIDES
for cards the rules misread. Re-run after changing the rules: python play/primer/card_roles.py
"""
import json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from render import BASICS, clean, load_card_text

OUT = Path(__file__).resolve().parent / "dsk_card_roles.json"
KEYWORDS = ("Flying", "Flash", "Deathtouch", "Lifelink", "Trample", "Menace", "First strike", "Double strike",
            "Vigilance", "Reach", "Haste", "Ward", "Defender")

REMOVAL = re.compile(r"destroy target (creature|nonland permanent|permanent)|deals? \d+ damage to target creature|"
                     r"deals? damage equal to .* to (target|another target) creature|gets -\d+/-\d+|"
                     r"exile target (creature|nonland)|fights? target|on (their choice of )?the top or bottom of"
                     r"|loses all abilities|"
                     r"target creature an opponent controls|creatures your opponents control get -", re.I)
TAGS = (("Eerie", "eerie"), ("Survival", "survival"), ("Delirium", "delirium"), ("When {this} enters", "ETB effect"),
        ("Whenever {this} attacks", "attack trigger"), ("Sacrifice another", "sac outlet"), ("can't block", "can't block"))
PUMP = re.compile(r"gets? \+(\d+)/\+(\d+)|gains? (deathtouch|indestructible|first strike|double strike|hexproof|flying)", re.I)

# hand corrections, keyed by card name (checked against the card text in engine/vocab/dsk_card_text.json)
OVERRIDES = {
    "Appendage Amalgam": "flash 3-drop body 3/2; ambush blocker",
    "Bear Trap": "removal: flash artifact, {3},T,sac: 3 damage to a creature",
    "Betrayer's Bargain": "removal: instant 5 damage (sac or pay {2})",
    # rares and mythics: how to use them
    "Tyvar, the Pummeler": "bomb: tap another creature for indestructible; {3}{G}{G} team pump for lethal",
    "Enduring Vitality": "3-drop; your creatures tap for any color (survival enabler); returns as an enchantment",
    "Enduring Curiosity": "flash 4-drop; card per combat hit; returns as an enchantment",
    "Enduring Innocence": "3-drop lifelink; draws when small creatures enter; returns as an enchantment",
    "Valgavoth's Onslaught": "bomb: X manifests with X +1/+1 counters each",
    "Abhorrent Oculus": "bomb: 3-mana flier (exile six from graveyard); manifests each opponent upkeep",
    "Unstoppable Slasher": "3-drop deathtouch; combat damage halves their life; returns once",
    "Screaming Nemesis": "3-drop haste; damage dealt to it is redirected",
    "Overlord of the Mistmoors": "bomb: impending {2}{W}{W} makes two 2/1 fliers now and on each attack",
    "Overlord of the Floodpits": "bomb: impending {1}{U}{U} draws 2 discards 1 now and on each attack",
    "Overlord of the Balemurk": "bomb: impending {1}{B} mills 4 and regrows a creature now and on each attack",
    "Overlord of the Boilerbilges": "bomb: impending {2}{R}{R} deals 4 damage now and on each attack",
    "Overlord of the Hauntwoods": "bomb: impending {1}{G}{G} ramps a land now and on each attack",
    "Unholy Annex // Ritual Chamber": "bomb Room: Unholy Annex draws each end step; Ritual Chamber 6/6 flying Demon makes it drain 2",
    "Split Up": "one-sided sweeper: destroy all tapped (after they attack) or all untapped creatures",
    "Entity Tracker": "flash 3-drop; draws a card on every eerie",
    "Ghostly Dancers": "5-drop flier; regrows an enchantment; 3/1 flier on every eerie",
    "The Swarmweaver": "4-drop + two 1/1 fliers; with delirium Insects/Spiders get +1/+1 deathtouch",
    "Patchwork Beastie": "1-drop 3/3; can't attack or block without delirium",
    "Clockwork Percussionist": "1-drop 1/1 haste; card when it dies",
    "Don't Make a Sound": "counter unless they pay {2}, instant {1}{U}",
    "Drag to the Roots": "removal: instant destroy nonland permanent (cheaper with delirium)",
    "Emerge from the Cocoon": "reanimation: return creature from your graveyard, gain 3",
    "Fear of Immobility": "4-drop 4/4 enchantment creature; taps a blocker on entry",
    "Floodpits Drowner": "flash 2-drop 2/1; taps and stuns an opposing creature",
    "Get Out": "counter creature/enchantment spell or bounce your own, instant {U}{U}",
    "Glimmerburst": "card draw: instant draw 2 + 1/1 Glimmer",
    "Growing Dread": "flash: manifest dread at instant speed; pumps flipped cards",
    "Live or Die": "removal or reanimation, instant {3}{B}{B}",
    "Manifest Dread": "2-mana 2/2 face down (choose from top 2)",
    "Murder": "removal: instant destroy creature",
    "Nowhere to Run": "removal: flash enchantment, -3/-3 on entry",
    "Scorching Dragonfire": "removal: instant 3 damage, exiles",
    "Seized from Slumber": "removal: instant destroy creature ({1}{W} if it's tapped)",
    "Shardmage's Rescue": "protection trick: flash aura, hexproof this turn, +1/+1",
    "Turn Inside Out": "trick: +3/+0 instant {R}; manifest dread if it dies",
    "Twist Reality": "counterspell or manifest dread, instant {1}{U}{U}",
    "Unable to Scream": "removal: aura, creature becomes 0/2 with no abilities",
    "Unwanted Remake": "removal: instant destroy creature (they manifest dread)",
    "Vanish from Sight": "removal: instant put nonland permanent on top/bottom of library",
    "Winter's Intervention": "removal: instant 2 damage, gain 2",
    "Withering Torment": "removal: instant destroy creature or enchantment",
    "Impossible Inferno": "removal: instant 6 damage to a creature",
    "Jump Scare": "trick: +2/+2 and flying, instant {W}",
    "Give In to Violence": "trick: +2/+2 and lifelink, instant {1}{B}",
    "Horrid Vigor": "trick: deathtouch + indestructible, instant {1}{G}",
    "Frantic Strength": "trick: flash aura +2/+2 trample {2}{G}",
    "Violent Urge": "trick: +1/+0 first strike (double strike with delirium), instant {R}",
    "Untimely Malfunction": "instant {1}{R}: two creatures can't block, or redirect a spell, or kill artifact",
    "Fear of Impostors": "flash 3-drop 3/2; counters a spell",
    "Entity Tracker": "flash 3-drop 2/3; draws on eerie",
    "Enduring Curiosity": "flash 4-drop 4/3; card per combat hit",
    "Rite of the Moth": "reanimation: sorcery, with flashback",
    "Monstrous Emergence": "removal: sorcery {1}{G}, damage equal to a creature's power",
    "Say Its Name": "self-mill 3, return creature or land; delirium enabler",
    "Final Vengeance": "removal: sorcery {B}, exile creature (sac a creature or enchantment)",
    "Trapped in the Screen": "removal: enchantment (ward 2) exiles artifact/creature/enchantment until it leaves",
    "Fear of Lost Teeth": "1-drop 1/1; 1 damage + 1 life when it dies",
    "Glassworks // Shattered Yard": "Room: Glassworks 4 damage to a creature on unlock; Shattered Yard pings each opponent at end step",
    "Baseball Bat": "equipment +1/+1, taps a blocker when it attacks",
    "Beastie Beatdown": "removal: sorcery, your creature hits theirs (+2 counters with delirium)",
    "Bottomless Pool // Locker Room": "Room: Bottomless Pool {U} bounce a creature; Locker Room {4}{U} draw on combat damage",
    "Break Down the Door": "instant {2}{G}: exile artifact/enchantment or manifest dread",
    "Cathartic Parting": "answer to an artifact/enchantment, sorcery",
    "Central Elevator // Promising Stairs": "Room: Central Elevator {3}{U} tutor a Room; Promising Stairs {2}{U} surveil each upkeep",
    "Chainsaw": "removal: 3 damage on entry; equipment grows as creatures die",
    "Charred Foyer // Warped Space": "Room: Charred Foyer {3}{R} card advantage each upkeep; Warped Space {4}{R}{R}",
    "Collected Company": "instant {3}{G}: up to two creatures (mv 3 or less) from top 6",
    "Come Back Wrong": "removal: sorcery, destroy and borrow the creature",
    "Commune with Evil": "card selection + self-mill 3, gain 3",
    "Conductive Machete": "equipment: manifest dread with +2/+1",
    "Coordinated Clobbering": "removal: sorcery {G}, tap one or two of yours to hit a creature",
    "Cracked Skull": "discard their best nonland card; aura kills a creature when damaged",
    "Cursed Windbreaker": "equipment: manifest dread with flying",
    "Damnation": "sweeper: destroy all creatures",
    "Dazzling Theater // Prop Room": "Room: convoke for creatures; Prop Room untaps your creatures on their turn",
    "Defiled Crypt // Cadaver Lab": "Room: Defiled Crypt 2/2s when cards leave graveyard; Cadaver Lab {B} regrow a creature",
    "Demonic Counsel": "tutor a Demon (any card with delirium)",
    "Derelict Attic // Widow's Walk": "Room: Derelict Attic {2}{B} draw 2; Widow's Walk lone attacker +1/+0 deathtouch",
    "Dissection Tools": "equipment: manifest dread with +2/+2 deathtouch lifelink",
    "Disturbing Mirth": "sac outlet: sac to draw 2; manifests when sacrificed",
    "Dollmaker's Shop // Porcelain Gallery": "Room: 1/1 Toys when you attack; Porcelain Gallery finisher",
    "Duskmourn's Domination": "removal: aura steals a creature (-3/-0, no abilities)",
    "Enter the Enigma": "cantrip: a creature can't be blocked this turn",
    "Ethereal Armor": "aura: +1/+1 per enchantment, first strike",
    "Exorcise": "removal: sorcery, exile power 4+ creature, artifact or enchantment",
    "Found Footage": "clue: see face-down creatures; {2}: surveil 2 and draw",
    "Funeral Room // Awakening Hall": "Room: drain on your creature deaths; Awakening Hall mass reanimation",
    "Ghost Vacuum": "graveyard hate",
    "Glimmerlight": "equipment +1/+1, comes with a 1/1 Glimmer",
    "Grab the Prize": "card draw: discard 1, draw 2 (2 damage if nonland)",
    "Grand Entryway // Elegant Rotunda": "Room: Grand Entryway {1}{W} 1/1 Glimmer; Elegant Rotunda {2}{W} +1/+1 counters on two",
    "Greenhouse // Rickety Gazebo": "Room: mana fixing; Rickety Gazebo mill 4, keep two permanents",
    "Hedge Shredder": "vehicle (crew 1): mills, lands milled go onto the battlefield",
    "Kaito, Bane of Nightmares": "planeswalker: card advantage, ninjutsu",
    "Let's Play a Game": "sorcery: -1/-1 sweep, discard 2 or drain 3 (more with delirium)",
    "Meat Locker // Drowned Diner": "Room: Meat Locker {2}{U} tap + 2 stun counters; Drowned Diner {3}{U}{U} draw 3 discard 1",
    "Midnight Mayhem": "sorcery: three 1/1 Gremlins, menace lifelink haste this turn",
    "Mirror Room // Fractured Realm": "Room: copy your creature; Fractured Realm doubles triggers",
    "Moldering Gym // Weight Room": "Room: Moldering Gym {2}{G} ramp; Weight Room {5}{G} 5/5 manifest",
    "Painter's Studio // Defaced Gallery": "Room: card advantage; Defaced Gallery {1}{R} attackers +1/+0",
    "Peer Past the Veil": "card draw: discard hand, draw one per card type in graveyard",
    "Pyroclasm": "sweeper: 2 damage to each creature",
    "Restricted Office // Lecture Hall": "Room: Restricted Office sweeper of power 3+; Lecture Hall hexproof",
    "Roaring Furnace // Steaming Sauna": "Room: Roaring Furnace removal (1 damage per card in hand); Steaming Sauna draw each end step",
    "Saw": "equipment +2/+0; sac a permanent to draw when it attacks",
    "Sheltered by Ghosts": "removal: aura exiles a nonland permanent; +1/+0 lifelink ward 2",
    "Smoky Lounge // Misty Salon": "Room: Room ramp; Misty Salon X/X flyer",
    "Sporogenic Infection": "removal: edict (they sacrifice a creature)",
    "Split Up": "sweeper: destroy all tapped or all untapped creatures",
    "Stay Hidden, Stay Silent": "removal: aura taps and locks a creature",
    "Surgical Suite // Hospital Room": "Room: Surgical Suite {1}{W} reanimate mv 3 or less; Hospital Room counters on attack",
    "The Tale of Tamiyo": "saga: self-mill, then card draw",
    "Threats Around Every Corner": "manifest dread engine, ramp when face-down creatures enter",
    "Ticket Booth // Tunnel of Hate": "Room: Ticket Booth {2}{R} manifest dread; Tunnel of Hate double strike on attack",
    "Trial of Agony": "removal: sorcery {R}, 5 damage to one of two creatures (their pick)",
    "Under the Skin": "manifest dread + return a permanent card from graveyard",
    "Underwater Tunnel // Slimy Aquarium": "Room: Underwater Tunnel {U} surveil 2; Slimy Aquarium {3}{U} 3/3 manifest",
    "Unholy Annex // Ritual Chamber": "Room: draw each end step; Ritual Chamber 6/6 flying Demon",
    "Unidentified Hovership": "removal: flying vehicle exiles toughness 5 or less while it stays",
    "Unnerving Grasp": "tempo: bounce a nonland permanent + manifest dread",
    "Valgavoth's Onslaught": "X manifests with X counters (finisher)",
    "Vengeful Possession": "threaten: steal a creature for a turn (great with sacrifice)",
    "Walk-In Closet // Forgotten Cellar": "Room: replay lands and spells from graveyard",
    "Waltz of Rage": "sweeper: your creature hits every other creature",
    "Sacrifice": "ritual: sac a creature for mana",
    "Grievous Wound": "aura on a player: no lifegain, damage halves life",
    "Hallowed Haunting": "enchantment payoff",
}


def role(c):
    if c["name"] in OVERRIDES:
        return OVERRIDES[c["name"]]
    types, cost = c["types"], c["cost"]
    if "left" in c:
        doors = []
        for h in (c["left"], c["right"]):
            t = clean(" ".join(h["rules"]))
            doors.append(f"{h['name']} {h['cost']}" + (" removal" if REMOVAL.search(t) else " draw" if "draw" in t.lower() else ""))
        return "Room: " + "; ".join(doors)
    rules = clean(" ".join(c.get("rules", [])))
    if "Land" in types:
        return "land: " + ", ".join(re.findall(r"Add \{(\w)\}", rules)) if "Add" in rules else "land"
    instant = "Instant" in types or "Flash" in rules
    speed = "instant" if instant else "sorcery" if "Sorcery" in types else ""
    if "Creature" in types:
        pt, mv = c.get("pt", "?/?"), c["mana_value"]
        kws = [k.lower() for k in KEYWORDS if re.search(r"\b" + k + r"\b", rules)]
        p = int(pt.split("/")[0]) if pt.split("/")[0].isdigit() else 0
        what = "finisher" if mv >= 5 and p >= 4 else f"{mv}-drop body"
        extra = []
        if "Impending" in rules:
            extra.append("impending (cast early, becomes creature later)")
        if REMOVAL.search(rules):
            extra.append("removal on a body")
        elif "draw" in rules.lower():
            extra.append("card advantage")
        if "manifest dread" in rules.lower():
            extra.append("manifests")
        extra += [tag for word, tag in TAGS if word in rules]
        return what + ("; " + "; ".join(extra) if extra else "")  # P/T and keywords are in the card text
    if "Counter target" in rules:
        return f"counterspell, {speed} {cost}"
    if "Aura" in types and PUMP.search(rules):
        return ("trick: flash aura " if instant else "aura: ") + PUMP.search(rules).group(0) + f" {cost}"
    if REMOVAL.search(rules):
        return f"removal: {speed or types.strip('[]').lower()} {cost}".replace("  ", " ")
    if PUMP.search(rules) and ("Instant" in types or "Sorcery" in types):
        return f"{'trick' if instant else 'pump'}: {PUMP.search(rules).group(0)} {speed} {cost}"
    if "return target creature card" in rules.lower() or "from your graveyard to the battlefield" in rules.lower():
        return f"reanimation {cost}"
    if "Equipment" in types:
        return f"equipment {cost}"
    if "Vehicle" in types:
        return f"vehicle {cost}"
    if "manifest dread" in rules.lower():
        return f"manifest dread {cost}"
    if "draw" in rules.lower():
        return f"card draw {speed} {cost}".replace("  ", " ")
    return f"{types.strip('[]').split(']')[0].lower()} {cost}"


def main():
    texts = load_card_text()
    roles = {n: role(c) for n, c in sorted(texts.items()) if n not in BASICS and "Land" not in c["types"]}
    OUT.write_text(json.dumps(roles, indent=0, ensure_ascii=False) + "\n")
    print(len(roles), "roles ->", OUT)


if __name__ == "__main__":
    main()
