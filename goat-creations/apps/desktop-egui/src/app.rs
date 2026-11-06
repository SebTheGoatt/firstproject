//! Application state, event routing and the per-frame UI loop.
//!
//! Every frame:
//! 1. global keyboard shortcuts become [`Action`]s,
//! 2. each panel draws itself and may add more actions,
//! 3. all actions are dispatched here, in one place, in order.
//!
//! Direct manipulation on the canvas (painting, dragging) goes straight to
//! the [`Editor`]; everything that is a *command* goes through [`Action`].

use std::path::PathBuf;
use std::time::Duration;

use egui::{
    Align, Color32, Frame, Key, Layout, Margin, Modifiers, Pos2, Rect, RichText, ViewportCommand,
};

use crate::engine::{io, Editor, Tool, Viewport};
use crate::ui::{self, theme::palette};
use crate::APP_NAME;

/// The suite's modules. VectorGOAT is the active workspace in this MVP;
/// the others are planned and share the same engine and shell.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Module {
    Image,
    Vector,
    Motion,
}

impl Module {
    pub const ALL: [Module; 3] = [Module::Image, Module::Vector, Module::Motion];

    pub fn name(self) -> &'static str {
        match self {
            Module::Image => "ImageGOAT",
            Module::Vector => "VectorGOAT",
            Module::Motion => "MotionGOAT",
        }
    }

    pub fn tagline(self) -> &'static str {
        match self {
            Module::Image => "Raster & photo editing",
            Module::Vector => "Vector & illustration design",
            Module::Motion => "Video & animation",
        }
    }

    /// What exists today vs. what is planned, shown honestly in the UI.
    pub fn is_available(self) -> bool {
        matches!(self, Module::Vector)
    }

    pub fn roadmap(self) -> &'static str {
        match self {
            Module::Image => "Planned: pixel layers, brushes with pressure, filters, adjustments, PNG/JPEG export.",
            Module::Vector => "Active: brush strokes, rectangles, ellipses, text, layers, undo/redo, project files.",
            Module::Motion => "Planned: timeline, keyframes on any property, onion skin, video export.",
        }
    }
}

/// A command from the menu bar, toolbar, inspector or keyboard.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Action {
    NewProject,
    OpenProject,
    SaveProject,
    SaveProjectAs,
    Quit,
    Undo,
    Redo,
    DeleteSelection,
    Deselect,
    ClearCanvas,
    BringForward,
    SendBackward,
    SetTool(Tool),
    SetModule(Module),
    ToggleGrid,
    ResetView,
    ZoomIn,
    ZoomOut,
    ShowAbout,
}

/// Keyboard shortcuts. `COMMAND` is Ctrl on Windows/Linux and Cmd on macOS.
pub mod shortcuts {
    use egui::{Key, KeyboardShortcut, Modifiers};

    const CMD: Modifiers = Modifiers::COMMAND;
    const CMD_SHIFT: Modifiers = Modifiers::COMMAND.plus(Modifiers::SHIFT);

    pub const NEW: KeyboardShortcut = KeyboardShortcut::new(CMD, Key::N);
    pub const OPEN: KeyboardShortcut = KeyboardShortcut::new(CMD, Key::O);
    pub const SAVE: KeyboardShortcut = KeyboardShortcut::new(CMD, Key::S);
    pub const SAVE_AS: KeyboardShortcut = KeyboardShortcut::new(CMD_SHIFT, Key::S);
    pub const QUIT: KeyboardShortcut = KeyboardShortcut::new(CMD, Key::Q);
    pub const UNDO: KeyboardShortcut = KeyboardShortcut::new(CMD, Key::Z);
    pub const REDO: KeyboardShortcut = KeyboardShortcut::new(CMD_SHIFT, Key::Z);
    pub const REDO_ALT: KeyboardShortcut = KeyboardShortcut::new(CMD, Key::Y);
    pub const RESET_VIEW: KeyboardShortcut = KeyboardShortcut::new(CMD, Key::Num0);
    pub const ZOOM_IN: KeyboardShortcut = KeyboardShortcut::new(CMD, Key::Equals);
    pub const ZOOM_OUT: KeyboardShortcut = KeyboardShortcut::new(CMD, Key::Minus);
}

/// Open / save path prompt.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum FileMode {
    Open,
    Save,
}

