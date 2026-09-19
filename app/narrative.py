"""What the rest of the table can see: health as a phrase per 10%, conditions as what they look like.

Players never see each other's numbers - the DM does. Companions (familiars, steel
defenders, homunculi) get the same treatment when they're summoned.
"""
from __future__ import annotations

# index = tenth of max hit points remaining, rounded up (0 = down)
HEALTH_STEPS = [
    "is down and not moving",
    "is struggling to stay conscious",
    "is barely standing",
    "is gravely wounded",
    "is staggering",
    "is badly hurt",
    "is bleeding from several wounds",
    "is wounded",
    "is lightly wounded",
    "has a scratch or two",
    "looks unhurt",
]

# what a condition looks like from across the room
CONDITION_LOOKS = {
    "Blinded": "is groping blindly",
    "Charmed": "seems oddly taken with someone",
    "Deafened": "isn't reacting to sounds",
    "Exhaustion": "looks exhausted",
    "Frightened": "looks terrified",
    "Grappled": "is held fast",
    "Incapacitated": "can't act",
    "Invisible": "is nowhere to be seen",
    "Paralyzed": "is rigid and unmoving",
    "Petrified": "has turned to stone",
    "Poisoned": "looks sickly",
    "Prone": "is on the ground",
    "Restrained": "is bound in place",
    "Stunned": "looks dazed",
    "Unconscious": "is out cold",
}


def health_step(current: int, maximum: int) -> int:
    """0 (down) to 10 (unhurt): the tenth of max HP remaining, rounded up."""
    if maximum <= 0 or current <= 0:
        return 0
    return max(1, min(10, -(-current * 10 // maximum)))


def health_colour(step: int) -> str:
    """Green for whole, amber in the middle, red near the end - as an hsl() the page can use."""
    hue = int(step * 12)                    # 0 red .. 120 green
    return f"hsl({hue}, 62%, 52%)"


def describe(name: str, current: int, maximum: int, conditions: list[str] | None = None) -> dict:
    step = health_step(current, maximum)
    looks = [CONDITION_LOOKS[c] for c in (conditions or []) if c in CONDITION_LOOKS]
    if step == 0 and "Unconscious" in (conditions or []):
        looks = [x for x in looks if x != CONDITION_LOOKS["Unconscious"]]
    return {
        "name": name,
        "step": step,
        "pct": step * 10,
        "health": HEALTH_STEPS[step],
        "colour": health_colour(step),
        "looks": looks,
        "down": step == 0,
    }


def hints(*, hp_current: int, hp_temp: int = 0, concentration: str = "", slots=None, pact=None,
          hit_dice_used: int = 0, level: int = 1, death_success: int = 0, death_fail: int = 0,
          attacks=None) -> list[str]:
    """Things anyone at the table could notice, without a number in sight."""
    out = []
    if hp_current <= 0:
        if death_fail >= 2:
            out.append("is slipping away")
        elif death_success >= 2:
            out.append("seems to be stabilising")
    if hp_temp > 0:
        out.append("is warded by something")
    if concentration:
        out.append("is holding a spell together")
    total = sum(s["total"] for s in (slots or [])) + (pact["count"] if pact else 0)
    used = sum(s["used"] for s in (slots or [])) + (pact["used"] if pact else 0)
    if total:
        left = total - used
        if left == 0:
            out.append("has nothing left to cast")
        elif left * 4 <= total:
            out.append("looks magically spent")
    if level and hit_dice_used * 2 >= level and hit_dice_used > 0:
        out.append("could use a rest")
    weapons = []
    for a in attacks or []:
        name = str(a.get("name", "")).strip()
        name = name.split(" (")[0].strip()
        if name and name.lower() not in ("unarmed", "unarmed strike", "claws", "claw", "bite") and name not in weapons:
            weapons.append(name)
    if weapons:
        out.append("armed with " + ", ".join(w.lower() for w in weapons[:4]))
    return out
