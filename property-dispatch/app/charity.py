"""Where donations go.

Every donation is split between three causes. The split is worked out to the
cent when the donation is paid (any leftover cent goes to the cause with the
largest remainder, so the shares always add up to the donation exactly) and
saved on the job, so the owner's ledger never changes after the fact, even if
the percentages are changed later.

Donations are voluntary and never taxed. Names come from settings so the owner
can name a specific VFW post, hospital NICU or youth program without a code change.
"""

from decimal import ROUND_DOWN, Decimal

from .config import Settings

CENT = Decimal("0.01")

# key → share of each donation. Must add up to 1.
CHARITY_SPLIT: dict[str, Decimal] = {
    "vfw": Decimal("0.33"),          # Veterans of Foreign Wars
    "nicu": Decimal("0.33"),         # Neonatal intensive care
    "at_risk_youth": Decimal("0.34"),  # At-risk youth programs
}
if sum(CHARITY_SPLIT.values()) != 1:
    raise ValueError("charity shares must add up to 100%")


# The customer picks ONE cause at booking; their order's giving (and any extra they give the crew)
# goes 100% to it. Orders without a pick (older bookings, API callers) keep the 33/33/34 split above.
CHOICES = ("toys_for_tots", "vfw", "nicu")
CAUSE_BLURBS = {
    "toys_for_tots": "Helps buy holiday toys for kids in our service area.",
    "vfw": "Helps local veterans and their families through a VFW post in our area.",
    "nicu": "Helps families whose newborns are in neonatal intensive care.",
}


def charity_names(settings: Settings) -> dict[str, str]:
    return {"vfw": settings.charity_vfw_name, "nicu": settings.charity_nicu_name,
            "at_risk_youth": settings.charity_youth_name, "toys_for_tots": settings.charity_toys_name}


def causes(settings: Settings) -> list[dict]:
    """The causes a customer can pick at booking, with their names from settings."""
    names = charity_names(settings)
    return [{"key": k, "name": names[k], "blurb": CAUSE_BLURBS[k]} for k in CHOICES]


def all_causes(settings: Settings) -> list[dict]:
    """Every cause money can be owed to (the split causes plus the pickable ones), for the owner's ledger."""
    names = charity_names(settings)
    return [{"key": k, "name": names[k], "percent": int(CHARITY_SPLIT.get(k, 0) * 100)}
            for k in dict.fromkeys([*CHARITY_SPLIT, *CHOICES])]


def chosen_cause(split: dict | None) -> str | None:
    """The customer's pick, read back from a saved split that went 100% to one cause."""
    keys = [k for k, v in (split or {}).items() if v]
    return keys[0] if len(keys) == 1 and keys[0] in CHOICES else None


def route_donation(amount, choice: str | None) -> dict[str, float]:
    """All of it to the customer's pick, or the standard split when there is none."""
    total = Decimal(str(amount or 0)).quantize(CENT)
    if total <= 0:
        return {}
    return {choice: float(total)} if choice in CHOICES else split_donation(total)


def split_donation(amount: float | Decimal | None) -> dict[str, float]:
    """{'vfw': 1.65, 'nicu': 1.65, 'at_risk_youth': 1.70} for $5. Always sums to the donation."""
    total = Decimal(str(amount or 0)).quantize(CENT)
    if total <= 0:
        return {}
    raw = {k: total * share for k, share in CHARITY_SPLIT.items()}
    shares = {k: v.quantize(CENT, rounding=ROUND_DOWN) for k, v in raw.items()}
    leftover = int((total - sum(shares.values())) / CENT)
    for k in sorted(raw, key=lambda k: raw[k] - shares[k], reverse=True)[:leftover]:
        shares[k] += CENT
    return {k: float(v) for k, v in shares.items()}


def describe(settings: Settings) -> list[dict]:
    """The causes and their percentages, for pages and receipts."""
    names = charity_names(settings)
    return [{"key": k, "name": names[k], "percent": int(share * 100)} for k, share in CHARITY_SPLIT.items()]


def ledger(settings: Settings, split: dict | None) -> list[dict]:
    """A saved split with names attached: [{'key', 'name', 'percent', 'amount'}]."""
    split = split or {}
    choice = chosen_cause(split)
    if choice:
        return [{"key": choice, "name": charity_names(settings)[choice], "percent": 100, "amount": round(float(split[choice]), 2)}]
    return [{**c, "amount": round(float(split.get(c["key"], 0)), 2)} for c in describe(settings)]
