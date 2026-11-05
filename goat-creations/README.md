# GOAT CREATIONS

**The Greatest of All Time Open-Source Creative Suite.**
Minimalist, dark, fast, and built for developers who make things.

| Module | What it is | Status |
| --- | --- | --- |
| **VectorGOAT** | Vector & illustration design | Active (this MVP) |
| **ImageGOAT** | Raster & photo editing | Planned |
| **MotionGOAT** | Video & animation | Planned |

This folder holds two pieces:

- **The desktop suite** (Rust + egui): this folder.
- **SEBastina** (`sebastina/`): a TypeScript CLI that sends ImageGOAT / MotionGOAT
  prompts to an AI generation server, such as a local Stable Diffusion WebUI.

---

## Desktop suite (Rust)

### Run it

```bash
cd goat-creations
cargo run            # debug build (dependencies are still optimized)
cargo run --release  # fully optimized
cargo test           # 27 engine tests, no window needed
```

Needs Rust 1.85 or newer (`rustup update`).

**Linux only:** install the usual windowing libraries once:

```bash
# Debian / Ubuntu
sudo apt install libxkbcommon-x11-0 libgl1 libwayland-client0
```

Windows and macOS need nothing extra.

### What works today

- **Select (V):** click to pick, drag to move, Delete to remove, Esc to deselect
- **Brush (B):** freehand strokes with size and color
- **Vector (P):** rectangles and ellipses, outline or filled; hold Shift for a square or circle
- **Text (T):** click to place text; edit the content and size in the inspector
- **Canvas:** scroll to pan, Ctrl + scroll (or pinch) to zoom at the cursor, Space + drag or middle-drag to pan, Ctrl+0 to fit
- **Inspector:** tool settings, quick color swatches, selection properties, artboard size and background, layer list with show/hide
- **Undo / redo** (Ctrl+Z, Ctrl+Shift+Z or Ctrl+Y). Slider and color drags undo as one step.
- **Project files:** File > Save / Open (`.goat.json`). Saves are atomic, and you're asked before unsaved work is thrown away, including when closing the window.

### Architecture

```
src/
├── main.rs          window lifecycle: native options, icon, run_native
├── app.rs           GoatApp state, Action routing, per-frame layout, dialogs
├── ui/              reusable UI: each panel draws itself and returns Actions
│   ├── theme.rs     brand palette ("GOAT gold" on dark), egui style, app icon
│   ├── menu_bar.rs  brand mark, File / Edit / GOAT Tools, module switcher
│   ├── toolbar.rs   left tool rail with icons drawn in code
│   ├── inspector.rs tool settings, selection, artboard, layers
│   ├── canvas.rs    pan/zoom workspace: input to engine, document rendering
│   ├── status_bar.rs
│   └── widgets.rs   logo mark, swatches, property rows
└── engine/          no UI code, fully unit-tested
    ├── document.rs  Document, Element, hit testing, z-order
    ├── editor.rs    the editing pipeline: gestures and commands to document edits
    ├── history.rs   snapshot undo/redo with coalescing
    ├── viewport.rs  world/screen transform, zoom around cursor, fit
    ├── tools.rs     Tool enum and ToolSettings
    └── io.rs        versioned .goat.json save/load
```

**How events flow:** keyboard shortcuts, menus, toolbar and inspector buttons all
produce `Action` values, and `GoatApp::dispatch` handles them in one place. Direct
manipulation on the canvas (painting, dragging) calls the `Editor` directly. The
engine never touches egui widgets, so ImageGOAT and MotionGOAT can share it.

**Renderer:** OpenGL via `glow`, for the widest hardware support. To try wgpu
(Vulkan / Metal / DX12), swap `"glow"` for `"wgpu"` in `Cargo.toml`.

---

## SEBastina CLI (TypeScript)

A terminal studio that sends ImageGOAT / MotionGOAT prompts to an AI backend, with
Lago billing in front of every generation.

```bash
cd goat-creations/sebastina
cp .env.example .env     # add MUAPI_API_KEY and LAGO_API_KEY
npm install
npm test                 # credit-gate checks against a local stand-in server
npm start
```

### Generation backend: MuAPI

The request format follows [Open-Generative-AI](https://github.com/Anil-matcha/Open-Generative-AI)
(MIT), which runs on the hosted MuAPI service (`api.muapi.ai`, pay per generation):

- Submit: `POST /api/v1/<model>` with header `x-api-key`, returns a `request_id`.
- Poll: `GET /api/v1/predictions/<request_id>/result` every 2 s until `completed`;
  the result is a URL in `outputs[0]`.
- ImageGOAT: `flux-dev-image` (FLUX.1 Dev) with `prompt, width, height, num_images`
  (sizes rounded to multiples of 64, 128 to 2048).
- MotionGOAT: `seedance-lite-t2v` (Seedance 1.0 Lite) with `prompt, aspect_ratio, duration, resolution`.
- Any other MuAPI model: set `SEBASTINA_IMAGE_MODEL` / `SEBASTINA_VIDEO_MODEL`.

To re-read their source: `git clone --depth 1 https://github.com/Anil-matcha/Open-Generative-AI vendor/open-gen`
(`vendor/` is git-ignored).

### Billing: Lago (`src/monetization/lago.ts`)

Uses Lago's official SDK, `lago-javascript-client`. Before each generation the
`lagoCreditGate` middleware in `src/sebastina.ts`:

1. finds the customer by their Lago external ID (`SEBASTINA_CUSTOMER_ID`, or asked at start),
2. requires an **active subscription** and an active **wallet** with enough credits
   (`CREDITS_PER_IMAGE` / `CREDITS_PER_VIDEO`, default 1),
3. takes the credits (a "voided credits" wallet transaction), then generates,
4. gives the credits back (as granted credits) if the generation fails.

If Lago can't be reached, generation is refused (no free generations during an outage).
`SEBASTINA_BILLING=off` skips billing, for local testing only.

In Lago: create a plan, subscribe the customer, and give them a wallet with credits.

---

## License

MIT OR Apache-2.0.
