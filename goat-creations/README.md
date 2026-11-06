# GOAT CREATIONS

**The Greatest of All Time Open-Source Creative Suite.**
Minimalist, dark, fast, and built for developers who make things.

| Module | What it is | Where |
| --- | --- | --- |
| **ImageGOAT** | AI image generation (FLUX via MuAPI) | desktop, mobile, CLI |
| **MotionGOAT** | AI video generation (Seedance via MuAPI) | desktop, mobile, CLI |
| **VectorGOAT** | Vector & illustration editor | `apps/desktop-egui` |
| **Skills** | One-tap recipes: YouTube Thumbnail, Instagram Post, Ad Creative, Logo, Blog Header, Drone Shot Video, Action Figure, Product Ad Video | desktop, mobile, ComfyUI |
| **Photo tools** | Animate Photo, Edit with Words, Upscale, Remove Background | desktop, mobile, ComfyUI |
| **SEBastina** | An original, consistent character: design her once, then Post / Thumbnail / Video | mobile |
| **Own computer** | Everything above on your own GPU with open models (ComfyUI), no API | mobile, desktop, server |
| **Hugging Face** | FLUX.1 Schnell images and Wan 2.1 video with just an HF token | mobile, desktop, server |

## Layout (npm workspaces + Turborepo)

```
goat-creations/
├── package.json               workspaces, scripts, one React version for all apps
├── turbo.json                 build/test pipeline (core builds first)
├── packages/
│   └── sebastina-core/        the shared pipeline
│       ├── src/engine.ts          ImageGOAT/MotionGOAT routing, Skills, photo upload (MuAPI format)
│       ├── src/models.ts          19 models and the exact fields each one accepts
│       ├── src/skills.ts          8 Skills + 4 photo tools (plain data, shared with ComfyUI)
│       ├── src/client.ts          SEBastinaClient: what the apps call
│       ├── src/billing/           Lago subscription + credit gate
│       ├── src/paywall/x402.ts    AI-crawler paywall (HTTP 402, USDC)
│       └── src/auth.ts            signed customer access tokens
└── apps/
    ├── server/                SEBastina server: holds the API keys, runs the pipeline
    ├── desktop-tauri/         Tauri 2 + React + TypeScript (Windows / macOS / Linux)
    ├── mobile-expo/           Expo SDK 58 (iOS / Android)
    ├── comfyui-goat/          ComfyUI node pack (Python): every Skill and tool as a node
    ├── cli/                   terminal studio for the owner
    └── desktop-egui/          the Rust/egui VectorGOAT editor
```

### How the pieces fit

```
desktop-tauri ─┐                         ┌─ MuAPI (FLUX, Seedance)
mobile-expo  ──┼─ SEBastinaClient ─► server ─┤
               │  (sebastina-core)  (sebastina-core engine
               │                     + Lago credit gate)   └─ Lago (subscription, credits)
AI crawlers ───┴──────────────────► server: x402 paywall ──► x402 facilitator (USDC on Base)
```

Both apps use the exact same pipeline through `sebastina-core`. The API keys
(MuAPI, Lago) live **only on the server**: anything shipped inside an app can be
unpacked and read, so apps carry a customer access token instead.

## Quick start

```bash
cd goat-creations
npm install              # installs every workspace and links sebastina-core
npm run build            # builds core first, then the apps (turbo)
npm test                 # core checks: credit gate, paywall, tokens
```

### 1. Server

```bash
cd apps/server
cp .env.example .env     # MUAPI_API_KEY, LAGO_API_KEY, SEBASTINA_TOKEN_SECRET, PAYWALL_PAY_TO
npm start                # http://127.0.0.1:8787
npm run token -- <lago-customer-id>   # access token to give that customer
```

### 2. Desktop (Tauri)

```bash
npm run desktop:dev      # from the root; or: cd apps/desktop-tauri && npm run tauri dev
```

Linux needs WebKitGTK once: `sudo apt install libwebkit2gtk-4.1-dev build-essential libxdo-dev libssl-dev libayatana-appindicator3-dev librsvg2-dev`.
Windows and macOS: see https://tauri.app/start/prerequisites/.
Open **Settings**, enter the server address and your access token, then generate.

### 3. Mobile (Expo)

```bash
npm run mobile:start     # scan the QR code with Expo Go
```

On a phone, `127.0.0.1` means the phone itself: enter your computer's network
address (e.g. `http://192.168.1.10:8787`). The token is kept in the device's
secure storage (Keychain / Keystore).

