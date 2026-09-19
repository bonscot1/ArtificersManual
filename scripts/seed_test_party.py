"""Three made-up level-2 characters for trying the site out.

    python scripts/seed_test_party.py            # skips names that already exist
    python scripts/seed_test_party.py --replace  # overwrite them

Every race, class, background, spell, feat and option is looked up in the enabled
books, so the numbers are real: point-buy scores plus racial bonuses, max hit die at
level 1 then the fixed average, attacks from the weapon tables.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.compendium import format as fmt  # noqa: E402
from app.compendium import rules  # noqa: E402
from app.compendium.loader import Compendium  # noqa: E402
from app.config import load_settings  # noqa: E402
from app.db import Character, make_engine, make_session_factory  # noqa: E402
from app.sheet import build_sheet, default_hp  # noqa: E402

PARTY = [
    dict(
        name="Bramblewick Tosscobble", player="Sam", race="Halfling|PHB||Lightfoot|PHB", cls="Rogue|PHB",
        background="Criminal|PHB", level=2, alignment="Chaotic Neutral", xp=300,
        # point buy 8/15/14/10/13/12, Lightfoot +2 Dex +1 Cha
        scores=dict(str=8, dex=17, con=14, int=10, wis=13, cha=13),
        ac=14, speed=25,                                   # leather armour + Dex
        skills=["Acrobatics", "Deception", "Insight", "Perception", "Sleight of Hand", "Stealth"],
        expertise=["Stealth", "Sleight of Hand"],
        weapons=["Shortsword", "Shortbow", "Dagger"],
        inventory=[("Leather Armor", 1), ("Shortsword", 1), ("Shortbow", 1), ("Arrows (20)", 1), ("Dagger", 2),
                   ("Thieves' Tools", 1), ("Burglar's Pack", 1), ("Crowbar", 1), ("Dark common clothes with a hood", 1),
                   ("Playing card set", 1)],
        gp=15,
        other_profs="Armour: light. Weapons: simple, hand crossbows, longswords, rapiers, shortswords. "
                    "Tools: thieves' tools, playing cards. Languages: Common, Halfling.",
        appearance="age 27 · 3 ft 1 · 41 lb · eyes hazel · hair dark curls · a chipped front tooth",
        personality="Personality: I always have a plan for what to do when things go wrong. I never pass up a wager.\n\n"
                    "Ideals: Freedom. Chains are meant to be broken, as are those who would forge them.\n\n"
                    "Bonds: Someone I loved died because of a mistake I made. That will never happen again.\n\n"
                    "Flaws: When I see something valuable, I can't think about anything but how to steal it.",
        backstory="Wick grew up in the river barges below Daggerford, the fourth of nine children and the only one who "
                  "could open a lock by ear. The Lamplighters - a smuggling ring that runs untaxed lamp oil up the "
                  "Delimbiyr - took him on at twelve as a lookout and kept him as a locksmith. He was good, and he "
                  "was careless: a job on a merchant's strongroom went wrong when he misread a trap, and his cousin "
                  "Tilda, who had insisted on coming, took the crossbow bolt meant for him.\n\nHe paid the ring what he "
                  "owed, buried Tilda properly, and left the barges. He tells people he is retired. He still checks "
                  "every door he walks through for a second lock.",
        allies="The Lamplighters (Daggerford smugglers) - former employers, owed nothing, trusted less.\n"
               "Old Harrow - fence in the Daggerford fish market; will buy anything, will sell Wick out for enough.\n"
               "Tilda Tosscobble - cousin, dead. Wick carries her lockpicks.",
        notes_dm="Tilda is not dead. The bolt put her in a fever for a month and she woke to find Wick gone and the "
                 "Lamplighters saying he had run with the take. She has been looking for him for two years - to hear "
                 "his side, or to settle it. She is now a bounty-runner working out of Daggerford's Lady Luck tavern.",
    ),
    dict(
        name="Sister Maelis Orrin", player="Priya", race="Human|PHB||Variant|PHB", cls="Cleric|PHB", subclass="Life|PHB",
        background="Acolyte|PHB", level=2, alignment="Lawful Good", xp=300,
        # point buy 13/10/13/10/15/12, variant human +1 Con +1 Wis, skill Medicine, feat Tough
        scores=dict(str=13, dex=10, con=14, int=10, wis=16, cha=12),
        ac=18, speed=30, hp_bonus=4,                       # chain mail + shield; Tough gives +2 per level
        skills=["History", "Insight", "Medicine", "Persuasion", "Religion"], expertise=[],
        feats=["Tough|PHB"],
        weapons=["Mace", "Light Crossbow"],
        spells=["Sacred Flame|PHB", "Guidance|PHB", "Spare the Dying|PHB", "Healing Word|PHB", "Guiding Bolt|PHB",
                "Shield of Faith|PHB", "Sanctuary|PHB", "Protection from Evil and Good|PHB"],
        prepared=["Healing Word|PHB", "Guiding Bolt|PHB", "Shield of Faith|PHB"],   # Bless + Cure Wounds are domain spells
        counters=[("Channel Divinity", 1, "short")],
        inventory=[("Chain Mail", 1), ("Shield", 1), ("Mace", 1), ("Light Crossbow", 1), ("Crossbow Bolts (20)", 1),
                   ("Priest's Pack", 1), ("Holy Symbol", 1), ("Prayer Book", 1), ("Incense", 5), ("Vestments", 1),
                   ("Common Clothes", 1)],
        gp=15,
        other_profs="Armour: light, medium, heavy, shields. Weapons: simple. Languages: Common, Celestial, Dwarvish.",
        appearance="age 34 · 5 ft 6 · 150 lb · eyes grey · hair cropped, greying early · burn scar on the left hand",
        personality="Personality: I quote sacred texts in almost every situation. I am tolerant of other faiths and "
                    "respect the worship of other gods.\n\nIdeals: Charity. I always try to help those in need, no "
                    "matter the cost.\n\nBonds: I owe my life to the priest who took me in when my parents died.\n\n"
                    "Flaws: I judge others harshly, and myself more harshly still.",
        backstory="Maelis was left at the door of the Temple of Ilmater in Daggerford the winter her parents died of "
                  "the coughing sickness, and Brother Aldous, who found her, raised her among the sickbeds. She learned "
                  "to set bones before she learned her letters. The burn on her hand is from the night the infirmary "
                  "caught fire and she went back in for a patient nobody else would carry.\n\nShe was ordained at "
                  "twenty-five and has spent nine years as the temple's field healer, walking the villages up the "
                  "river. When people began disappearing near the old manor she went to the council and asked to be "
                  "sent. They told her healers do not go into haunted houses. She went anyway.",
        allies="Temple of Ilmater, Daggerford - home; Brother Aldous (elderly, failing) raised her.\n"
               "The Ferry Wardens - river-folk who owe her for a plague year; will carry her anywhere for free.",
        notes_dm="Brother Aldous did not find Maelis by chance. Her parents did not die of the coughing sickness - "
                 "they were cultists of the manor's old master, and Aldous took the child to keep her from them. He "
                 "has a letter in her mother's hand, sealed, that he has never given her. He will not live out the year.",
    ),
    dict(
        name="Ysolde Varn", player="Tom", race="Tiefling|PHB||", cls="Warlock|PHB", subclass="Fiend|PHB",
        background="Charlatan|PHB", level=2, alignment="Chaotic Neutral", xp=300,
        # point buy 8/14/14/10/10/15, Tiefling +1 Int +2 Cha
        scores=dict(str=8, dex=14, con=14, int=11, wis=10, cha=17),
        ac=13, speed=30,                                   # leather armour + Dex
        skills=["Arcana", "Deception", "Intimidation", "Sleight of Hand"], expertise=[],
        options=["Agonizing Blast|PHB", "Devil's Sight|PHB"],
        weapons=["Dagger", "Light Crossbow"],
        spells=["Eldritch Blast|PHB", "Minor Illusion|PHB", "Hex|PHB", "Armor of Agathys|PHB", "Burning Hands|PHB"],
        prepared=["Hex|PHB", "Armor of Agathys|PHB", "Burning Hands|PHB"],
        inventory=[("Leather Armor", 1), ("Light Crossbow", 1), ("Crossbow Bolts (20)", 1), ("Dagger", 2),
                   ("Arcane Focus (rod)", 1), ("Scholar's Pack", 1), ("Disguise Kit", 1), ("Fine Clothes", 1),
                   ("Weighted dice", 1), ("Signet ring of an imaginary duke", 1)],
        gp=15,
        other_profs="Armour: light. Weapons: simple. Tools: disguise kit, forgery kit. Languages: Common, Infernal.",
        appearance="age 24 · 5 ft 9 · 140 lb · eyes solid gold · skin dusky red · small backswept horns · a tail she "
                   "hides under long coats",
        personality="Personality: I fall in and out of love easily, and am always pursuing someone. Flattery is my "
                    "preferred trick for getting what I want.\n\nIdeals: Independence. I am a free spirit - no one "
                    "tells me what to do.\n\nBonds: A powerful person killed someone I love. Some day soon, I'll have "
                    "my revenge.\n\nFlaws: I can't resist a pretty face, or a locked box.",
        backstory="Ysolde was the third daughter of a Waterdeep counting-house and the first to be shown the door, "
                  "after a season of forged letters of credit that very nearly worked. She drifted down the Trade Way "
                  "selling titles she did not hold to people who wanted to believe her, and she was good enough at it "
                  "to attract attention.\n\nThe attention came in a dream, then in a contract. The thing that offered "
                  "her power called itself a patron and never gave a name; it wanted only that she keep taking, and "
                  "keep climbing. She signed. The eldritch blast works. The nightmares are the interest on the loan. "
                  "She came to Daggerford because a man there sold her sister a cure that was poison, and she intends "
                  "to sell him something in return.",
        allies="Coster Varn & Daughters, Waterdeep - family counting-house; will not acknowledge her.\n"
               "Perrin Halfmoon - halfling fence and forger in Daggerford; a partner in three cons, owed a fourth.\n"
               "Enemy: Dorran Vell, apothecary of Daggerford - sold her sister the 'cure'.",
        notes_dm="Her patron is the pit fiend Amaimon, who holds a very old claim on the Varn line: her great-"
                 "grandfather sold the family's firstborns for the counting-house's first fortune. Ysolde was never "
                 "the firstborn - the contract is a fraud on the fraudster, and Amaimon knows it. Dorran Vell did not "
                 "poison her sister; the sister is alive, disgraced, and hiding in Daggerford under another name.",
    ),
]


def build(spec: dict, comp: Compendium) -> Character:
    race_key, _, subrace_key = spec["race"].partition("||")
    cls = comp.classes[spec["cls"]]
    bg = comp.backgrounds[spec["background"]]
    race = comp.merged_race(race_key, subrace_key)
    assert race and bg, spec["name"]
    ch = Character(name=spec["name"], player=spec["player"], race_key=race_key, subrace_key=subrace_key,
                   class_key=spec["cls"], subclass_key=spec.get("subclass", ""), background_key=spec["background"],
                   level=spec["level"], alignment=spec["alignment"], xp=spec["xp"])
    for ab, v in spec["scores"].items():
        setattr(ch, f"score_{ab}", v)
    mods = {ab: rules.ability_mod(v) for ab, v in spec["scores"].items()}
    ch.hp_max = ch.hp_current = default_hp(cls, spec["level"], mods["con"]) + spec.get("hp_bonus", 0)
    ch.ac, ch.speed = spec["ac"], spec["speed"]
    ch.save_profs = list(cls["proficiency"])
    ch.skill_profs, ch.skill_expertise = spec["skills"], spec["expertise"]
    ch.other_profs = spec["other_profs"]
    for key in spec.get("spells", []):
        assert key in comp.spells, key
    ch.spells = [{"key": k, "prepared": comp.spells[k]["level"] == 0 or k in spec.get("prepared", [])}
                 for k in spec.get("spells", [])]
    for key in spec.get("feats", []):
        assert key in comp.feats, key
    for key in spec.get("options", []):
        assert key in comp.optionalfeatures, key
    ch.feats = [{"key": k, "note": ""} for k in spec.get("feats", [])]
    ch.options = [{"key": k, "note": ""} for k in spec.get("options", [])]
    ch.counters = [{"name": n, "max": mx, "used": 0, "reset": rs} for n, mx, rs in spec.get("counters", [])]
    prof = rules.proficiency_bonus(spec["level"])
    attacks = []
    for w in spec["weapons"]:
        item = comp.find("item", w)
        assert item and item.get("weapon"), w
        filled = fmt.weapon_attack(item, mods, prof)
        attacks.append({"name": w, **filled})
    ch.attacks = attacks
    ch.inventory = [{"name": n, "qty": str(q), "notes": ""} for n, q in spec["inventory"]]
    ch.currency = {"cp": 0, "sp": 0, "ep": 0, "gp": spec["gp"], "pp": 0}
    ch.appearance, ch.personality = spec["appearance"], spec["personality"]
    ch.backstory, ch.allies, ch.notes_dm = spec["backstory"], spec["allies"], spec["notes_dm"]
    return ch


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--replace", action="store_true")
    args = ap.parse_args()
    settings = load_settings()
    comp = Compendium(settings.data_dir, settings.sources)
    Session = make_session_factory(make_engine(settings.db_url))
    with Session() as session:
        for spec in PARTY:
            existing = session.scalars(select(Character).where(Character.name == spec["name"])).first()
            if existing and not args.replace:
                print(f"  keep    {spec['name']} (/c/{existing.id})")
                continue
            fresh = build(spec, comp)
            if existing:
                for col in Character.__table__.columns.keys():
                    if col not in ("id", "created_at", "password_hash"):
                        setattr(existing, col, getattr(fresh, col))
                ch = existing
            else:
                session.add(fresh)
                ch = fresh
            session.commit()
            view = build_sheet(ch, comp)
            sc = view["spellcasting"]
            print(f"  {'updated' if existing else 'created'} {ch.name} (/c/{ch.id}): {view['race']['name']} "
                  f"{view['cls']['name']} {ch.level}, HP {ch.hp_max}, AC {ch.ac}, PP {view['passive_perception']}"
                  + (f", DC {sc['dc']}, prepared {view['prepared_count']}/{sc['prepared_max']}" if sc and sc.get("prepared_max") else "")
                  + (f", pact {sc['pact']['count']}x{sc['pact']['label']}" if sc and sc.get("pact") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
