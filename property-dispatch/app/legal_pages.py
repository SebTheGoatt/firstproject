"""Privacy policy, terms of service (with the damage policy) and refund policy.

    GET /privacy   what we collect, who sees it, how to delete it
    GET /terms     the service agreement, including the damage policy (/terms#damage)
    GET /refunds   cancellations, weather, re-dos and refunds

Plain-English drafts written from what this app actually does (see each section). Have a Texas
attorney review them; then change the EFFECTIVE date below whenever the wording changes.
Contact details come from settings (LEGAL_NAME, BUSINESS_EMAIL, BUSINESS_PHONE).
"""

import html

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from .config import Settings
from .local_pages import contact_line, crumbs, layout

esc = html.escape
EFFECTIVE = "October 19, 2026"
SMS_CONSENT = ("I agree to get text messages from {legal} about this booking: confirmation, crew on the way, "
               "job done, payment link, and one note afterward asking how we did. Msg & data rates may apply; "
               "frequency varies. Reply STOP to opt out, HELP for help.")


def legal_footer_html(settings: Settings) -> str:
    """The footer line every customer page carries: who we are, how to reach us, the policies."""
    return (f'<p class="legal-line">{esc(settings.legal_name)}{contact_line(settings)} · '
            '<a href="/privacy">Privacy</a> · <a href="/terms">Terms</a> · <a href="/refunds">Refunds</a></p>')


def contact_words(settings: Settings) -> str:
    """How to reach us, as HTML: email, and the phone once it's set."""
    parts = []
    if settings.business_email:
        parts.append(f'email <a href="mailto:{esc(settings.business_email)}">{esc(settings.business_email)}</a>')
    if settings.business_phone:
        digits = "".join(c for c in settings.business_phone if c.isdigit() or c == "+")
        parts.append(f'call or text <a href="tel:{esc(digits)}">{esc(settings.business_phone)}</a>')
    return " or ".join(parts) or "contact us through your visit page"


def page(settings: Settings, version: str, title: str, description: str, sections: str) -> str:
    body = f"""
    <section class="section legal" aria-labelledby="legal-title">
      <div class="site-wrap legal-wrap">
        {crumbs([("Home", "/"), (title, None)])}
        <h1 class="page-title" id="legal-title">{esc(title)}</h1>
        <p class="hint">Effective {EFFECTIVE} · {esc(settings.legal_name)}, doing business as {esc(settings.business_name)}</p>
{sections}
        <h2>Contact</h2>
        <p>Questions about this page: {contact_words(settings)}.</p>
      </div>
    </section>"""
    return layout(settings, version, title=f"{title} | {settings.business_name}", description=description, body=body)


def privacy_html(settings: Settings, version: str) -> str:
    legal, contact = esc(settings.legal_name), contact_words(settings)
    return page(settings, version, "Privacy Policy",
                "What we collect when you book a lawn visit, who sees it, and how to delete it.", f"""
        <p>{legal} ("we") mows lawns and runs this website and booking app. This page explains what we collect,
          why, and your choices. We do not sell your information, and we do not use advertising trackers.</p>

        <h2>What we collect</h2>
        <ul>
          <li><strong>Booking details:</strong> your name, mobile number, service address, the service date, what you
            chose to have mowed, your rate, add-ons, the cause you picked, and your language.</li>
          <li><strong>Payment status:</strong> whether you paid, how (cash or card) and the amounts. Card payments are
            handled by Stripe; we never see or store your full card number.</li>
          <li><strong>Visit records:</strong> before and after photos of your lawn, the time the crew arrived and
            finished, and short crew notes (for example a gate code).</li>
          <li><strong>Notifications:</strong> if you turn on app notifications, your browser's notification address.</li>
          <li><strong>Site visits:</strong> anonymous counts of which pages are viewed, with a random id that lasts
            for one browser tab. No names, phone numbers or anything typed into forms.</li>
        </ul>
        <p>We do not collect your location. The crew's phone shares its GPS with our app only to give the crew
          directions.</p>

        <h2>How we use it</h2>
        <p>To schedule and plan routes, do the work you booked, text you about it, take payment, show you your
          visit page and receipt, keep tax and business records, and ask once after a visit how we did.</p>

        <h2>Text messages</h2>
        <p>When you book, you agree to texts about that booking: confirmation, crew on the way, job done, your
          payment link, and one follow-up asking how we did. Message and data rates may apply. Reply
          <strong>STOP</strong> to any text to opt out, or <strong>HELP</strong> for help. We never send marketing
          texts and never share your number for anyone else's marketing.</p>

        <h2>Who we share it with</h2>
        <p>Only the services that run this app, and only what each one needs:</p>
        <ul>
          <li>Stripe (card payments), Twilio (text messages), Supabase (our database) and Render (web hosting).</li>
          <li>Map services that turn your address into a map point and plan driving routes: Google (address
            suggestions while you type on the booking form), OpenStreetMap / Nominatim, OSRM and OpenFreeMap.</li>
          <li>Your browser's notification service, if you turn on notifications.</li>
          <li>Authorities, only when the law requires it.</li>
        </ul>

        <h2>Cookies and browser storage</h2>
        <p>We do not use advertising or tracking cookies. Our pages store a few small things in your own browser:
          your language, your visit access code (so the visit page opens straight away), and, for the crew, their
          sign-in. Payment pages run by Stripe use Stripe's own cookies for security and fraud prevention.</p>

        <h2>How long we keep it</h2>
        <p>We keep booking and payment records for 4 years for Texas sales tax records. Photos and notes are kept
          with the visit until you ask us to delete them.</p>

        <h2 id="delete">Delete your information</h2>
        <p>Open your visit page with your access code and tap <strong>Delete my information</strong> at the bottom,
          or {contact}. We remove your name, phone number, address, photos and notes. We keep only what the law
          requires (the date, service and amounts paid, with no name attached). If you have an upcoming visit,
          cancel it first.</p>

        <h2>Children</h2>
        <p>Our service is for adults who own or rent the property. We do not knowingly collect information from
          children under 13.</p>

        <h2>Security</h2>
        <p>The site uses encrypted connections (HTTPS), customer pages need a private access code, and only our
          crew can sign in to the crew app.</p>

        <h2>Changes</h2>
        <p>If we change this policy, we update the date at the top of this page.</p>""")