### 4. VectorGOAT editor (Rust)

```bash
cd apps/desktop-egui && cargo run
```

## Hugging Face (FLUX.1 Schnell + Wan 2.1, token only)

`GOATAIEngineHub` / `generateFluxAsset` (`packages/sebastina-core/src/aiHub.ts`) run open
models hosted on Hugging Face Inference Providers (fal.ai or WaveSpeed today) with an
access token. No GPU needed; each request is billed to the token's Hugging Face account
(free accounts get a small monthly credit).

```ts
import { createGOATAIEngineHub, generateFluxAsset } from 'sebastina-core';
const hub = createGOATAIEngineHub({ token });            // token from the app's Settings
const dataUrl = await hub.textToImage('a goat', 1024, 576);  // FLUX.1 Schnell, 4 steps
const { videoUrl } = await hub.textToVideo('a goat running'); // Wan 2.1, 81 frames
const asset = await generateFluxAsset('a goat');         // { blob, dataUrl, mimeType, model }
```

- Apps: the token is typed into Settings and kept on the device (phone: secure storage),
  never built into an app. Server / CLI: `HF_ACCESS_TOKEN` in `.env` (loaded by `sebastina-core/server`).
- Desktop: **Draw with FLUX (Hugging Face)** paints the result onto the workspace canvas.
- Phone: **Settings → Hugging Face**; on MotionGOAT, **swipe the gold knob** to render one Wan clip
  (one render per swipe; screen readers get a double-tap action), played inline.
- Text-only Skills work too; photo tools need MuAPI or your own computer.
- The token needs the "Make calls to Inference Providers" permission.

## Run it on your own computer (no API, no per-image cost)