struct FileDialog {
    mode: FileMode,
    path: String,
    /// Focus the path field once, when the dialog opens.
    focus_pending: bool,
}

/// A transient message in the status bar.
struct Notice {
    text: String,
    is_error: bool,
    shown_at: f64,
}

const NOTICE_SECONDS: f64 = 4.0;
const DEFAULT_PROJECT: &str = "untitled.goat.json";

pub struct GoatApp {
    editor: Editor,
    view: Viewport,
    module: Module,
    show_grid: bool,
    show_about: bool,
    file_dialog: Option<FileDialog>,
    /// An action waiting for "discard unsaved changes?" confirmation.
    confirm: Option<Action>,
    /// Set once the user agreed to quit with unsaved changes.
    allow_close: bool,
    project_path: Option<PathBuf>,
    notice: Option<Notice>,
    cursor_world: Option<Pos2>,
    canvas_rect: Rect,
    window_title: String,
}

impl GoatApp {
    pub fn new(cc: &eframe::CreationContext<'_>) -> Self {
        ui::theme::apply(&cc.egui_ctx);
        Self {
            editor: Editor::default(),
            view: Viewport::default(),
            module: Module::Vector,
            show_grid: true,
            show_about: false,
            file_dialog: None,
            confirm: None,
            allow_close: false,
            project_path: None,
            notice: None,
            cursor_world: None,
            canvas_rect: Rect::NOTHING,
            window_title: String::new(),
        }
    }

    /// Short name of the open project, for the title and status bar.
    fn project_name(&self) -> String {
        self.project_path
            .as_ref()
            .and_then(|p| p.file_name())
            .map(|n| n.to_string_lossy().into_owned())
            .unwrap_or_else(|| "Untitled".to_owned())
    }

    fn notify(&mut self, ctx: &egui::Context, text: impl Into<String>, is_error: bool) {
        self.notice = Some(Notice {
            text: text.into(),
            is_error,
            shown_at: ctx.input(|i| i.time),
        });
        // Wake up again to clear the message even if the user is idle.
        ctx.request_repaint_after(Duration::from_secs_f64(NOTICE_SECONDS));
    }

    // ------------------------------------------------------------ input

    /// Turn global keyboard shortcuts into actions.
    fn collect_shortcuts(&mut self, ctx: &egui::Context, actions: &mut Vec<Action>) {
        // While a text field has focus, plain keys and undo belong to it.
        let typing = ctx.egui_wants_keyboard_input();

        ctx.input_mut(|i| {
            use shortcuts::*;
            // Shift variants first: shortcut matching ignores extra Shift.
            if i.consume_shortcut(&SAVE_AS) {
                actions.push(Action::SaveProjectAs);
            }
            if i.consume_shortcut(&SAVE) {
                actions.push(Action::SaveProject);
            }
            if i.consume_shortcut(&NEW) {
                actions.push(Action::NewProject);
            }
            if i.consume_shortcut(&OPEN) {
                actions.push(Action::OpenProject);
            }
            if i.consume_shortcut(&QUIT) {
                actions.push(Action::Quit);
            }
            if i.consume_shortcut(&RESET_VIEW) {
                actions.push(Action::ResetView);
            }
            if i.consume_shortcut(&ZOOM_IN) {
                actions.push(Action::ZoomIn);
            }
            if i.consume_shortcut(&ZOOM_OUT) {
                actions.push(Action::ZoomOut);
            }
            if typing {
                return;
            }
            if i.consume_shortcut(&REDO) || i.consume_shortcut(&REDO_ALT) {
                actions.push(Action::Redo);
            }
            if i.consume_shortcut(&UNDO) {
                actions.push(Action::Undo);
            }
            if i.consume_key(Modifiers::NONE, Key::Delete)
                || i.consume_key(Modifiers::NONE, Key::Backspace)
            {
                actions.push(Action::DeleteSelection);
            }
            if i.consume_key(Modifiers::NONE, Key::Escape) {
                actions.push(Action::Deselect);
            }
            for tool in Tool::ALL {
                if i.consume_key(Modifiers::NONE, tool.shortcut()) {
                    actions.push(Action::SetTool(tool));
                }
            }
        });
    }

    // ------------------------------------------------------------ routing

