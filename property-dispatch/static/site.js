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
