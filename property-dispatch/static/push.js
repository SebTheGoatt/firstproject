// "Get updates on this phone": shared by the visit page and the booking confirmation.
// The permission prompt only appears when the button is tapped; the phone is then saved for that one booking.

window.SGPush = (() => {
  const toKey = (b64) => {
    const raw = atob((b64 + "=".repeat((4 - (b64.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(raw, (c) => c.charCodeAt(0));
  };

  // box = wrapper (stays hidden unless notifications can work here), btn = the button, note = the small print.
  async function setup(code, { box, btn, note }) {
    try {
      const cfg = await (await fetch("/api/push-config")).json();
      if (!cfg.public_key || !("serviceWorker" in navigator)) return;
      const standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
      const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent);
      if (!("PushManager" in window) || !("Notification" in window)) {
        if (isIOS && !standalone) {            // iPhones only allow this from the Home Screen app
          btn.hidden = true;
          note.textContent = "On iPhone, tap Share, then Add to Home Screen, and open the app from there to get visit updates.";
          box.hidden = false;
        }
        return;
      }
      if (Notification.permission === "denied") return;
      const reg = await navigator.serviceWorker.ready;
      const existing = await reg.pushManager.getSubscription();
      box.hidden = false;
      if (existing && Notification.permission === "granted") {
        btn.hidden = true; note.textContent = "Visit updates are on for this phone."; return;
      }
      btn.onclick = async () => {
        btn.disabled = true;
        try {
          if ((await Notification.requestPermission()) !== "granted") {
            note.textContent = "No problem. You can still check this page anytime."; btn.hidden = true; return;
          }
          const sub = (await reg.pushManager.getSubscription()) || await reg.pushManager.subscribe({
            userVisibleOnly: true, applicationServerKey: toKey(cfg.public_key) });
          const j = sub.toJSON();
          const res = await fetch(`/api/visit/${encodeURIComponent(code)}/push`, { method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ endpoint: j.endpoint, keys: j.keys, lang: window.I18N?.lang === "es" ? "es" : "en" }) });
          if (!res.ok) throw new Error("save failed");
          btn.hidden = true; note.textContent = "Visit updates are on for this phone.";
        } catch {
          btn.disabled = false; note.textContent = "We couldn't turn updates on. Please try again.";
        }
      };
    } catch { /* notifications are optional; the page works without them */ }
  }

  return { setup };
})();
