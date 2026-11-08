//! Right-hand inspector: module card, tool settings, selection properties,
//! artboard settings and the layer list.

use egui::{Color32, DragValue, RichText, Slider, Ui};

use super::theme::palette;
use super::widgets::{property_row, section_title, swatch_row};
use crate::app::{Action, Module};
use crate::engine::{Editor, ElementId, ElementKind, ShapeKind, Tool};

pub fn show(ui: &mut Ui, editor: &mut Editor, module: Module) -> Vec<Action> {
    let mut actions = Vec::new();

    module_card(ui, module);
    ui.add_space(6.0);
    ui.separator();

    tool_settings(ui, editor);
    ui.separator();

    if editor.selection().is_some() {
        selection_properties(ui, editor, &mut actions);
        ui.separator();
    }

    artboard_settings(ui, editor);
    ui.separator();

    layers(ui, editor);
    actions
}

fn module_card(ui: &mut Ui, module: Module) {
    egui::Frame::new()
        .fill(palette::RAISED)
        .corner_radius(8)
        .inner_margin(10)
        .show(ui, |ui| {
            ui.set_width(ui.available_width());
            ui.horizontal(|ui| {
                ui.label(RichText::new(module.name()).strong().color(palette::ACCENT));
                let (badge, color) = if module.is_available() {
                    ("ACTIVE", palette::SUCCESS)
                } else {
                    ("PLANNED", palette::TEXT_DIM)
                };
                ui.label(RichText::new(badge).small().strong().color(color));
            });
            ui.label(RichText::new(module.tagline()).color(palette::TEXT));
            ui.label(
                RichText::new(module.roadmap())
                    .small()
                    .color(palette::TEXT_DIM),
            );
        });
}

fn tool_settings(ui: &mut Ui, editor: &mut Editor) {
    let tool = editor.tool;
    section_title(ui, &format!("{} tool", tool.label()));
    ui.label(RichText::new(tool.hint()).small().color(palette::TEXT_DIM));

    let s = &mut editor.settings;
    if tool != Tool::Select {
        property_row(ui, "Color", |ui| ui.color_edit_button_srgba(&mut s.color));
        if let Some(c) = swatch_row(ui, s.color) {
            s.color = c;
        }
    }
    match tool {
        Tool::Select => {}
        Tool::Brush => {
            property_row(ui, "Size", |ui| {
                ui.add(
                    Slider::new(&mut s.brush_width, 1.0..=128.0)
                        .logarithmic(true)
                        .suffix(" px"),
                )
            });
        }
        Tool::Vector => {
            property_row(ui, "Shape", |ui| {
                for kind in ShapeKind::ALL {
                    ui.selectable_value(&mut s.shape, kind, kind.label());
                }
            });
            property_row(ui, "Stroke", |ui| {
                ui.add(Slider::new(&mut s.stroke_width, 1.0..=64.0).suffix(" px"))
            });
            property_row(ui, "Fill", |ui| ui.checkbox(&mut s.filled, "Filled"));
        }
        Tool::Text => {
            property_row(ui, "Text", |ui| ui.text_edit_singleline(&mut s.text));
            property_row(ui, "Size", |ui| {
                ui.add(
                    Slider::new(&mut s.font_size, 8.0..=320.0)
                        .logarithmic(true)
                        .suffix(" px"),
                )
            });
        }
    }
}