def terms_html(settings: Settings, version: str) -> str:
    legal, contact = esc(settings.legal_name), contact_words(settings)
    insured = (f"We carry {esc(settings.liability_coverage)} in commercial general liability coverage. "
               if settings.liability_coverage.strip() else "")
    return page(settings, version, "Terms of Service",
                "The agreement for lawn visits booked online: scope, prices, payment, weather and our damage policy.", f"""
        <p>These terms are the agreement between you and {legal} when you book a visit on this site.
          By booking, you agree to them, to our <a href="/refunds">refund policy</a> and to our
          <a href="/privacy">privacy policy</a>.</p>

        <h2>The service</h2>
        <ul>
          <li>Each booking is <strong>one visit</strong>, billed per visit. There is no contract or subscription.</li>
          <li><strong>What we mow:</strong> if you chose <em>Yard only</em>, we mow the main or fenced yard; if you chose
            <em>Full property</em>, we mow the whole lot except the house. The price shown for that choice is locked:
            we don't re-measure on site. Older bookings without that choice are confirmed on site.</li>
          <li>Add-ons (for example bin or gutter cleaning) are done on the same visit.</li>
          <li>You must own the property or have the owner's permission for us to work there.</li>
        </ul>

        <h2>Your part</h2>
        <ul>
          <li>Give us access: unlock gates, or leave the gate code in your booking or with us.</li>
          <li>Keep pets indoors while we work. If a pet is loose in the area to be mowed, the crew may skip that area
            for everyone's safety.</li>
          <li>Pick up toys, hoses, furniture and pet waste from the lawn before the visit.</li>
          <li>Tell us before the visit about anything hidden or fragile in the grass (see the damage policy below).</li>
        </ul>

        <h2>Arrival times</h2>
        <p>Routes are planned the evening before. Arrival times are estimates and can shift with traffic, weather
          and the jobs before yours. We text you when the crew is on the way.</p>

        <h2>Prices and payment</h2>
        <ul>
          <li>You see the full price, including Texas sales tax, before you book. There are no hidden fees.</li>
          <li>Pay the crew in cash at the visit, or by card through the private Stripe link we send.</li>
          <li>Part of each visit's price goes to the cause you picked, as shown at booking. Anything extra you choose
            to give goes to that cause too. Tips are never expected.</li>
        </ul>

        <h2>Weather and safety</h2>
        <p>We don't mow in lightning, heavy rain or when the ground is soft enough to rut. We'll text you and
          reschedule to the next open day. The crew may also skip a small area that is unsafe (a wasp nest, a steep
          wet slope, standing water) and will tell you; see the <a href="/refunds">refund policy</a> for what happens then.</p>

        <h2 id="damage">Damage policy</h2>
        <p>We work carefully and we stand behind our work. {insured}Here is exactly how damage is handled.</p>
        <h3>What we cover</h3>
        <ul>
          <li>Damage we cause through our own mistake or carelessness: for example a broken window from a thrown
            rock, a dented car or fence, a damaged marked sprinkler head, or a gate we left open.</li>
          <li>We will repair it, have it repaired by a qualified professional, or pay the reasonable cost to repair it
            (or to replace it, if repair isn't possible), at our choice, after we have inspected it.</li>
        </ul>
        <h3>How to report it</h3>
        <ol>
          <li>Tell us within <strong>72 hours</strong> of the visit: {contact}.</li>
          <li>Send photos of the damage, and don't repair it yourself before we've seen it, except to prevent more
            damage or for safety.</li>
          <li>We will reply within 1 business day and inspect within 3 business days.</li>
        </ol>
        <p>When the crew takes before and after photos, they're on your visit page, and they help settle what was
          already there.</p>
        <h3>What we don't cover</h3>
        <ul>
          <li><strong>Hidden or unmarked items</strong> in the area to be mowed that you didn't tell us about: sprinkler
            heads set too high or not marked, invisible dog fence wire, low-voltage lighting, cables, irrigation lines
            or stakes. Mark them with a flag or tell us before the visit and we'll work around them.</li>
          <li><strong>Items left on the lawn</strong>, such as toys, hoses, decorations or furniture. We move what we
            can safely, but we aren't responsible for items hidden in the grass.</li>
          <li><strong>Damage that was already there</strong> before our visit, or normal wear such as worn turf along
            regular mowing paths.</li>
          <li><strong>Lawn health</strong> not caused by our work: drought, disease, insects, fertilizer, watering or
            weather.</li>
          <li><strong>Areas outside what you booked</strong>, or property lines you didn't show us.</li>
          <li>Damage caused by pets, other people, or conditions you asked us to work in after we advised against it.</li>
        </ul>
        <h3>Limits</h3>
        <p>For any one visit, our responsibility is limited to fixing or paying for direct physical damage as described
          above. We are not responsible for indirect or consequential losses (such as lost time or income). Nothing in
          these terms limits any right you have that Texas law doesn't allow us to limit.</p>

        <h2>Changes and cancellations</h2>
        <p>See the <a href="/refunds">refund policy</a>. We may cancel a visit we can't safely or legally do, and you
          get a full refund.</p>

        <h2>Disputes</h2>
        <p>If something goes wrong, contact us first: {contact}. We will try in good faith to fix it within 14 days.
          These terms are governed by Texas law, and any dispute that we can't settle goes to the courts of the county
          where the work was done, including small claims (justice) court.</p>

        <h2>Changes to these terms</h2>
        <p>We may update these terms; the version shown when you booked applies to that booking.</p>""")