    /// Run an action, asking first if it would throw away unsaved work.
    fn dispatch(&mut self, ctx: &egui::Context, action: Action) {
        let destructive = matches!(
            action,
            Action::NewProject | Action::OpenProject | Action::Quit
        );
        if destructive && self.editor.is_modified() {
            self.confirm = Some(action);
            return;
        }
        self.execute(ctx, action);
    }

    fn execute(&mut self, ctx: &egui::Context, action: Action) {
        match action {
            Action::NewProject => {
                self.editor.new_document();
                self.project_path = None;
                self.view.needs_fit = true;
                self.notify(ctx, "New project", false);
            }
            Action::OpenProject => self.open_file_dialog(FileMode::Open),
            Action::SaveProject => match self.project_path.clone() {
                Some(path) => self.save_to(ctx, path),
                None => self.open_file_dialog(FileMode::Save),
            },
            Action::SaveProjectAs => self.open_file_dialog(FileMode::Save),
            Action::Quit => {
                self.allow_close = true;
                ctx.send_viewport_cmd(ViewportCommand::Close);
            }
            Action::Undo => {
                if !self.editor.undo() {
                    self.notify(ctx, "Nothing to undo", false);
                }
            }
            Action::Redo => {
                if !self.editor.redo() {
                    self.notify(ctx, "Nothing to redo", false);
                }
            }
            Action::DeleteSelection => {
                self.editor.delete_selection();
            }
            Action::Deselect => self.editor.select(None),
            Action::ClearCanvas => self.editor.clear_canvas(),
            Action::BringForward => {
                self.editor.bring_forward();
            }
            Action::SendBackward => {
                self.editor.send_backward();
            }
            Action::SetTool(tool) => self.editor.set_tool(tool),
            Action::SetModule(module) => {
                self.module = module;
                if !module.is_available() {
                    self.notify(
                        ctx,
                        format!(
                            "{} is on the roadmap. The vector workspace stays active meanwhile.",
                            module.name()
                        ),
                        false,
                    );
                }
            }
            Action::ToggleGrid => self.show_grid = !self.show_grid,
            Action::ResetView => self.view.needs_fit = true,
            Action::ZoomIn | Action::ZoomOut => {
                if self.canvas_rect.is_positive() {
                    let factor = if action == Action::ZoomIn { 1.25 } else { 0.8 };
                    self.view
                        .zoom_around(self.canvas_rect.center(), self.canvas_rect.min, factor);
                }
            }
            Action::ShowAbout => self.show_about = true,
        }
    }

    // ------------------------------------------------------------ files

    fn open_file_dialog(&mut self, mode: FileMode) {
        let path = self
            .project_path
            .as_ref()
            .map(|p| p.display().to_string())
            .unwrap_or_else(|| DEFAULT_PROJECT.to_owned());
        self.file_dialog = Some(FileDialog {
            mode,
            path,
            focus_pending: true,
        });
    }

    fn save_to(&mut self, ctx: &egui::Context, path: PathBuf) {
        match io::save(&self.editor.doc, &path) {
            Ok(()) => {
                self.editor.mark_saved();
                self.notify(ctx, format!("Saved {}", path.display()), false);
                self.project_path = Some(path);
            }
            Err(e) => self.notify(ctx, format!("Could not save {}: {e}", path.display()), true),
        }
    }

    fn open_from(&mut self, ctx: &egui::Context, path: PathBuf) {
        match io::load(&path) {
            Ok(doc) => {
                self.editor.replace_document(doc);
                self.view.needs_fit = true;
                self.notify(ctx, format!("Opened {}", path.display()), false);
                self.project_path = Some(path);
            }
            Err(e) => self.notify(ctx, format!("Could not open {}: {e}", path.display()), true),
        }
    }

    // ------------------------------------------------------------ dialogs

    fn show_dialogs(&mut self, ctx: &egui::Context) {
        self.show_file_dialog(ctx);
        self.show_confirm_dialog(ctx);
        self.show_about_window(ctx);
    }

