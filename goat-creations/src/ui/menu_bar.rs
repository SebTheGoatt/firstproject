//! Top menu bar: brand mark, "File", "Edit", "GOAT Tools" and the module switcher.

use egui::{Align, Button, Layout, RichText, Ui};

use super::theme::palette;
use super::widgets;
use crate::app::{shortcuts, Action, Module};
use crate::engine::Tool;

/// What the menus need to know to enable/disable and check their items.
pub struct MenuState {
    pub can_undo: bool,
    pub can_redo: bool,
    pub has_selection: bool,
    pub has_elements: bool,
    pub tool: Tool,
    pub module: Module,
    pub show_grid: bool,
}

pub fn show(ui: &mut Ui, state: &MenuState) -> Vec<Action> {
    let mut actions = Vec::new();

    egui::MenuBar::new().ui(ui, |ui| {
        // Brand.
        widgets::logo_mark(ui, 20.0);
        ui.label(
            RichText::new("GOAT CREATIONS")
                .strong()
                .color(palette::TEXT),
        );
        ui.add_space(8.0);

        ui.menu_button("File", |ui| file_menu(ui, &mut actions));
        ui.menu_button("Edit", |ui| edit_menu(ui, state, &mut actions));
        ui.menu_button("GOAT Tools", |ui| goat_tools_menu(ui, state, &mut actions));

        // Module switcher, right-aligned.
        ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
            for module in Module::ALL.iter().rev() {
                let selected = *module == state.module;
                let mut text = RichText::new(module.name());
                if selected {
                    text = text.color(palette::ACCENT).strong();
                } else if !module.is_available() {
                    text = text.color(palette::TEXT_DIM);
                }
                let tip = if module.is_available() {
                    module.tagline().to_owned()
                } else {
                    format!("{} (planned)", module.tagline())
                };
                if ui
                    .selectable_label(selected, text)
                    .on_hover_text(tip)
                    .clicked()
                {
                    actions.push(Action::SetModule(*module));
                }
            }
        });
    });

    actions
}

/// A menu item with a shortcut hint. Pushes `action` when clicked.
fn item(
    ui: &mut Ui,
    label: &str,
    shortcut: Option<&egui::KeyboardShortcut>,
    enabled: bool,
    action: Action,
    out: &mut Vec<Action>,
) {
    let mut button = Button::new(label);
    if let Some(sc) = shortcut {
        button = button.shortcut_text(ui.ctx().format_shortcut(sc));
    }
    if ui.add_enabled(enabled, button).clicked() {
        out.push(action);
    }
}

fn file_menu(ui: &mut Ui, out: &mut Vec<Action>) {
    item(
        ui,
        "New project",
        Some(&shortcuts::NEW),
        true,
        Action::NewProject,
        out,
    );
    item(
        ui,
        "Open…",
        Some(&shortcuts::OPEN),
        true,
        Action::OpenProject,
        out,
    );
    ui.separator();
    item(
        ui,
        "Save",
        Some(&shortcuts::SAVE),
        true,
        Action::SaveProject,
        out,
    );
    item(
        ui,
        "Save as…",
        Some(&shortcuts::SAVE_AS),
        true,
        Action::SaveProjectAs,
        out,
    );
    ui.separator();
    ui.add_enabled(false, Button::new("Export image…"))
        .on_disabled_hover_text("PNG/JPEG export arrives with ImageGOAT.");
    ui.separator();
    item(ui, "Quit", Some(&shortcuts::QUIT), true, Action::Quit, out);
}

fn edit_menu(ui: &mut Ui, s: &MenuState, out: &mut Vec<Action>) {
    item(
        ui,
        "Undo",
        Some(&shortcuts::UNDO),
        s.can_undo,
        Action::Undo,
        out,
    );
    item(
        ui,
        "Redo",
        Some(&shortcuts::REDO),
        s.can_redo,
        Action::Redo,
        out,
    );
    ui.separator();
    let del = egui::KeyboardShortcut::new(egui::Modifiers::NONE, egui::Key::Delete);
    let esc = egui::KeyboardShortcut::new(egui::Modifiers::NONE, egui::Key::Escape);
    item(
        ui,
        "Delete",
        Some(&del),
        s.has_selection,
        Action::DeleteSelection,
        out,
    );
    item(
        ui,
        "Deselect",
        Some(&esc),
        s.has_selection,
        Action::Deselect,
        out,
    );
    ui.separator();
    item(
        ui,
        "Bring forward",
        None,
        s.has_selection,
        Action::BringForward,
        out,
    );
    item(
        ui,
        "Send backward",
        None,
        s.has_selection,
        Action::SendBackward,
        out,
    );
    ui.separator();
    item(
        ui,
        "Clear canvas",
        None,
        s.has_elements,
        Action::ClearCanvas,
        out,
    );
}

fn goat_tools_menu(ui: &mut Ui, s: &MenuState, out: &mut Vec<Action>) {
    for tool in Tool::ALL {
        let sc = egui::KeyboardShortcut::new(egui::Modifiers::NONE, tool.shortcut());
        let button = Button::selectable(s.tool == tool, tool.label())
            .shortcut_text(ui.ctx().format_shortcut(&sc));
        if ui.add(button).clicked() {
            out.push(Action::SetTool(tool));
        }
    }
    ui.separator();
    ui.menu_button("Modules", |ui| {
        for module in Module::ALL {
            let label = if module.is_available() {
                module.name().to_owned()
            } else {
                format!("{}  (planned)", module.name())
            };
            if ui
                .add(Button::selectable(s.module == module, label))
                .on_hover_text(module.roadmap())
                .clicked()
            {
                out.push(Action::SetModule(module));
            }
        }
    });
    ui.separator();
    if ui
        .add(Button::selectable(s.show_grid, "Show grid"))
        .clicked()
    {
        out.push(Action::ToggleGrid);
    }
    item(
        ui,
        "Zoom in",
        Some(&shortcuts::ZOOM_IN),
        true,
        Action::ZoomIn,
        out,
    );
    item(
        ui,
        "Zoom out",
        Some(&shortcuts::ZOOM_OUT),
        true,
        Action::ZoomOut,
        out,
    );
    item(
        ui,
        "Fit artboard",
        Some(&shortcuts::RESET_VIEW),
        true,
        Action::ResetView,
        out,
    );
    ui.separator();
    item(
        ui,
        "About GOAT CREATIONS",
        None,
        true,
        Action::ShowAbout,
        out,
    );
}
