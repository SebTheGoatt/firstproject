"""Spanish speakers: the booking remembers the language and every text comes in Spanish."""

from pathlib import Path
from unittest.mock import patch

from app.nightly import run_nightly

from .test_api_flow import CREW, NOW, TOMORROW


def book(client, phone, lang=None, name="Ana López"):
    body = {"name": name, "phone": phone, "address": "100 A Example Rd", "lawn_sqft": 5000, "package": "supporter",
            "add_ons": ["gutters"], "scheduled_date": TOMORROW.isoformat(), "payment_method": "cash"}
    if lang:
        body["lang"] = lang
    with patch("app.main.local_now", return_value=NOW):
        r = client.post("/api/jobs", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_spanish_booking_confirmation_text(client, repo, sms):
    job = book(client, "2815550101", lang="es")
    assert repo.jobs[job["id"]]["lang"] == "es"
    to, text = sms.sent[-1]
    assert text.startswith("Hola Ana, tu cita con")
    assert "corte de césped + limpieza de canaletas" in text and "jueves 15 de oct" in text
    assert job["access_code"] in text and "Responde STOP" in text


def test_english_stays_the_default(client, repo, sms):
    job = book(client, "2815550102", name="Pat Doe")
    assert repo.jobs[job["id"]]["lang"] == "en"
    assert sms.sent[-1][1].startswith("Hi Pat, you're booked with") and "Thursday, Oct 15" in sms.sent[-1][1]


def test_on_the_way_and_pay_link_texts_follow_the_customer(client, repo, settings, sms):
    book(client, "2815550101", lang="es")                       # stop 1 or 2
    book(client, "2815550102", name="Pat Doe")
    run_nightly(repo, settings, TOMORROW)
    stops = client.get(f"/api/routes/{TOMORROW}", headers=CREW).json()["stops"]
    client.post(f"/api/stops/{stops[0]['stop_id']}/complete", headers=CREW)
    text = sms.sent[-1][1]
    if stops[1]["customer_name"].startswith("Ana"):
        assert text.startswith("Hola Ana, te saluda") and "vamos en camino" in text
    else:
        assert text.startswith("Hi Pat, this is")


def test_unknown_language_is_refused(client):
    with patch("app.main.local_now", return_value=NOW):
        r = client.post("/api/jobs", json={"name": "X Y", "phone": "2815550103", "address": "100 A Example Rd",
                                           "lawn_sqft": 5000, "package": "standard", "lang": "fr",
                                           "scheduled_date": TOMORROW.isoformat()})
    assert r.status_code == 422


def test_customer_pages_load_the_translations(client):
    for path in ("/", "/book", "/visit", "/pay/some-token-value-123456"):
        assert "/static/i18n.js?v=" in client.get(path).text, path
    assert "/static/i18n.js" not in client.get("/crew").text          # the crew app stays in English
    js = (Path(__file__).parent.parent / "static" / "i18n.js").read_text()
    assert "Reservar un servicio" in js and "Calcular mi precio" in js
