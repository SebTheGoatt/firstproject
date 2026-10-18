"""About page (/about): the founders and how the business runs. Server-rendered, same header and footer.

The founders' bios are their own words. The three "how we work" points only say what the app really does
(price from lawn size and yard type, the real route-density discount, the causes from settings).
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
    ("Ciro Marabillo-Arreguin", "Co-Founder · Supply Chain Manager", "LOGISTICS CORE",
     "An accomplished enterprise shipping, inventory control, and multi-stop operations supervisor with a proven "
     "record managing complex commercial fleet dispatch paths and strict KPI tracking logs at RXO Logistics. "
     "Specializes in Lean Six Sigma process improvements, tight resource scheduling, and asset risk mitigation to "
     "completely eliminate unbilled downtime across target deployment zones."),
)


def about_html(settings: Settings, version: str) -> str:
    people = "".join(f"""
          <article class="about-card">
            <header><div><h3>{esc(name)}</h3><p class="about-role">{esc(role)}</p></div><span class="about-tag">{esc(tag)}</span></header>
            <p>{esc(bio)}</p>
          </article>""" for name, role, tag, bio in FOUNDERS)
    pillars = (
        ("01 / Frictionless Autonomy", "The Power of Choice",
         "We systematically rejected the rigid, forced corporate subscription structures that fatigue modern consumers. "
         "Instead, we built a streamlined, self-serve transaction shell. You select your exact property coordinates, "
         "layer high-margin add-ons instantly with zero personal friction, and manage your asset timeline your way."),
        ("02 / Dynamic Geofences", "Route Density Optimization",
         f"By locking down our daily regional manifests at {settings.freeze_hour - 12 if settings.freeze_hour > 12 else settings.freeze_hour}:00 PM sharp, "
         "we treat every morning deployment like a controlled tactical insertion. We map spatial density patterns across "
         "target ZIP networks, cutting down the fuel and drive-time leakages that drive low-class starters into bankruptcy."),
        ("03 / Generational Moats", "The Purpose Pledge",
         "As dedicated Texas homeowners and land stewards, we approach your property boundary with genuine peer "
         "perspective and oversight. Every mission completed allows you to allocate part of your payment directly to "
         f"the local cause you pick: {joined(cause_names(settings))}."),
    )
    cols = "".join(f'<div class="about-pillar"><p class="about-kicker">{esc(k)}</p><h4>{esc(t)}</h4><p>{esc(d)}</p></div>'
                   for k, t, d in pillars)
    body = f"""
    <section class="about-hero" aria-labelledby="about-title">
      <div class="site-wrap about-wrap">
        <div class="about-intro">
          <p class="about-chips"><span>🛡️ Veteran-Owned &amp; Managed</span><span class="dot" aria-hidden="true"></span><span>⚡ NVIDIA AI Infrastructure Trained</span></p>
          <h1 id="about-title">Built on Pedigree. Driven by <span>Discernment.</span></h1>
          <p class="about-lede">Anyone can deploy a lawn mower or purchase an automated robot. But a machine cannot exercise
            situational judgment, and unmanaged contractors lack operational accountability. We engineered
            {esc(settings.business_name.split(" Lawn")[0])} around a single core tenet: bringing elite operational legacy,
            institutional discipline, and data-driven logistics to home asset preservation.</p>
        </div>
        <div class="about-grid">{people}
        </div>
        <div class="about-pillars">{cols}</div>
        <p><a class="btn btn-primary btn-lg" href="/book">Book your first visit</a></p>
      </div>
    </section>"""
    return layout(settings, version, title=f"About | {settings.business_name}",
                  description="Veteran-owned lawn care around Spring, TX, run with operational discipline: "
                              "self-serve booking, planned routes, and a local cause on every order.",
                  body=body, canonical=None)


def register_about_page(app: FastAPI, settings: Settings, version: str = "") -> None:
    @app.get("/about", include_in_schema=False)
    def about():
        return HTMLResponse(about_html(settings, version), headers={"Cache-Control": "no-cache"})
