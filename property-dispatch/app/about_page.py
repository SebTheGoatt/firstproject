"""About page (/about): the founders, how the business runs and why it's called Post One. Server-rendered,
same header and footer.

The founder's bio is his own words. The three "how we work" points only say what the app really does
(price from lawn size and yard type, the real route-density discount, the causes from settings). The
"Why Post One" band tells the name's story and backs each line of the brand voice with the same facts.
"""

import html

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from .config import Settings
from .local_pages import cause_names, joined, layout

esc = html.escape

FOUNDERS = (
    ("Raymundo S. Alvarez", "Co-Founder · Director of Operations", "USMC VET / MBA",
     "Forged through nearly a decade of strict tactical infantry leadership and high-value asset protection within "
     "the U.S. Marine Corps Security Guard Program, securing vital federal architecture and diplomatic infrastructure "
     "across global U.S. Embassies. Combines an immaculate 4.0 graduate business background with specialized NVIDIA "
     "AI Infrastructure tracking to ensure flawless routing execution on the ground."),
)

# Waiting on Ciro's go-ahead. To show him on the page, move this entry into FOUNDERS above.
PENDING_FOUNDERS = (
    ("Ciro Marabillo-Arreguin", "Co-Founder · Supply Chain Manager", "LOGISTICS CORE",
     "An accomplished enterprise shipping, inventory control, and multi-stop operations supervisor with a proven "
     "record managing complex commercial fleet dispatch paths and strict KPI tracking logs at RXO Logistics. "
     "Specializes in Lean Six Sigma process improvements, tight resource scheduling, and asset risk mitigation to "
     "completely eliminate unbilled downtime across target deployment zones."),
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
        ("01", "Frictionless Autonomy", "The Power of Choice",
         "We systematically rejected the rigid, forced corporate subscription structures that fatigue modern consumers. "
         "Instead, we built a streamlined, self-serve transaction shell. You select your exact property coordinates, "
         "layer high-margin add-ons instantly with zero personal friction, and manage your asset timeline your way."),
        ("02", "Dynamic Geofences", "Route Density Optimization",
         f"By locking down our daily regional manifests at {settings.freeze_hour - 12 if settings.freeze_hour > 12 else settings.freeze_hour}:00 PM sharp, "
         "we treat every morning deployment like a controlled tactical insertion. We map spatial density patterns across "
         "target ZIP networks, cutting down the fuel and drive-time leakages that drive low-class starters into bankruptcy."),
        ("03", "Generational Moats", "The Purpose Pledge",
         "As dedicated Texas homeowners and land stewards, we approach your property boundary with genuine peer "
         "perspective and oversight. Every mission completed allows you to allocate part of your payment directly to "
         f"the local cause you pick: {joined(causes)}."),
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
          <p class="eyebrow">Veteran-Owned &amp; Managed · NVIDIA AI Infrastructure Trained</p>
          <h1 id="about-title">Built on Pedigree. Driven by <span>Discernment.</span></h1>
          <p class="lede">Anyone can deploy a lawn mower or purchase an automated robot. But a machine cannot exercise
            situational judgment, and unmanaged contractors lack operational accountability. We engineered
            {esc(settings.business_name.split(" Lawn")[0])} around a single core tenet: bringing elite operational legacy,
            institutional discipline, and data-driven logistics to home asset preservation.</p>
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
            <h2 id="why-title">The post that's never left unmanned.</h2>
            <p>At U.S. embassies around the world, Marine Security Guards stand Post One, the post that is never left unmanned.
              Our co-founder, Raymundo, served as a Marine Security Guard. Now he brings that standard home to Spring:
              show up on time, do it right, and treat every yard like it matters.</p>
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
    def about():
        return HTMLResponse(about_html(settings, version), headers={"Cache-Control": "no-cache"})
