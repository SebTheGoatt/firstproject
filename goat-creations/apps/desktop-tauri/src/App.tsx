/**
 * GOAT CREATIONS desktop studio (Tauri).
 *
 * All generation goes through `sebastina-core`'s SEBastinaClient, the same
 * pipeline the mobile app uses. The app only stores the server address and the
 * customer's access token; API keys stay on the SEBastina server.
 */
import { useEffect, useMemo, useState } from "react";
import { GOAT_MODULES, SEBastinaClient, type GenerateRequest, type GoatModuleId } from "sebastina-core";
import "./App.css";

const STORAGE_KEY = "goat-creations.settings";
const DEFAULT_SERVER = "http://127.0.0.1:8787";

interface Settings {
  serverUrl: string;
  token: string;
}

const IMAGE_SIZES = [
  { label: "Square", width: 1024, height: 1024 },
  { label: "Landscape", width: 1344, height: 768 },
  { label: "Portrait", width: 768, height: 1344 },
];
const VIDEO_RATIOS = ["16:9", "9:16", "1:1"];
const VIDEO_DURATIONS = [5, 10];

function loadSettings(): Settings {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}");
    return { serverUrl: saved.serverUrl || DEFAULT_SERVER, token: saved.token || "" };
  } catch {
    return { serverUrl: DEFAULT_SERVER, token: "" };
  }
}

type Status = { kind: "idle" | "busy" | "ok" | "error"; text: string };

export default function App() {
  const [settings, setSettings] = useState<Settings>(loadSettings);
  const [showSettings, setShowSettings] = useState(() => !loadSettings().token);
  const [moduleId, setModuleId] = useState<GoatModuleId>("image");
  const [prompt, setPrompt] = useState("A majestic goat climbing a high-tech neon mountain, cinematic");
  const [size, setSize] = useState(IMAGE_SIZES[0]);
  const [ratio, setRatio] = useState(VIDEO_RATIOS[0]);
  const [duration, setDuration] = useState(VIDEO_DURATIONS[0]);
  const [status, setStatus] = useState<Status>({ kind: "idle", text: "Ready." });
  const [result, setResult] = useState<{ url: string; isMotion: boolean } | null>(null);

  const module = GOAT_MODULES.find((m) => m.id === moduleId)!;
  const client = useMemo(() => new SEBastinaClient(settings), [settings]);
  const busy = status.kind === "busy";

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
    } catch {
      /* storage unavailable: settings last for this session only */
    }
  }, [settings]);

  async function generate() {
    const request: GenerateRequest = module.isMotion
      ? { prompt, isMotion: true, aspectRatio: ratio, duration }
      : { prompt, isMotion: false, width: size.width, height: size.height };
    setStatus({ kind: "busy", text: module.isMotion ? "Rendering video… this can take a few minutes." : "Generating image…" });
    const outcome = await client.generate(request);
    if (outcome.success && outcome.data) {
      setResult({ url: outcome.data, isMotion: module.isMotion });
      setStatus({ kind: "ok", text: `${module.name} finished.` });
    } else {
      setStatus({ kind: "error", text: outcome.error ?? "Something went wrong." });
    }
  }

  async function testConnection() {
    setStatus({ kind: "busy", text: "Checking the server…" });
    const ok = await client.health();
    setStatus(ok ? { kind: "ok", text: "Server reachable." } : { kind: "error", text: `Can't reach ${settings.serverUrl}.` });
  }

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="mark" aria-hidden="true">G</span>
          <span className="wordmark">GOAT CREATIONS</span>
        </div>
        <nav className="modules" aria-label="Modules">
          {GOAT_MODULES.map((m) => (
            <button
              key={m.id}
              className={m.id === moduleId ? "tab active" : "tab"}
              aria-pressed={m.id === moduleId}
              title={m.tagline}
              onClick={() => setModuleId(m.id)}
            >
              {m.name}
            </button>
          ))}
        </nav>
        <button className="ghost" aria-expanded={showSettings} onClick={() => setShowSettings((s) => !s)}>
          Settings
        </button>
      </header>

      <main className="workspace">
        <aside className="panel">
          {showSettings && (
            <section className="card">
              <h2>Connection</h2>
              <label>
                Server address
                <input
                  value={settings.serverUrl}
                  onChange={(e) => setSettings({ ...settings, serverUrl: e.target.value })}
                  spellCheck={false}
                />
              </label>
              <label>
                Access token
                <input
                  type="password"
                  value={settings.token}
                  placeholder="From your GOAT CREATIONS account"
                  onChange={(e) => setSettings({ ...settings, token: e.target.value })}
                  spellCheck={false}
                />
              </label>
              <button className="secondary" onClick={testConnection} disabled={busy}>
                Test connection
              </button>
            </section>
          )}

          <section className="card">
            <h2>{module.name}</h2>
            <p className="dim">{module.tagline}</p>
            <label>
              Prompt
              <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={6} maxLength={3000} />
            </label>

            {module.isMotion ? (
              <>
                <fieldset>
                  <legend>Aspect ratio</legend>
                  <div className="chips">
                    {VIDEO_RATIOS.map((r) => (
                      <button key={r} className={r === ratio ? "chip on" : "chip"} aria-pressed={r === ratio} onClick={() => setRatio(r)}>
                        {r}
                      </button>
                    ))}
                  </div>
                </fieldset>
                <fieldset>
                  <legend>Length</legend>
                  <div className="chips">
                    {VIDEO_DURATIONS.map((d) => (
                      <button key={d} className={d === duration ? "chip on" : "chip"} aria-pressed={d === duration} onClick={() => setDuration(d)}>
                        {d} s
                      </button>
                    ))}
                  </div>
                </fieldset>
              </>
            ) : (
              <fieldset>
                <legend>Size</legend>
                <div className="chips">
                  {IMAGE_SIZES.map((s) => (
                    <button key={s.label} className={s === size ? "chip on" : "chip"} aria-pressed={s === size} onClick={() => setSize(s)}>
                      {s.label}
                    </button>
                  ))}
                </div>
              </fieldset>
            )}

            <button className="primary" onClick={generate} disabled={busy || !prompt.trim()}>
              {busy ? "Working…" : `Generate with ${module.name}`}
            </button>
          </section>
        </aside>

        <section className="canvas" aria-live="polite">
          {result ? (
            result.isMotion ? (
              <video className="output" src={result.url} controls autoPlay loop />
            ) : (
              <img className="output" src={result.url} alt={`Generated: ${prompt}`} />
            )
          ) : (
            <div className="empty">
              <span className="mark big" aria-hidden="true">G</span>
              <h1>
                <span className="gold">GOAT</span> CREATIONS
              </h1>
              <p>The Greatest of All Time Open-Source Creative Suite</p>
            </div>
          )}
        </section>
      </main>

      <footer className={`status ${status.kind}`} role="status">
        <span className="module-name">{module.name}</span>
        <span>{status.text}</span>
      </footer>
    </div>
  );
}
