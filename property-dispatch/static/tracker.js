/* Semper Green — activity tracker (v4)
 * ---------------------------------------------------
 * Sends: pageviews, booking-funnel milestones, heartbeats, and
 * estimated departures (exits). Booking completions are counted
 * ONLY on the server (see app/live_feed.py record_booking).
 *
 * Every beacon carries a per-page-load instance id (pid), which lets
 * the server tell an old page's exit beacon apart from a real
 * departure — no timing guesswork.
 *
 * Privacy: sends only a page label (home / booking / team / visit /
 * other — never the raw URL, query strings, or access tokens),
 * the referrer's domain, and random per-tab ids. No names, phones,
 * addresses, or anything typed into the form.
 *
 * Install: add  <script src="/static/tracker.js?v={{V}}" defer></script>
 * before </body> on every page (home, book, team, visit).
 */
(() => {
  "use strict";

  const SID_KEY = "sg_sid";
  let sid = sessionStorage.getItem(SID_KEY);
  if (!sid) {
    sid = (crypto.randomUUID ? crypto.randomUUID()
      : Date.now().toString(36) + Math.random().toString(36).slice(2, 10));
    sessionStorage.setItem(SID_KEY, sid);
  }

  // Fresh id per page load: identifies which page a beacon belongs to.
  const pid = (crypto.randomUUID ? crypto.randomUUID()
    : Date.now().toString(36) + Math.random().toString(36).slice(2, 10));

  const start = Date.now();

  // Map the URL to a fixed label — raw paths (which can contain access
  // tokens, e.g. /visit/<code>) never leave the browser.
  const ROUTES = [["/book", "booking"], ["/team", "team"], ["/visit", "visit"]];
  const routeLabel = () => {
    const p = location.pathname;
    if (p === "/" || p === "") return "home";
    for (const [prefix, name] of ROUTES) if (p.startsWith(prefix)) return name;
    return "other";
  };
  const refDomain = () => {
    try { return document.referrer ? new URL(document.referrer).hostname : null; }
    catch { return null; }
  };

  function post(body) {
    try {
      fetch("/api/track", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        keepalive: true,
      }).catch(() => {});
    } catch { /* never break the page over analytics */ }
  }

  const base = () => ({ sid, pid, path: routeLabel(), ref: refDomain() });

  post({ event: "pageview", ...base() });

  // Heartbeat: keeps "online now" honest while someone reads a page
  // (otherwise a reader disappears from the count after 5 idle minutes).
  setInterval(() => {
    if (document.visibilityState === "visible") post({ event: "ping", ...base() });
  }, 60000);

  // Estimated departure: fires on tab close, back button, external link.
  // The server retracts it if the same session opens another page on the
  // site shortly after (internal navigation).
  let exited = false;
  addEventListener("pagehide", () => {
    if (exited) return;
    exited = true;
    const body = JSON.stringify({
      event: "exit",
      ...base(),
      step: window.__sgStep || null,
      dwell_ms: Date.now() - start,
    });
    if (navigator.sendBeacon) {
      navigator.sendBeacon("/api/track", new Blob([body], { type: "application/json" }));
    }
  });

  // ---- booking-funnel milestones (only on /book) ----
  //   1 lawn size entered   2 rate chosen   3 quote displayed   4 submit clicked
  // Each milestone is reported once per page load, independently —
  // visitors can fill the form in any order. "Booked" (5) is counted
  // only by the server.
  if (location.pathname !== "/book") return;

  const seen = new Set();
  window.__sgStep = 0;

  const reached = (n) => {
    if (seen.has(n)) return;
    seen.add(n);
    window.__sgStep = Math.max(window.__sgStep || 0, n);
    post({ event: "step", ...base(), step: n });
  };

  // 1 — lawn size entered
  document.addEventListener("input", (e) => {
    if (e.target && e.target.id === "lawn-sqft" && e.target.value.trim()) reached(1);
  }, true);

  // 2 — rate chosen
  document.addEventListener("change", (e) => {
    const t = e.target;
    if (t && t.name === "package_pick" && t.checked) reached(2);
  }, true);

  // 3 — itemized quote displayed (the review box becomes visible)
  const priceLines = document.getElementById("price-lines");
  if (priceLines) {
    new MutationObserver(() => { if (!priceLines.hidden) reached(3); })
      .observe(priceLines, { attributes: true, attributeFilter: ["hidden"] });
  }

  // 4 — submit clicked (booking completion is counted server-side)
  const form = document.getElementById("intake");
  if (form) form.addEventListener("submit", () => reached(4), { once: true });
})();