/// Values copied out of the selected element, so widgets can edit locals and
/// the editor applies each change as an undoable edit.
fn selection_properties(ui: &mut Ui, editor: &mut Editor, actions: &mut Vec<Action>) {
    let Some(el) = editor.selected() else { return };
    let mut name = el.name.clone();
    let mut color = el.color;
    let type_label = el.kind.type_label();

    section_title(ui, &format!("Selection · {type_label}"));

    if property_row(ui, "Name", |ui| ui.text_edit_singleline(&mut name)).changed() {
        editor.edit_selected("name", |e| e.name = name.clone());
    }
    if property_row(ui, "Color", |ui| ui.color_edit_button_srgba(&mut color)).changed() {
        editor.edit_selected("color", |e| e.color = color);
    }
    if let Some(c) = swatch_row(ui, color) {
        editor.edit_selected("color", |e| e.color = c);
    }

    // Kind-specific properties. Read first (immutable), edit after.
    match editor.selected().map(|e| e.kind.clone()) {
        Some(ElementKind::Stroke { mut width, .. }) => {
            if property_row(ui, "Width", |ui| {
                ui.add(
                    Slider::new(&mut width, 1.0..=128.0)
                        .logarithmic(true)
                        .suffix(" px"),
                )
            })
            .changed()
            {
                editor.edit_selected("width", |e| {
                    if let ElementKind::Stroke { width: w, .. } = &mut e.kind {
                        *w = width;
                    }
                });
            }
        }
        Some(ElementKind::Shape {
            mut stroke_width,
            mut filled,
            rect,
            kind,
        }) => {
            ui.label(
                RichText::new(format!(
                    "{} · {:.0} × {:.0} at ({:.0}, {:.0})",
                    kind.label(),
                    rect.width(),
                    rect.height(),
                    rect.min.x,
                    rect.min.y
                ))
                .small()
                .color(palette::TEXT_DIM),
            );
            if property_row(ui, "Stroke", |ui| {
                ui.add(Slider::new(&mut stroke_width, 1.0..=64.0).suffix(" px"))
            })
            .changed()
            {
                editor.edit_selected("stroke_width", |e| {
                    if let ElementKind::Shape {
                        stroke_width: w, ..
                    } = &mut e.kind
                    {
                        *w = stroke_width;
                    }
                });
            }
            if property_row(ui, "Fill", |ui| ui.checkbox(&mut filled, "Filled")).changed() {
                editor.edit_selected("filled", |e| {
                    if let ElementKind::Shape { filled: f, .. } = &mut e.kind {
                        *f = filled;
                    }
                });
            }
        }
        Some(ElementKind::Text {
            mut content,
            mut size,
            ..
        }) => {
            if property_row(ui, "Text", |ui| {
                ui.add(egui::TextEdit::multiline(&mut content).desired_rows(2))
            })
            .changed()
            {
                editor.edit_selected("content", |e| {
                    if let ElementKind::Text {
                        content: c,
                        measured,
                        ..
                    } = &mut e.kind
                    {
                        *c = content.clone();
                        *measured = None;
                    }
                });
            }
            if property_row(ui, "Size", |ui| {
                ui.add(
                    Slider::new(&mut size, 8.0..=320.0)
                        .logarithmic(true)
                        .suffix(" px"),
                )
            })
            .changed()
            {
                editor.edit_selected("size", |e| {
                    if let ElementKind::Text {
                        size: s, measured, ..
                    } = &mut e.kind
                    {
                        *s = size;
                        *measured = None;
                    }
                });
            }
        }
        None => {}
    }

    ui.horizontal(|ui| {
        if ui
            .button("Forward")
            .on_hover_text("Bring forward")
            .clicked()
        {
            actions.push(Action::BringForward);
        }
        if ui
            .button("Backward")
            .on_hover_text("Send backward")
            .clicked()
        {
            actions.push(Action::SendBackward);
        }
        if ui
            .button(RichText::new("Delete").color(palette::DANGER))
            .clicked()
        {
            actions.push(Action::DeleteSelection);
        }
    });
}

fn artboard_settings(ui: &mut Ui, editor: &mut Editor) {
    section_title(ui, "Artboard");
    let (mut w, mut h, mut bg) = (editor.doc.width, editor.doc.height, editor.doc.background);
    let size_changed = property_row(ui, "Size", |ui| {
        let a = ui.add(
            DragValue::new(&mut w)
                .range(16.0..=16384.0)
                .speed(4.0)
                .suffix(" w"),
        );
        let b = ui.add(
            DragValue::new(&mut h)
                .range(16.0..=16384.0)
                .speed(4.0)
                .suffix(" h"),
        );
        a.changed() || b.changed()
    });
    if size_changed {
        editor.edit_document("size", |d| {
            d.width = w;
            d.height = h;
        });
    }
    if property_row(ui, "Background", |ui| ui.color_edit_button_srgba(&mut bg)).changed() {
        editor.edit_document("background", |d| d.background = bg);
    }
}

fn layers(ui: &mut Ui, editor: &mut Editor) {
    section_title(ui, &format!("Layers ({})", editor.doc.elements.len()));
    if editor.doc.is_empty() {
        ui.label(
            RichText::new("Nothing here yet. Pick a tool and start creating.")
                .small()
                .color(palette::TEXT_DIM),
        );
        return;
    }

    // Collect clicks first, apply after the loop (the list borrows the doc).
    let mut clicked: Option<ElementId> = None;
    let mut toggled: Option<(ElementId, bool)> = None;
    let selected = editor.selection();

    for el in editor.doc.elements.iter().rev() {
        ui.horizontal(|ui| {
            let mut visible = el.visible;
            if ui
                .checkbox(&mut visible, "")
                .on_hover_text(if visible { "Hide" } else { "Show" })
                .changed()
            {
                toggled = Some((el.id, visible));
            }
            let (r, g, b, _) = el.color.to_tuple();
            let (dot, _) = ui.allocate_exact_size(egui::vec2(10.0, 10.0), egui::Sense::hover());
            ui.painter()
                .circle_filled(dot.center(), 4.5, Color32::from_rgb(r, g, b));
            let text = if el.visible {
                RichText::new(&el.name)
            } else {
                RichText::new(&el.name).color(palette::TEXT_DIM).italics()
            };
            // `right_text("")` adds a stretchy spacer, which left-aligns the name.
            let row = ui.add(
                egui::Button::selectable(selected == Some(el.id), text)
                    .right_text("")
                    .min_size(egui::vec2(ui.available_width(), 22.0)),
            );
            if row.clicked() {
                clicked = Some(el.id);
            }
        });
    }

    if let Some((id, visible)) = toggled {
        editor.set_visible(id, visible);
    }
    if let Some(id) = clicked {
        editor.select(Some(id));
    }
}