GOAT can run entirely on your own GPU with open-weight models, through
[ComfyUI](https://github.com/comfyanonymous/ComfyUI) and the GOAT pack. The phone,
desktop app and server talk to ComfyUI's API instead of MuAPI.

| Setup | Models (license) | Download | GPU | What works |
| --- | --- | --- | --- | --- |
| **Light** | Stable Diffusion 1.5 (OpenRAIL-M), Real-ESRGAN (BSD-3), BiRefNet (MIT) | ~2.3 GB | 8 GB (or CPU, slowly) | text→image, image Skills, Design SEBastina, upscale, remove background |
| **Full** | + FLUX.1 Schnell, Qwen-Image-Edit 2509, Wan 2.2 TI2V 5B (all Apache-2.0) | ~66 GB | 24 GB | everything: photo edits, SEBastina scenes, Product Ad Video, video |
| **Pro** | Z-Image Turbo (photoreal), Qwen-Image 2512 (lettering), Qwen-Image-Edit 2511, Wan 2.2 14B video, each with its 4-step Lightning LoRA (all Apache-2.0) | ~143 GB | 24 GB+ (32 GB comfortable) | everything, at flagship open-model quality |

Pro follows ComfyUI's official workflow templates for these models; each workflow is checked
against ComfyUI's node definitions and was accepted by a real ComfyUI's validation. Models with
licenses that limit commercial use (FLUX.1/2 Dev, Krea 2, Hunyuan, LTX-2, Qwen-Image 2.1) are left out.
Closed flagships (Veo, Kling, GPT Image, Nano Banana) stay available as optional paid backends via MuAPI.

**One command:** `apps/render-node/setup.sh` (Linux/macOS) or `apps/render-node/setup.ps1`
(Windows) does steps 1–4 below and starts the node; add `--full` / `-Full` or `--pro` / `-Pro`.
It is safe to re-run. The SEBastina server uses this render node by default
(`SEBASTINA_BACKEND=comfyui`); MuAPI and Hugging Face are optional, paid, and off unless you choose them.

1. Install ComfyUI on the computer with the graphics card.
2. Copy `apps/comfyui-goat` into `ComfyUI/custom_nodes/`, then
   `pip install -r custom_nodes/comfyui-goat/requirements.txt` (use `onnxruntime-gpu` on NVIDIA).
3. From the ComfyUI folder: `python custom_nodes/comfyui-goat/download_models.py` (add `--full` for the Full setup).
4. Start ComfyUI so the phone can reach it: `python main.py --listen 0.0.0.0`
   (add `--enable-cors-header` for the desktop app).
5. Phone: **Settings → My computer**, enter `http://<computer's IP>:8188`, pick Light or Full, **Save and test**.

ComfyUI has no login: keep it on your home network. To use it away from home,
put both devices on a private network such as Tailscale; never open port 8188 to
the internet. For customers, run the SEBastina server with `SEBASTINA_BACKEND=comfyui`:
it keeps ComfyUI private and hands out signed file links.

The workflows use ComfyUI's built-in nodes, plus the GOAT pack's own
"GOAT Remove Background (local)" node. `npm run check-workflows -- object_info.json`
(in `packages/sebastina-core`) checks every one against a ComfyUI's node definitions.

## Skills and photo tools

Skills are fill-in templates (your subject, your headline), inspired by the Skill
workflows in MuAPI's ComfyUI pack. Some chain models: **Product Ad Video** re-stages
your product photo with FLUX.2 Edit, then animates it with Wan 2.5. Photos are
re-encoded before upload, which strips hidden metadata such as GPS location.

On the server, Skills are off until you list them in `SEBASTINA_SERVER_SKILLS`
(each step costs a credit; video steps cost `CREDITS_PER_VIDEO`). Photos go through
`POST /api/upload` (JPEG/PNG/WebP/HEIC, 10 MB) and Skills only accept photos that
were uploaded that way.

## SEBastina (consistent character)

**Design SEBastina** turns a written description into a reference portrait; you
save the one you like, and SEBastina Post, Thumbnail and Video start from that
reference so she looks the same everywhere. Rules enforced in code, not just in
the prompts:

- she is always an adult, always fully clothed and safe-for-work: `contentIssue()`
  refuses explicit, underwear or minor wording before anything is sent or billed;
- her reference only ever comes from Design SEBastina (no uploaded photos), so no
  real person's face can be mapped onto her. These Skills are not in the ComfyUI
  pack for the same reason (any image could be wired in there).

## ComfyUI node pack

`apps/comfyui-goat` turns the same catalog into ComfyUI nodes: GOAT Image, GOAT
Video, one node per Skill and photo tool, and GOAT Save Video. The catalog is
generated from `sebastina-core` (`npm run catalog`), and a parity test proves the
Python port builds the same MuAPI requests as the apps. See its README to install.

## Billing (Lago)

Before every generation, `lagoCreditGate` checks the customer's **active
subscription** and **wallet credits**, takes the credits (`CREDITS_PER_IMAGE` /
`CREDITS_PER_VIDEO`, default 1), and refunds them if the generation fails. If
Lago can't be reached, generation is refused. In Lago: create a plan, subscribe
the customer, give them a wallet with credits.

## AI-crawler paywall (x402)

Everything the server serves outside `/api` and `/health` sits behind
`crawlerPaywall`. People and ordinary bots get content free. Requests whose
User-Agent names an AI crawler (GPTBot, ClaudeBot, PerplexityBot, CCBot,
Bytespider, meta-externalagent, cohere-ai, …):

1. get **HTTP 402 Payment Required** and no content,
2. with a JSON body in the [x402](https://github.com/x402-foundation/x402) format:
   0.001 USDC (`maxAmountRequired: "1000"`), `payTo` your wallet, USDC on Base,
3. may retry with a signed payment in `X-PAYMENT` (or `Authorization: x402 <payload>`).
   The payment is verified and settled through an x402 facilitator, then the
   asset streams with an `X-PAYMENT-RESPONSE` receipt. Invalid or malformed
   payments get a 402 and the connection is closed.

Settings: `PAYWALL_PAY_TO` (required; without it AI crawlers are refused),
`PAYWALL_NETWORK` (`base-sepolia` test money by default; `base` for real USDC,
which needs a mainnet facilitator such as Coinbase's), `PAYWALL_PRICE_USDC`.

Limits worth knowing: the User-Agent is self-reported, so a scraper that hides
its name passes as a person, and one could pretend to be GPTBot. Major crawlers
publish IP ranges if you later want to verify them.

## Generation backend: MuAPI

The request format follows [Open-Generative-AI](https://github.com/Anil-matcha/Open-Generative-AI)
(MIT), which runs on the hosted MuAPI service (pay per generation): `POST /api/v1/<model>`
with `x-api-key`, then poll `/api/v1/predictions/<id>/result`. Defaults: `flux-dev-image`
and `seedance-lite-t2v`; any MuAPI model works via `SEBASTINA_IMAGE_MODEL` /
`SEBASTINA_VIDEO_MODEL`. To re-read their source:
`git clone --depth 1 https://github.com/Anil-matcha/Open-Generative-AI vendor/open-gen` (git-ignored).

## License

MIT OR Apache-2.0.
