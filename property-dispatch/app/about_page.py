"""About page (/about): the founders and how the business runs. Server-rendered, same header and footer.

The founders' bios are their own words. The three "how we work" points only say what the app really does
(price from lawn size and yard type, the real route-density discount, the causes from settings).
"""

import html

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from .config import Settings
from .local_pages import cause_names, joined, layout
from .pricing import density_pct

esc = html.escape

FOUNDERS = (
    ("Raymundo Alvarez", "Co-Founder · Director of Operations", "USMC Veteran",
     "Brings over a half-decade of strict operational command and asset protection from the U.S. Marine Corps, "
     "managing security protocols across global diplomatic infrastructure and U.S. Embassies. Finishes an MBA with a "
     "4.0 GPA and carries foundational certification in NVIDIA AI Infrastructure & Operations to optimize data "
     "matrices on the ground."),
    ("Ciro Marabillo-Arreguin", "Co-Founder · Fleet Supply Chain Manager", "Logistics Lead",
     "An accomplished enterprise logistics supervisor with a background leading regional multi-stop distribution "
     "systems and warehouse KPI pipelines at RXO Logistics. Specializes in Lean Six Sigma principles, strict risk "
     "mitigation planning, and tight scheduling constraints to minimize operational downtime."),
)


def about_html(settings: Settings, version: str) -> str:
    people = "".join(f"""
          <article class="about-card">
            <header><div><h3>{esc(name)}</h3><p class="about-role">{esc(role)}</p></div><span class="about-tag">{esc(tag)}</span></header>
            <p>{esc(bio)}</p>
          </article>""" for name, role, tag, bio in FOUNDERS)
    small, big = int(density_pct(2) * 100), int(density_pct(5) * 100)
    pillars = (
        ("01 / Absolute Certainty",
         "We don't guess pricing or schedules via drive-bys. Our system prices your visit from your lot size and yard "
         "type, and shows the full checkout total with tax before you book. Pick yard only or full property and that "
         "total is locked."),
        ("02 / Route Architecture",
         "Routes are planned every evening, stop by stop, around tight neighborhood clusters to keep travel overhead "
         f"low. We pass that efficiency back: with 2 or more of our customers booked within half a mile, your mow "
         f"costs {small}% less ({big}% with 5 or more)."),
        ("03 / Noble Purpose Impact",
         "Our mission extends past residential boundaries. Part of every checkout goes to the local cause each client "
         f"picks: {joined(cause_names(settings))}."),
    )
    cols = "".join(f'<div class="about-pillar"><h4>{esc(t)}</h4><p>{esc(d)}</p></div>' for t, d in pillars)
    body = f"""
    <section class="about-hero" aria-labelledby="about-title">
      <div class="site-wrap about-wrap">
        <div class="about-intro">
          <p class="about-chips"><span>🛡️ Marine-Led Operations</span><span class="dot" aria-hidden="true"></span><span>⚡ AI-Backed Logistics</span></p>
          <h1 id="about-title">Lawn Care, Run Like an <span>Operation.</span></h1>
          <p class="about-lede">Most home services suffer from fragmented logistics, unreturned messages, and volatile pricing.
            We engineered {esc(settings.business_name)} to treat residential asset management with the same precision, security,
            and technology accountability expected in corporate supply chains and high-stakes operations.</p>
        </div>
        <div class="about-grid">{people}
        </div>
        <div class="about-pillars">{cols}</div>
        <p><a class="btn btn-primary btn-lg" href="/book">Book your first visit</a></p>
      </div>
    </section>"""
    return layout(settings, version, title=f"About | {settings.business_name}",
                  description="Marine-led, veteran-owned lawn care around Spring, TX, run with logistics discipline: "
                              "upfront prices, planned routes, and a local cause on every order.",
                  body=body, canonical=None)


def register_about_page(app: FastAPI, settings: Settings, version: str = "") -> None:
    @app.get("/about", include_in_schema=False)
    def about():
        return HTMLResponse(about_html(settings, version), headers={"Cache-Control": "no-cache"})
