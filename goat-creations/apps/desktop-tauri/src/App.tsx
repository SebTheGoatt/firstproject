/**
 * GOAT CREATIONS desktop studio (Tauri).
 *
 * All generation goes through `sebastina-core`'s SEBastinaClient, the same
 * pipeline the mobile app uses. The app only stores the server address and the
 * customer's access token; API keys stay on the SEBastina server.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import {
  GOAT_MODULES,
  IMAGE_MODELS,
  VIDEO_MODELS,
  DEFAULT_IMAGE_MODEL,
  DEFAULT_VIDEO_MODEL,
  SKILLS,
  skillOutput,
  SEBastinaClient,
  createGOATAIEngineHub,
  type Skill,
  type GenerateRequest,
  type GoatModuleId,
} from "sebastina-core";
import "./App.css";

const STORAGE_KEY = "goat-creations.settings";
type TabId = GoatModuleId | "skills" | "photo";
const TABS: { id: TabId; label: string; title: string }[] = [
  ...GOAT_MODULES.map((m) => ({ id: m.id as TabId, label: m.name, title: m.tagline })),
  { id: "skills", label: "Skills", title: "One-tap recipes" },
  { id: "photo", label: "Photo", title: "Start from your photo" },
];
const DEFAULT_SERVER = "http://127.0.0.1:8787";

interface Settings {
  serverUrl: string;
  token: string;
  /** Hugging Face access token for "Draw with FLUX" (kept on this computer only). */
  hfToken: string;
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
    return { serverUrl: saved.serverUrl || DEFAULT_SERVER, token: saved.token || "", hfToken: saved.hfToken || "" };
  } catch {
    return { serverUrl: DEFAULT_SERVER, token: "", hfToken: "" };
  }
}

type Status = { kind: "idle" | "busy" | "ok" | "error"; text: string };

