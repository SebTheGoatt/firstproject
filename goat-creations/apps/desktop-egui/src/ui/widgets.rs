//! Small shared widgets used by several panels.

use egui::{Align2, Color32, CornerRadius, FontId, Rect, RichText, Sense, Stroke, Ui, Vec2};

use super::theme::palette;

/// The brand mark: a gold rounded square with a "G". `size` is the side length.
pub fn logo_mark(ui: &mut Ui, size: f32) -> egui::Response {
    let (rect, response) = ui.allocate_exact_size(Vec2::splat(size), Sense::hover());
    paint_logo_mark(ui.painter(), rect);
    response
}

/// Paint the brand mark into `rect` (also used on the empty canvas).
pub fn paint_logo_mark(painter: &egui::Painter, rect: Rect) {
    let radius = CornerRadius::same((rect.width() * 0.24).round().clamp(0.0, 255.0) as u8);
    painter.rect_filled(rect, radius, palette::ACCENT);
    painter.text(
        rect.center(),
        Align2::CENTER_CENTER,
        "G",
        FontId::proportional(rect.height() * 0.72),
        palette::CANVAS_BG,
    );
}

/// Uppercase, letter-spaced section title used in the inspector.
pub fn section_title(ui: &mut Ui, title: &str) {
    ui.add_space(4.0);
    ui.label(
        RichText::new(title.to_uppercase())
            .small()
            .strong()
            .color(palette::TEXT_DIM),
    );
}

/// A row of quick color swatches. Returns the swatch the user clicked.
pub fn swatch_row(ui: &mut Ui, current: Color32) -> Option<Color32> {
    let mut picked = None;
    ui.horizontal_wrapped(|ui| {
        ui.spacing_mut().item_spacing = Vec2::splat(4.0);
        for color in palette::SWATCHES {
            let (rect, response) = ui.allocate_exact_size(Vec2::splat(18.0), Sense::click());
            let selected = color == current;
            let stroke = if selected {
                Stroke::new(2.0, palette::TEXT)
            } else if response.hovered() {
                Stroke::new(1.0, palette::TEXT_DIM)
            } else {
                Stroke::new(1.0, palette::BORDER)
            };
            ui.painter().rect_filled(rect, CornerRadius::same(4), color);
            ui.painter().rect_stroke(
                rect,
                CornerRadius::same(4),
                stroke,
                egui::StrokeKind::Inside,
            );
            let hex = format!("#{:02X}{:02X}{:02X}", color.r(), color.g(), color.b());
            if response.on_hover_text(hex).clicked() {
                picked = Some(color);
            }
        }
    });
    picked
}

/// A label on the left and a widget on the right, for property rows.
pub fn property_row<R>(ui: &mut Ui, label: &str, add: impl FnOnce(&mut Ui) -> R) -> R {
    ui.horizontal(|ui| {
        // Fixed-width, left-aligned label column so rows line up.
        ui.allocate_ui_with_layout(
            Vec2::new(80.0, 20.0),
            egui::Layout::left_to_right(egui::Align::Center),
            |ui| {
                ui.set_min_width(80.0);
                ui.label(RichText::new(label).color(palette::TEXT_DIM));
            },
        );
        add(ui)
    })
    .inner
}
