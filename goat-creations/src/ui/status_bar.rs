//! Bottom status bar: tool, cursor position, zoom, element count, messages.

use egui::{Align, Layout, Pos2, RichText, Ui};

use super::theme::palette;
use crate::app::Module;
use crate::engine::Tool;

pub struct StatusInfo<'a> {
    pub tool: Tool,
    pub module: Module,
    pub cursor: Option<Pos2>,
    pub zoom: f32,
    pub elements: usize,
    pub modified: bool,
    /// Transient message and whether it is an error.
    pub notice: Option<(&'a str, bool)>,
}

pub fn show(ui: &mut Ui, info: &StatusInfo<'_>) {
    let dim = |s: String| RichText::new(s).small().color(palette::TEXT_DIM);

    ui.horizontal(|ui| {
        ui.label(
            RichText::new(info.module.name())
                .small()
                .strong()
                .color(palette::ACCENT),
        );
        ui.separator();
        ui.label(dim(format!("{} · {}", info.tool.label(), info.tool.hint())));

        ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
            ui.label(dim(format!("{:.0}%", info.zoom * 100.0)));
            ui.separator();
            let pos = info
                .cursor
                .map(|p| format!("X {:.0}  Y {:.0}", p.x, p.y))
                .unwrap_or_else(|| "X –  Y –".to_owned());
            ui.label(dim(pos));
            ui.separator();
            ui.label(dim(format!(
                "{} element{}",
                info.elements,
                if info.elements == 1 { "" } else { "s" }
            )));
            if info.modified {
                ui.separator();
                ui.label(RichText::new("● Unsaved").small().color(palette::ACCENT));
            }
            if let Some((text, is_error)) = info.notice {
                ui.separator();
                let color = if is_error {
                    palette::DANGER
                } else {
                    palette::SUCCESS
                };
                ui.label(RichText::new(text).small().color(color));
            }
        });
    });
}
