"""About page (/about): the founders, how the business runs and why it's called Post One. Server-rendered,
same header and footer.

The founder's bio is his own words. The three "how we work" points only say what the app really does
(price from lawn size and yard type, the real route-density discount, the causes from settings). The
"Why Post One" band tells the name's story and backs each line of the brand voice with the same facts.
"""

import html

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from .config import Settings, site_url
from .local_pages import cause_names, hour_words, joined, layout, with_share_tags
from .zones import schedule_text

esc = html.escape

FOUNDERS = (
    ("Raymundo S. Alvarez", "Co-Founder · Director of Operations", "USMC VET / MBA",
     "U.S. Marine Corps veteran with an MBA. Runs dispatch, pricing and the crew, and answers for every visit."),
)

# Waiting on Ciro's go-ahead. To show him on the page, move this entry into FOUNDERS above.
PENDING_FOUNDERS = (
    ("Ciro Marabillo-Arreguin", "Co-Founder · Supply Chain Manager", "LOGISTICS CORE",
     "Fleet dispatch and multi-stop scheduling background at RXO Logistics. Keeps routes tight and days on time."),
)


# Logo A's full mark (shield, "1" and mow lines) for the "Why Post One" band. Decorative: the heading says it all.
SHIELD = ('<svg class="sp-story-mark" viewBox="0 0 200 220" aria-hidden="true" focusable="false">'
          '<path d="M100 10 L182 40 V110 C182 160 148 192 100 210 C52 192 18 160 18 110 V40 Z" fill="#0F2B22" '
          'stroke="#C9A227" stroke-width="6" stroke-linejoin="round"/>'
          '<path d="M46 160 H154" stroke="#1F5A3C" stroke-width="8" stroke-linecap="round"/>'
          '<path d="M66 180 H134" stroke="#1F5A3C" stroke-width="8" stroke-linecap="round"/>'
          '<path d="M92 166 V82 C84 88 74 92 62 94 V78 C80 74 94 62 101 46 H113 V166 Z" fill="#9BD15A"/>'
          '<rect x="80" y="160" width="46" height="10" rx="2" fill="#9BD15A"/></svg>')

# The three lines of the brand's voice, each with what the app really does to back it up.
STANDARDS = (
    ("On post. On time.", "Each day's route is planned the evening before, and you get a text when the crew is on the way."),
    ("Every yard gets Post One attention.", "Your price comes from your lawn size and yard type, and you see it, tax included, "
                                            "before you book."),
    ("Clean lawns. Stronger communities.", "Part of every visit's price goes to the local cause you pick when you book."),
)


def about_html(settings: Settings, version: str) -> str:
    people = "".join(f"""
          <article class="sp-founder">
            <header>
              <div><h3>{esc(name)}</h3><p class="sp-role">{esc(role)}</p></div>
              <span class="sp-tag">{esc(tag)}</span>
            </header>
            <p>{esc(bio)}</p>
          </article>""" for name, role, tag, bio in FOUNDERS)
    # Each cause in its own span, so the Spanish page can translate the names one by one.
    causes = [f"<span>{esc(c)}</span>" for c in cause_names(settings)]
    pillars = (   # (number, kicker, title, text as HTML)
        ("01", "No subscription", "Pay per visit",
         "Book one visit at a time. Pick your lawn size, yard type and add-ons, and the total, tax included, is shown "
         "before you book. Pay by card at checkout or cash to the crew."),
        ("02", "One area a day", "Lawns, not the road",
         f"We mow {esc(schedule_text())}. Each route locks at {hour_words(settings.freeze_hour)} the day before, "
         "so the crew drives less and your day is firm."),
        ("03", "Local causes", "Your pick",
         f"Part of every visit goes to the local cause you pick when you book: {joined(causes)}."),
    )
    cols = "".join(f"""
          <li><span class="sp-num">{n}</span><p class="sp-kicker">{esc(k)}</p><h3>{esc(t)}</h3><p>{d}</p></li>"""
                   for n, k, t, d in pillars)
    standards = "".join(f"<li><strong>{esc(t)}</strong><span>{esc(d)}</span></li>" for t, d in STANDARDS)
    badges = (f' coverage="{esc(settings.liability_coverage.strip())}"' if settings.liability_coverage.strip() else "") \
        + (" background-checked" if settings.crew_background_checked else "")
    body = f"""
    <section class="sp-hero" aria-labelledby="about-title">
      <div class="site-wrap sp-hero-grid">
        <div class="sp-hero-copy">
          <p class="eyebrow">Veteran-owned · Spring, TX</p>
          <h1 id="about-title">Local crew. Upfront prices. <span>On time.</span></h1>
          <p class="lede">You see your price before you book, pay per visit with no subscription, and get a text when
            the crew is on the way. We mow one area a day, so the crew's time goes into lawns, not the road.</p>
          <div class="hero-actions">
            <a class="btn btn-lg sp-btn-fresh" href="/book">Book your first visit</a>
            <a class="btn btn-lg sp-btn-line" href="#why">Our story</a>
          </div>
        </div>
        <trust-badges{badges}></trust-badges>
      </div>
    </section>

    <section class="section" aria-labelledby="leaders-title">
      <div class="site-wrap sp-split">
        <div class="sp-split-copy">
          <h2 id="leaders-title">Leadership</h2>
          <p class="section-lede">A local business owned and led by a veteran.</p>
        </div>
        <div class="sp-founders">{people}
        </div>
      </div>
    </section>

    <section class="section" aria-labelledby="work-title">
      <div class="site-wrap">
        <h2 id="work-title">How we work</h2>
        <ol class="sp-pillars">{cols}
        </ol>
      </div>
    </section>

    <section class="section" id="why" aria-labelledby="why-title">
      <div class="site-wrap">
        <div class="sp-story">
          {SHIELD}
          <div class="sp-story-copy">
            <p class="eyebrow">Why “Post One”</p>
            <h2 id="why-title">Your yard is our first priority.</h2>
            <p>Post One means you're never an afterthought. We mow on planned neighborhood routes, so we show up on the day we say, text you when we're on the way, and send a receipt when we're done.</p>
            <ul class="sp-standards">{standards}</ul>
            <div class="hero-actions">
              <a class="btn btn-lg sp-btn-fresh" href="/book">Book your first visit</a>
              <a class="btn btn-lg sp-btn-line" href="/local">Areas we serve</a>
            </div>
          </div>
        </div>
      </div>
    </section>"""
    return layout(settings, version, title=f"About | {settings.business_name}",
                  description="Veteran-owned lawn care around Spring, TX, run with operational discipline: "
                              "self-serve booking, planned routes, and a local cause on every order.",
                  body=body, canonical=None, page="about",
                  head_extra=f'\n  <script src="/static/trust-badges.js?v={esc(version)}" defer></script>')


def register_about_page(app: FastAPI, settings: Settings, version: str = "") -> None:
    @app.get("/about", include_in_schema=False)
    def about(request: Request):
        return HTMLResponse(with_share_tags(about_html(settings, version), site_url(settings, request), "/about"),
                            headers={"Cache-Control": "no-cache"})