    fn show_file_dialog(&mut self, ctx: &egui::Context) {
        let Some(dialog) = &mut self.file_dialog else {
            return;
        };
        let mode = dialog.mode;
        let mut submit = false;
        let mut cancel = false;

        let modal = egui::Modal::new(egui::Id::unique("goat_file_dialog")).show(ctx, |ui| {
            ui.set_width(420.0);
            ui.heading(if mode == FileMode::Open { "Open project" } else { "Save project" });
            ui.label(
                RichText::new("Project files are JSON (.goat.json). Paths are relative to the folder you ran the app from.")
                    .color(palette::TEXT_DIM),
            );
            ui.add_space(6.0);
            let edit = ui.add(
                egui::TextEdit::singleline(&mut dialog.path)
                    .desired_width(f32::INFINITY)
                    .hint_text(DEFAULT_PROJECT),
            );
            if std::mem::take(&mut dialog.focus_pending) {
                edit.request_focus();
            }
            if ui.input(|i| i.key_pressed(Key::Enter)) {
                submit = true;
            }
            ui.add_space(8.0);
            ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                let label = if mode == FileMode::Open { "Open" } else { "Save" };
                if ui.add(egui::Button::new(RichText::new(label).color(palette::CANVAS_BG)).fill(palette::ACCENT)).clicked() {
                    submit = true;
                }
                if ui.button("Cancel").clicked() {
                    cancel = true;
                }
            });
        });
        if modal.should_close() {
            cancel = true;
        }

        if submit {
            let path = dialog.path.trim().to_owned();
            if path.is_empty() {
                return;
            }
            self.file_dialog = None;
            let path = PathBuf::from(path);
            match mode {
                FileMode::Open => self.open_from(ctx, path),
                FileMode::Save => self.save_to(ctx, path),
            }
        } else if cancel {
            self.file_dialog = None;
        }
    }

    fn show_confirm_dialog(&mut self, ctx: &egui::Context) {
        let Some(action) = self.confirm else { return };
        let mut decision: Option<bool> = None;

        let modal = egui::Modal::new(egui::Id::unique("goat_confirm")).show(ctx, |ui| {
            ui.set_width(360.0);
            ui.heading("Discard unsaved changes?");
            ui.label(
                RichText::new(format!(
                    "\"{}\" has changes that are not saved.",
                    self.project_name()
                ))
                .color(palette::TEXT_DIM),
            );
            ui.add_space(8.0);
            ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                if ui
                    .add(
                        egui::Button::new(RichText::new("Discard").color(Color32::WHITE))
                            .fill(palette::DANGER),
                    )
                    .clicked()
                {
                    decision = Some(true);
                }
                if ui.button("Keep editing").clicked() {
                    decision = Some(false);
                }
            });
        });
        if modal.should_close() && decision.is_none() {
            decision = Some(false);
        }

        match decision {
            Some(true) => {
                self.confirm = None;
                self.execute(ctx, action);
            }
            Some(false) => self.confirm = None,
            None => {}
        }
    }

    fn show_about_window(&mut self, ctx: &egui::Context) {
        egui::Window::new("About GOAT CREATIONS")
            .open(&mut self.show_about)
            .collapsible(false)
            .resizable(false)
            .anchor(egui::Align2::CENTER_CENTER, [0.0, 0.0])
            .show(ctx, |ui| {
                ui.horizontal(|ui| {
                    ui::widgets::logo_mark(ui, 40.0);
                    ui.vertical(|ui| {
                        ui.label(
                            RichText::new(APP_NAME)
                                .heading()
                                .strong()
                                .color(palette::TEXT),
                        );
                        ui.label(
                            RichText::new("The Greatest of All Time Open-Source Creative Suite")
                                .color(palette::ACCENT),
                        );
                    });
                });
                ui.add_space(8.0);
                ui.label(format!("Version {}", env!("CARGO_PKG_VERSION")));
                ui.add_space(4.0);
                for module in Module::ALL {
                    ui.label(RichText::new(module.name()).strong());
                    ui.label(RichText::new(module.roadmap()).color(palette::TEXT_DIM));
                }
                ui.add_space(6.0);
                ui.label(
                    RichText::new("Built in Rust with egui. Licensed MIT OR Apache-2.0.")
                        .small()
                        .color(palette::TEXT_DIM),
                );
            });
    }

    /// Keep the OS window title in sync ("name* - GOAT CREATIONS").
    fn sync_window_title(&mut self, ctx: &egui::Context) {
        let dirty = if self.editor.is_modified() { "*" } else { "" };
        let title = format!(
            "{}{} - {} · {}",
            self.project_name(),
            dirty,
            APP_NAME,
            self.module.name()
        );
        if title != self.window_title {
            ctx.send_viewport_cmd(ViewportCommand::Title(title.clone()));
            self.window_title = title;
        }
    }

    /// Intercept the window close button when there is unsaved work.
    fn guard_close(&mut self, ctx: &egui::Context) {
        if ctx.input(|i| i.viewport().close_requested())
            && self.editor.is_modified()
            && !self.allow_close
        {
            ctx.send_viewport_cmd(ViewportCommand::CancelClose);
            self.confirm = Some(Action::Quit);
        }
    }
}

