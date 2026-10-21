// Shared by every page: offline support + "Install app" button.

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}

// Android / desktop Chrome & Edge fire beforeinstallprompt; iOS Safari never does,
// so iPhone users get Share → Add to Home Screen instructions instead.
(function () {
  const btn = document.getElementById("install-btn");
  const iosHint = document.getElementById("install-ios");
  if (!btn && !iosHint) return;

  const standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
  if (standalone) return;

  let deferred = null;
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferred = e;
    if (btn) btn.hidden = false;
  });
  btn?.addEventListener("click", async () => {
    if (!deferred) return;
    deferred.prompt();
    await deferred.userChoice.catch(() => {});
    deferred = null;
    btn.hidden = true;
  });
  window.addEventListener("appinstalled", () => { if (btn) btn.hidden = true; });

  const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  if (isIOS && iosHint) iosHint.hidden = false;
})();

// Donations are split 33% VFW / 33% NICU / 34% at-risk youth. Same math as the
// server (app/charity.py): whole cents, leftover cents to the largest remainders.
const charities = [
  { key: "vfw", percent: 33, short: "VFW" },
  { key: "nicu", percent: 33, short: "NICU" },
  { key: "at_risk_youth", percent: 34, short: "at-risk youth" },
];
function splitDonation(amount) {
  const total = Math.round((amount || 0) * 100);
  if (total <= 0) return {};
  const raw = charities.map((c) => ({ key: c.key, exact: (total * c.percent) / 100 }));
  raw.forEach((r) => { r.cents = Math.floor(r.exact + 1e-9); });
  let left = total - raw.reduce((n, r) => n + r.cents, 0);
  [...raw].sort((a, b) => (b.exact - b.cents) - (a.exact - a.cents)).forEach((r) => { if (left > 0) { r.cents += 1; left -= 1; } });
  return Object.fromEntries(raw.map((r) => [r.key, r.cents / 100]));
}

// Where this visitor found us, for the owner's marketing scoreboard. A ?ref= from a QR code, flyer or post wins
// (e.g. ?ref=yard-sign-klein); otherwise UTM tags; otherwise the site they came from (Google, Facebook, an AI
// assistant). Kept 30 days in this browser and sent with a booking. Only a short label: never anything personal.
(function () {
  const clean = (v) => (v || "").toLowerCase().replace(/[^a-z0-9-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 48);
  const FROM = [[/(^|\.)google\./, "google"], [/(^|\.)bing\.com$/, "bing"], [/(^|\.)(facebook|fb)\.com$/, "facebook"],
                [/(^|\.)instagram\.com$/, "instagram"], [/(^|\.)tiktok\.com$/, "tiktok"], [/(^|\.)nextdoor\.com$/, "nextdoor"],
                [/(^|\.)yelp\.com$/, "yelp"], [/(^|\.)(chatgpt\.com|openai\.com)$/, "ai-chatgpt"],
                [/(^|\.)perplexity\.ai$/, "ai-perplexity"], [/(^|\.)(claude\.ai|gemini\.google\.com|copilot\.microsoft\.com)$/, "ai-assistant"]];
  try {
    const q = new URLSearchParams(location.search);
    let ref = clean(q.get("ref") || [q.get("utm_source"), q.get("utm_campaign")].filter(Boolean).join("-"));
    if (!ref && document.referrer) {
      const host = new URL(document.referrer).hostname;
      if (host && host !== location.hostname) {
        const hit = FROM.find(([re]) => re.test(host));
        ref = hit ? (hit[1] === "google" && host.startsWith("gemini.") ? "ai-assistant" : hit[1]) : "";
      }
    }
    if (ref) localStorage.setItem("po_ref", JSON.stringify({ r: ref, t: Date.now() }));
  } catch {}
  window.poSource = () => {
    try {
      const v = JSON.parse(localStorage.getItem("po_ref") || "null");
      return v && Date.now() - v.t < 30 * 864e5 ? v.r : null;
    } catch { return null; }
  };
})();
