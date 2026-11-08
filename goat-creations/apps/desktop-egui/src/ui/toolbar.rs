//! Left-hand toolbar: Select, Brush, Vector, Text, with icons drawn in code
//! (crisp at any DPI, no image assets to ship).

use egui::{
    epaint::CubicBezierShape, pos2, vec2, Color32, CornerRadius, Painter, Pos2, Rect, Sense, Shape,
    Stroke, Ui,
};

use super::theme::palette;
use crate::app::Action;
use crate::engine::Tool;

const BUTTON: f32 = 40.0;

pub fn show(ui: &mut Ui, current: Tool, color: Color32) -> Vec<Action> {
    let mut actions = Vec::new();

    ui.vertical_centered(|ui| {
        ui.spacing_mut().item_spacing.y = 6.0;
        for tool in Tool::ALL {
            if tool_button(ui, tool, tool == current).clicked() {
                actions.push(Action::SetTool(tool));
            }
        }

        // Current color, as a reminder of what the next mark will look like.
        ui.add_space(10.0);
        let (rect, response) = ui.allocate_exact_size(vec2(28.0, 28.0), Sense::hover());
        ui.painter()
            .rect_filled(rect, CornerRadius::same(14), color);
        ui.painter().rect_stroke(
            rect,
            CornerRadius::same(14),
            Stroke::new(2.0, palette::BORDER),
            egui::StrokeKind::Outside,
        );
        response.on_hover_text("Current color (change it in the inspector)");
    });

    actions
}

fn tool_button(ui: &mut Ui, tool: Tool, selected: bool) -> egui::Response {
    let (rect, response) = ui.allocate_exact_size(vec2(BUTTON, BUTTON), Sense::click());
    response.widget_info(|| {
        egui::WidgetInfo::selected(egui::Role::Button, true, selected, tool.label())
    });

    let painter = ui.painter();
    let (bg, fg) = if selected {
        (palette::ACCENT_SOFT, palette::ACCENT)
    } else if response.hovered() {
        (palette::HOVER, palette::TEXT)
    } else {
        (Color32::TRANSPARENT, palette::TEXT_DIM)
    };
    painter.rect_filled(rect, CornerRadius::same(8), bg);
    if selected {
        // Small gold notch on the left edge marks the active tool.
        let notch = Rect::from_min_size(
            pos2(rect.left() - 8.0, rect.center().y - 8.0),
            vec2(3.0, 16.0),
        );
        painter.rect_filled(notch, CornerRadius::same(2), palette::ACCENT);
    }
    paint_icon(painter, rect.center(), tool, fg);

    response.on_hover_text(format!(
        "{}  ({})\n{}",
        tool.label(),
        tool.shortcut().name(),
        tool.hint()
    ))
}

/// Draw `tool`'s icon centered on `c` in a roughly 20x20 box.
fn paint_icon(painter: &Painter, c: Pos2, tool: Tool, color: Color32) {
    let stroke = Stroke::new(1.6, color);
    let p = |x: f32, y: f32| c + vec2(x, y);
    match tool {
        Tool::Select => {
            // Pointer arrow.
            let arrow = vec![
                p(-5.0, -8.0),
                p(-5.0, 6.0),
                p(-1.5, 2.5),
                p(1.5, 8.5),
                p(4.0, 7.3),
                p(1.0, 1.5),
                p(6.0, 1.5),
            ];
            painter.add(Shape::closed_line(arrow, stroke));
        }
        Tool::Brush => {
            // Handle and a round bristle tip.
            painter.line_segment([p(7.0, -8.0), p(-0.5, 0.5)], Stroke::new(2.4, color));
            painter.circle_filled(p(-3.5, 4.0), 3.6, color);
            painter.line_segment([p(-7.5, 8.0), p(-5.0, 6.5)], Stroke::new(1.8, color));
        }
        Tool::Vector => {
            // A bezier curve between two anchor nodes.
            let curve = CubicBezierShape::from_points_stroke(
                [p(-7.0, 6.0), p(-5.0, -10.0), p(5.0, 10.0), p(7.0, -6.0)],
                false,
                Color32::TRANSPARENT,
                stroke,
            );
            painter.add(curve);
            for node in [p(-7.0, 6.0), p(7.0, -6.0)] {
                let r = Rect::from_center_size(node, vec2(4.5, 4.5));
                painter.rect_filled(r, CornerRadius::ZERO, palette::PANEL);
                painter.rect_stroke(r, CornerRadius::ZERO, stroke, egui::StrokeKind::Middle);
            }
        }
        Tool::Text => {
            // A serif-less "T".
            let thick = Stroke::new(2.2, color);
            painter.line_segment([p(-7.0, -7.0), p(7.0, -7.0)], thick);
            painter.line_segment([p(0.0, -7.0), p(0.0, 8.0)], thick);
            painter.line_segment([p(-3.0, 8.0), p(3.0, 8.0)], stroke);
        }
    }
}
