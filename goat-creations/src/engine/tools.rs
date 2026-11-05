//! Tools and their settings.

use egui::Color32;

use super::document::ShapeKind;

/// The active tool decides what a press-drag-release on the canvas does.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Default)]
pub enum Tool {
    /// Pick and move elements.
    #[default]
    Select,
    /// Paint freehand strokes.
    Brush,
    /// Draw vector shapes (rectangle, ellipse).
    Vector,
    /// Place text.
    Text,
}

impl Tool {
    pub const ALL: [Tool; 4] = [Tool::Select, Tool::Brush, Tool::Vector, Tool::Text];

    pub fn label(self) -> &'static str {
        match self {
            Tool::Select => "Select",
            Tool::Brush => "Brush",
            Tool::Vector => "Vector",
            Tool::Text => "Text",
        }
    }

    /// Single-key shortcut, shown in tooltips and menus.
    pub fn shortcut(self) -> egui::Key {
        match self {
            Tool::Select => egui::Key::V,
            Tool::Brush => egui::Key::B,
            Tool::Vector => egui::Key::P,
            Tool::Text => egui::Key::T,
        }
    }

    /// One-line usage hint for tooltips and the inspector.
    pub fn hint(self) -> &'static str {
        match self {
            Tool::Select => "Click to select, drag to move. Delete removes.",
            Tool::Brush => "Drag to paint a freehand stroke.",
            Tool::Vector => "Drag to draw a shape. Hold Shift for a square or circle.",
            Tool::Text => "Click on the artboard to place text.",
        }
    }
}

/// Settings applied to newly created elements.
#[derive(Clone, Debug)]
pub struct ToolSettings {
    pub color: Color32,
    pub brush_width: f32,
    pub shape: ShapeKind,
    pub stroke_width: f32,
    pub filled: bool,
    pub text: String,
    pub font_size: f32,
}

impl Default for ToolSettings {
    fn default() -> Self {
        Self {
            color: crate::ui::theme::palette::ACCENT,
            brush_width: 8.0,
            shape: ShapeKind::Rectangle,
            stroke_width: 4.0,
            filled: false,
            text: "GOAT".to_owned(),
            font_size: 96.0,
        }
    }
}
