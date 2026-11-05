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

A terminal studio that sends a prompt to an AI backend and reports the result.

```bash
cd goat-creations/sebastina
cp .env.example .env     # set AI_BACKEND_URL
npm install
npm start
```

- **ImageGOAT** posts to `/sdapi/v1/txt2img`, the API of the AUTOMATIC1111 Stable
  Diffusion WebUI (start it with `--api`).
- **MotionGOAT** posts to `/v1/video/generate`. That route is not part of the
  standard WebUI, so it needs a video backend that serves it.

---

## License

MIT OR Apache-2.0.