export default function App() {
  const [settings, setSettings] = useState<Settings>(loadSettings);
  const [showSettings, setShowSettings] = useState(() => !loadSettings().token);
  const [moduleId, setModuleId] = useState<TabId>("image");
  const [serverSkills, setServerSkills] = useState<string[]>([]);
  const [prompt, setPrompt] = useState("A majestic goat climbing a high-tech neon mountain, cinematic");
  const [size, setSize] = useState(IMAGE_SIZES[0]);
  const [ratio, setRatio] = useState(VIDEO_RATIOS[0]);
  const [duration, setDuration] = useState(VIDEO_DURATIONS[0]);
  const [status, setStatus] = useState<Status>({ kind: "idle", text: "Ready." });
  const [result, setResult] = useState<{ url: string; isMotion: boolean } | null>(null);
  // "Draw with FLUX": the Hugging Face image, painted onto the workspace canvas.
  const [canvasImage, setCanvasImage] = useState<string | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const hub = useMemo(() => createGOATAIEngineHub({ token: settings.hfToken.trim() }), [settings.hfToken]);

  useEffect(() => {
    if (!canvasImage || !canvasRef.current) return;
    const canvas = canvasRef.current;
    const picture = new Image();
    picture.onload = () => {
      canvas.width = picture.naturalWidth;
      canvas.height = picture.naturalHeight;
      canvas.getContext("2d")!.drawImage(picture, 0, 0);
    };
    picture.src = canvasImage;
  }, [canvasImage]);

  async function drawWithFlux() {
    if (!settings.hfToken.trim()) {
      setShowSettings(true);
      return setStatus({ kind: "error", text: "Add your Hugging Face token in Settings first." });
    }
    setStatus({ kind: "busy", text: "FLUX.1 Schnell is drawing on Hugging Face…" });
    try {
      const dataUrl = await hub.textToImage(prompt, size.width, size.height);
      setResult(null);
      setCanvasImage(dataUrl);
      setStatus({ kind: "ok", text: "Drawn on the canvas with FLUX.1 Schnell (Hugging Face)." });
    } catch (error) {
      setStatus({ kind: "error", text: (error as Error).message });
    }
  }
  const [imageModel, setImageModel] = useState(DEFAULT_IMAGE_MODEL);
  const [videoModel, setVideoModel] = useState(DEFAULT_VIDEO_MODEL);
  /** Models the server allows; empty until fetched (then the full catalog shows). */
  const [serverModels, setServerModels] = useState<string[]>([]);

  // ImageGOAT / MotionGOAT; undefined on the Skills and Photo tabs.
  const module = GOAT_MODULES.find((m) => m.id === moduleId);
  const tabLabel = TABS.find((t) => t.id === moduleId)?.label ?? "";
  const client = useMemo(() => new SEBastinaClient(settings), [settings]);
  const busy = status.kind === "busy";
  const catalog = module?.isMotion ? VIDEO_MODELS : IMAGE_MODELS;
  const models = serverModels.length ? catalog.filter((m) => serverModels.includes(m.id)) : catalog;
  const chosen = module?.isMotion ? videoModel : imageModel;
  const setChosen = module?.isMotion ? setVideoModel : setImageModel;
  const category = moduleId === "photo" ? "photo" : "create";
  const skills = SKILLS.filter((s) => s.category === category && serverSkills.includes(s.id));
  const model = models.find((m) => m.id === chosen) ?? models[0];

  useEffect(() => {
    let cancelled = false;
    client.allowedModels().then((ids) => !cancelled && setServerModels(ids));
    client.allowedSkills().then((ids) => !cancelled && setServerSkills(ids));
    return () => {
      cancelled = true;
    };
  }, [client]);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
    } catch {
      /* storage unavailable: settings last for this session only */
    }
  }, [settings]);

  async function runSkill(skill: Skill, inputs: Record<string, string>, photo: File | null) {
    let photoUrl: string | undefined;
    if (skill.needsPhoto) {
      if (!photo) return setStatus({ kind: "error", text: `${skill.name} needs a photo.` });
      setStatus({ kind: "busy", text: "Uploading photo…" });
      try {
        photoUrl = await client.uploadImage(await cleanPhoto(photo));
      } catch (error) {
        return setStatus({ kind: "error", text: (error as Error).message });
      }
    }
    const isVideo = skillOutput(skill) === "video";
    setStatus({ kind: "busy", text: `Running ${skill.name}…${isVideo ? " Videos can take a few minutes." : ""}` });
    const outcome = await client.runSkill({ skillId: skill.id, inputs, photoUrl });
    if (outcome.success && outcome.data) {
      setResult({ url: outcome.data, isMotion: outcome.kind === "video" });
      setStatus({ kind: "ok", text: `${skill.name} finished.` });
    } else {
      setStatus({ kind: "error", text: outcome.error ?? "Something went wrong." });
    }
  }

  async function generate() {
    if (!module) return;
    const request: GenerateRequest = module.isMotion
      ? { prompt, isMotion: true, model: model?.id, aspectRatio: ratio, duration }
      : { prompt, isMotion: false, model: model?.id, width: size.width, height: size.height };
    setStatus({ kind: "busy", text: module.isMotion ? "Rendering video… this can take a few minutes." : "Generating image…" });
    const outcome = await client.generate(request);
    if (outcome.success && outcome.data) {
      setCanvasImage(null);
      setResult({ url: outcome.data, isMotion: module.isMotion });
      setStatus({ kind: "ok", text: `${module.name} finished with ${model?.name ?? "the default model"}.` });
    } else {
      setStatus({ kind: "error", text: outcome.error ?? "Something went wrong." });
    }
  }

  async function testConnection() {
    setStatus({ kind: "busy", text: "Checking the server…" });
    const ok = await client.health();
    if (ok) {
      setServerModels(await client.allowedModels());
      setServerSkills(await client.allowedSkills());
    }
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
          {TABS.map((t) => (
            <button
              key={t.id}
              className={t.id === moduleId ? "tab active" : "tab"}
              aria-pressed={t.id === moduleId}
              title={t.title}
              onClick={() => setModuleId(t.id)}
            >
              {t.label}
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
              <label>
                Hugging Face token (for Draw with FLUX)
                <input
                  type="password"
                  value={settings.hfToken}
                  placeholder="hf_… from huggingface.co/settings/tokens"
                  onChange={(e) => setSettings({ ...settings, hfToken: e.target.value })}
                  spellCheck={false}
                />
              </label>
            </section>
          )}

          {!module ? (
            <SkillPanel key={category} skills={skills} category={category} busy={busy} onRun={runSkill} />
          ) : (
          <section className="card">
            <h2>{module.name}</h2>
            <p className="dim">{module.tagline}</p>
            <fieldset>
              <legend>Model</legend>
              <div className="models">
                {models.map((m) => (
                  <button
                    key={m.id}
                    className={m.id === model?.id ? "model on" : "model"}
                    aria-pressed={m.id === model?.id}
                    onClick={() => setChosen(m.id)}
                  >
                    <span className="model-name">{m.name}</span>
                    <span className="model-note">{m.note}</span>
                  </button>
                ))}
              </div>
            </fieldset>
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
            {!module.isMotion && (
              <button className="secondary" onClick={drawWithFlux} disabled={busy || !prompt.trim()}>
                Draw with FLUX (Hugging Face)
              </button>
            )}
          </section>
          )}
        </aside>

        <section className="canvas" aria-live="polite">
          {canvasImage && !result ? (
            <canvas ref={canvasRef} className="output" aria-label={`Drawn with FLUX: ${prompt}`} role="img" />
          ) : result ? (
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
        <span className="module-name">{tabLabel}</span>
        <span>{status.text}</span>
      </footer>
    </div>
  );
}

/** Re-encode a photo as JPEG (max 2048 px): drops hidden metadata such as GPS location. */
async function cleanPhoto(file: File): Promise<Blob> {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, 2048 / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d")!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("Couldn't read that photo."))), "image/jpeg", 0.88),
  );
}

function SkillPanel(props: {
  skills: Skill[];
  category: "create" | "photo";
  busy: boolean;
  onRun: (skill: Skill, inputs: Record<string, string>, photo: File | null) => void;
}) {
  const { skills, category, busy, onRun } = props;
  const [selectedId, setSelectedId] = useState(skills[0]?.id);
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [photo, setPhoto] = useState<File | null>(null);
  const preview = useMemo(() => (photo ? URL.createObjectURL(photo) : null), [photo]);
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);
  const skill = skills.find((s) => s.id === selectedId) ?? skills[0];

  if (!skill) {
    return (
      <section className="card">
        <h2>{category === "photo" ? "Photo tools" : "Skills"}</h2>
        <p className="dim">This server offers none yet. The owner turns them on with SEBASTINA_SERVER_SKILLS.</p>
      </section>
    );
  }
  const missing = skill.fields.find((f) => !f.fallback && !(inputs[f.id] ?? "").trim());
  return (
    <section className="card">
      <h2>{category === "photo" ? "Photo tools" : "Skills"}</h2>
      <div className="models" role="radiogroup" aria-label={category === "photo" ? "Photo tools" : "Skills"}>
        {skills.map((s) => (
          <button key={s.id} className={s.id === skill.id ? "model on" : "model"} role="radio" aria-checked={s.id === skill.id} onClick={() => setSelectedId(s.id)}>
            <span className="model-name">{s.name} <span className="badge">{skillOutput(s) === "video" ? "VIDEO" : "IMAGE"}</span></span>
            <span className="model-note">{s.description}</span>
          </button>
        ))}
      </div>
      {skill.fields.map((f) => (
        <label key={f.id}>
          {f.label}{f.fallback ? " (optional)" : ""}
          <input value={inputs[f.id] ?? ""} placeholder={f.placeholder} maxLength={600}
            onChange={(e) => setInputs((prev) => ({ ...prev, [f.id]: e.target.value }))} />
        </label>
      ))}
      {skill.needsPhoto && (
        <label>
          Photo
          <input type="file" accept="image/jpeg,image/png,image/webp" onChange={(e) => setPhoto(e.target.files?.[0] ?? null)} />
          {preview && <img className="thumb" src={preview} alt="Chosen photo" />}
        </label>
      )}
      <button className="primary" disabled={busy || !!missing || (skill.needsPhoto && !photo)} onClick={() => onRun(skill, inputs, photo)}>
        {busy ? "Working…" : `Run ${skill.name}`}
      </button>
      <p className="dim">
        {skill.steps.length > 1 ? `${skill.steps.length} steps · ` : ""}{skillOutput(skill) === "video" ? "Makes a video" : "Makes an image"}
        {missing ? ` · Fill in "${missing.label}"` : ""}
      </p>
    </section>
  );
}