def refunds_html(settings: Settings, version: str) -> str:
    contact = contact_words(settings)
    return page(settings, version, "Refund & Cancellation Policy",
                "Cancel before the crew arrives for a full refund. Weather days are rescheduled or refunded in full.", f"""
        <p>Simple version: <strong>if we don't do the work you paid for, you get your money back in full.</strong></p>

        <h2>Cancel or change a visit</h2>
        <ul>
          <li>Cancel any time before the crew arrives: <strong>full refund</strong> if you paid by card, nothing owed
            if you planned to pay cash.</li>
          <li>To cancel or move a visit, {contact}, with your access code if you have it handy.</li>
          <li>Moving to another day is free, subject to open spots on that day's route.</li>
        </ul>

        <h2>Weather</h2>
        <p>If rain, lightning or wet ground stops the visit, we move it to the next open day and text you. If that day
          doesn't work for you, you get a <strong>full refund</strong>.</p>

        <h2>Not happy with the work</h2>
        <ul>
          <li>Tell us within 48 hours of the visit, with a photo if you can.</li>
          <li>We come back and fix it at no charge, usually within 2 business days.</li>
          <li>If it still isn't right, you get a <strong>full refund</strong> for that visit.</li>
        </ul>

        <h2>Areas we couldn't mow</h2>
        <p>If the crew had to skip part of the area you booked (for example a loose pet, a locked gate or a safety
          hazard), we tell you, and you choose: we come back to finish it, or we refund that part of the visit.</p>

        <h2>What is refunded</h2>
        <p>A full refund is everything you paid for that visit: the price, the sales tax, and any extra donation you
          added. Card refunds go back to the same card through Stripe and usually show up in 5 to 10 business days.
          Cash is refunded in cash or by check.</p>

        <h2>Damage</h2>
        <p>Damage is handled under the <a href="/terms#damage">damage policy</a> in our terms of service.</p>""")


def register_legal_pages(app: FastAPI, settings: Settings, version: str = "") -> None:
    def html_page(text: str) -> HTMLResponse:
        return HTMLResponse(text, headers={"Cache-Control": "no-cache"})

    @app.get("/privacy", include_in_schema=False)
    def privacy():
        return html_page(privacy_html(settings, version))

    @app.get("/terms", include_in_schema=False)
    def terms():
        return html_page(terms_html(settings, version))

    @app.get("/refunds", include_in_schema=False)
    def refunds():
        return html_page(refunds_html(settings, version))