impl eframe::App for GoatApp {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        // The Context is a cheap handle (Arc); clone it so panels can borrow `ui`.
        let ctx = &ui.ctx().clone();
        self.guard_close(ctx);

        let mut actions = Vec::new();
        let modal_open = self.file_dialog.is_some() || self.confirm.is_some();
        if !modal_open {
            self.collect_shortcuts(ctx, &mut actions);
        }

        // --- Top: brand + menus + module switcher -------------------------
        egui::Panel::top("goat_menu_bar")
            .frame(
                Frame::new()
                    .fill(palette::PANEL)
                    .inner_margin(Margin::symmetric(10, 6)),
            )
            .show(ui, |ui| {
                let state = ui::menu_bar::MenuState {
                    can_undo: self.editor.history.can_undo(),
                    can_redo: self.editor.history.can_redo(),
                    has_selection: self.editor.selection().is_some(),
                    has_elements: !self.editor.doc.is_empty(),
                    tool: self.editor.tool,
                    module: self.module,
                    show_grid: self.show_grid,
                };
                actions.extend(ui::menu_bar::show(ui, &state));
            });

        // --- Bottom: status bar ------------------------------------------
        let now = ctx.input(|i| i.time);
        if self
            .notice
            .as_ref()
            .is_some_and(|n| now - n.shown_at > NOTICE_SECONDS)
        {
            self.notice = None;
        }
        egui::Panel::bottom("goat_status_bar")
            .frame(
                Frame::new()
                    .fill(palette::PANEL)
                    .inner_margin(Margin::symmetric(10, 4)),
            )
            .show(ui, |ui| {
                ui::status_bar::show(
                    ui,
                    &ui::status_bar::StatusInfo {
                        tool: self.editor.tool,
                        module: self.module,
                        cursor: self.cursor_world,
                        zoom: self.view.zoom,
                        elements: self.editor.doc.elements.len(),
                        modified: self.editor.is_modified(),
                        notice: self.notice.as_ref().map(|n| (n.text.as_str(), n.is_error)),
                    },
                );
            });

        // --- Left: tools -------------------------------------------------
        egui::Panel::left("goat_toolbar")
            .resizable(false)
            .exact_size(56.0)
            .frame(
                Frame::new()
                    .fill(palette::PANEL)
                    .inner_margin(Margin::symmetric(8, 10)),
            )
            .show(ui, |ui| {
                actions.extend(ui::toolbar::show(
                    ui,
                    self.editor.tool,
                    self.editor.settings.color,
                ));
            });

        // --- Right: inspector ----------------------------------------------
        egui::Panel::right("goat_inspector")
            .resizable(true)
            .default_size(272.0)
            .size_range(232.0..=420.0)
            .frame(
                Frame::new()
                    .fill(palette::PANEL)
                    .inner_margin(Margin::symmetric(12, 10)),
            )
            .show(ui, |ui| {
                egui::ScrollArea::vertical()
                    .auto_shrink([false, false])
                    .show(ui, |ui| {
                        actions.extend(ui::inspector::show(ui, &mut self.editor, self.module));
                    });
            });

        // --- Center: the workspace canvas ------------------------------------
        egui::CentralPanel::default()
            .frame(Frame::new().fill(palette::CANVAS_BG))
            .show(ui, |ui| {
                let out = ui::canvas::show(
                    ui,
                    &mut self.editor,
                    &mut self.view,
                    &ui::canvas::CanvasOptions {
                        show_grid: self.show_grid,
                        module: self.module,
                        interactive: !modal_open,
                    },
                );
                self.cursor_world = out.hover_world;
                self.canvas_rect = out.rect;
            });

        self.show_dialogs(ctx);

        for action in actions {
            self.dispatch(ctx, action);
        }
        self.sync_window_title(ctx);
    }
}
