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
