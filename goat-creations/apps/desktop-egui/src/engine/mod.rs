//! The GOAT engine: the document model and the editing pipeline.
//!
//! Nothing in here draws pixels or reads input devices. The UI layer turns
//! mouse and keyboard input into calls on [`Editor`], and reads [`Document`]
//! to render it. That split keeps the engine testable without a window and
//! lets future modules (ImageGOAT, VectorGOAT, MotionGOAT) share one core.
//!
//! egui's small math/color types (`Pos2`, `Rect`, `Color32`) are used as plain
//! value types; no egui UI calls are made from this module.

pub mod document;
pub mod editor;
pub mod history;
pub mod io;
pub mod tools;
pub mod viewport;

pub use document::{Element, ElementId, ElementKind, ShapeKind};
pub use editor::Editor;
pub use tools::Tool;
pub use viewport::Viewport;
