"""Card payments through Stripe Checkout (hosted payment page).

We never see or store card numbers: the customer pays on Stripe's page, and
Stripe tells us it succeeded through a signed webhook. Talks to Stripe's REST
API directly with httpx, so there's no extra SDK to install.
"""

import hashlib
import hmac
import json
import time

import httpx

from .charity import route_donation
from .config import Settings

MAX_DONATION = 500.00
SIGNATURE_TOLERANCE_S = 300


class PaymentError(Exception):
    pass


def to_cents(amount: float) -> int:
    return int(round(amount * 100))


def clean_donation(value: float | None) -> float:
    """Donations are optional, non-negative, capped, and rounded to the cent."""
    if value is None:
        return 0.0
    v = round(float(value), 2)
    if v < 0 or v > MAX_DONATION:
        raise PaymentError(f"Donations can be between $0 and ${MAX_DONATION:,.0f}.")
    return v


class StripeClient:
    API = "https://api.stripe.com/v1"

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        self.client = client or httpx.Client(timeout=15)

    def create_checkout(
        self, *, job_id: str, service_label: str, service_date: str, amount_due: float, donation: float,
        success_url: str, cancel_url: str, subtotal: float | None = None, tax: float | None = None,
        tax_rate: float | None = None, charities: list[dict] | None = None,
        package_label: str | None = None, charity_rate: float | None = None, charity_amount: float | None = None,
        add_ons: list | None = None, charity_choice: str | None = None, audit: dict | None = None,
    ) -> dict:
        """One Stripe line for the service, one for Texas sales tax, and one per cause an optional
        donation goes to (so the receipt shows exactly where it went).
        Checkout offers whichever methods are on in the Stripe Dashboard (cards, Apple Pay, Google Pay…)."""
        data: dict[str, str] = {
            "mode": "payment",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "client_reference_id": job_id,
            "metadata[job_id]": job_id,
            "metadata[amount_due_cents]": str(to_cents(amount_due)),
            "metadata[donation_cents]": str(to_cents(donation)),
            "metadata[charity_choice]": charity_choice or "",
            # The same facts on the PaymentIntent, so payment_intent.succeeded and the Stripe Dashboard carry them too.
            "payment_intent_data[metadata][job_id]": job_id,
            "payment_intent_data[metadata][donation_cents]": str(to_cents(donation)),
            "payment_intent_data[metadata][charity_choice]": charity_choice or "",
            "payment_intent_data[description]": f"{self.settings.business_name}: {service_label} on {service_date}",
        }
        # Audit facts (no names, phones or addresses): size bracket, tier, giving lane, route stop.
        for key, value in (audit or {}).items():
            data[f"metadata[{key}]"] = data[f"payment_intent_data[metadata][{key}]"] = str(value)[:500]
        lines: list[tuple[str, float]] = []
        service_name = f"{service_label} ({service_date})"
        if package_label and charity_amount:
            # The package's giving is part of the price, so it's named on the line rather than charged again.
            service_name = (f"{service_label}, {package_label} ({service_date}): generates "
                            f"${charity_amount:,.2f} ({charity_rate * 100:g}%) for VFW, NICU & youth programs")
        notes = {a["key"]: a for a in (add_ons or []) if a.get("info")}   # yield engine: yard type + density discount
        if "yard_type" in notes:
            yard = notes["yard_type"]["label"].removeprefix("Yard type: ")
            cut = -float(notes.get("route_density", {}).get("amount") or 0)
            service_name = (f"{service_label}, {yard} ({service_date})"
                            + (f", after a ${cut:,.2f} route cluster discount" if cut > 0 else ""))
        if subtotal is not None and tax is not None and abs(subtotal + tax - amount_due) < 0.005:
            extras = [(f"Add-on: {a['label']}", float(a["price"])) for a in (add_ons or [])
                      if a.get("price") is not None and float(a["price"]) > 0]     # yard / full property: no line of its own
            lines.append((service_name, round(subtotal - sum(p for _, p in extras), 2)))
            lines.extend(extras)
            if tax > 0:
                lines.append((f"Texas sales tax ({tax_rate * 100:.2f}%)" if tax_rate else "Texas sales tax", tax))
        else:
            lines.append((service_name, amount_due))
        if donation > 0:
            split = route_donation(donation, charity_choice)
            if charity_choice:
                name = next((c["name"] for c in charities or [] if c["key"] == charity_choice), "our local cause")
                lines.append((f"Donation to {name} (not taxed)", donation))
            elif charities:
                for c in charities:
                    if split.get(c["key"], 0) > 0:
                        lines.append((f"Donation, {c['percent']}% to {c['name']} (not taxed)", split[c["key"]]))
            else:
                lines.append(("Donation (not taxed). Thank you!", donation))
        for i, (name, amount) in enumerate(lines):
            data.update({
                f"line_items[{i}][quantity]": "1",
                f"line_items[{i}][price_data][currency]": "usd",
                f"line_items[{i}][price_data][unit_amount]": str(to_cents(amount)),
                f"line_items[{i}][price_data][product_data][name]": name,
            })
        try:
            resp = self.client.post(f"{self.API}/checkout/sessions", data=data,
                                    auth=(self.settings.stripe_secret_key, ""))
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise PaymentError("Card payments are temporarily unavailable. Please try again shortly.") from exc
        body = resp.json()
        return {"id": body["id"], "url": body["url"]}


    def refund_checkout(self, session_id: str) -> str:
        """Full refund of a paid Checkout Session (cancelled visit). Returns the Stripe refund id."""
        auth = (self.settings.stripe_secret_key, "")
        try:
            session = self.client.get(f"{self.API}/checkout/sessions/{session_id}", auth=auth)
            session.raise_for_status()
            intent = session.json().get("payment_intent")
            if not intent:
                raise PaymentError("That payment has nothing to refund.")
            r = self.client.post(f"{self.API}/refunds", auth=auth,
                                 data={"payment_intent": intent, "metadata[reason]": "visit_cancelled"})
            r.raise_for_status()
            return r.json()["id"]
        except httpx.HTTPError as exc:
            raise PaymentError("The card refund didn't go through automatically.") from exc


def verify_webhook(payload: bytes, signature_header: str | None, secret: str, now: float | None = None) -> dict:
    """Check Stripe's `Stripe-Signature` header and return the parsed event."""
    if not signature_header or not secret:
        raise PaymentError("missing signature")
    parts = dict(p.split("=", 1) for p in signature_header.split(",") if "=" in p)
    timestamp = parts.get("t")
    candidates = [v for k, v in (p.split("=", 1) for p in signature_header.split(",") if "=" in p) if k == "v1"]
    if not timestamp or not candidates:
        raise PaymentError("malformed signature")
    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, c) for c in candidates):
        raise PaymentError("bad signature")
    if abs((now or time.time()) - int(timestamp)) > SIGNATURE_TOLERANCE_S:
        raise PaymentError("stale signature")
    return json.loads(payload)
