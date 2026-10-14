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

from .charity import split_donation
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
            "payment_intent_data[description]": f"{self.settings.business_name}: {service_label} on {service_date}",
        }
        lines: list[tuple[str, float]] = []
        if subtotal is not None and tax is not None and abs(subtotal + tax - amount_due) < 0.005:
            lines.append((f"{service_label} ({service_date})", subtotal))
            if tax > 0:
                lines.append((f"Texas sales tax ({tax_rate * 100:.2f}%)" if tax_rate else "Texas sales tax", tax))
        else:
            lines.append((f"{service_label} ({service_date})", amount_due))
        if donation > 0:
            split = split_donation(donation)
            if charities:
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
