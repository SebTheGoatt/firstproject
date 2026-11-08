//! The central workspace: an infinite, pannable, zoomable canvas holding the
//! artboard. Converts raw pointer input into engine calls and renders the
//! document.
//!
//! Navigation:
//! - scroll / two-finger swipe: pan
//! - Ctrl + scroll / pinch: zoom towards the cursor
//! - middle-drag, or hold Space and drag: pan

use egui::{
    pos2, text::LayoutJob, vec2, Align2, Color32, CornerRadius, CursorIcon, FontId, Key, Painter,
    PointerButton, Pos2, Rect, Sense, Shape, Stroke, StrokeKind, TextFormat, Ui,
};

use super::theme::palette;
use super::widgets::paint_logo_mark;
use crate::app::Module;
use crate::engine::{Editor, Element, ElementKind, ShapeKind, Tool, Viewport};

pub struct CanvasOptions {
    pub show_grid: bool,
    pub module: Module,
    /// False while a modal dialog is open: draw, but ignore pointer input.
    pub interactive: bool,
}

pub struct CanvasOutput {
    /// Cursor position in artboard coordinates, while hovering the canvas.
    pub hover_world: Option<Pos2>,
    /// Screen rect of the canvas (used for keyboard zoom).
    pub rect: Rect,
}

/// Pick radius in screen points; converted to world units with the zoom.
const PICK_RADIUS: f32 = 6.0;

pub fn show(
    ui: &mut Ui,
    editor: &mut Editor,
    view: &mut Viewport,
    opts: &CanvasOptions,
) -> CanvasOutput {
    let (response, painter) = ui.allocate_painter(ui.available_size(), Sense::click_and_drag());
    let rect = response.rect;
    let origin = rect.min;

    if view.needs_fit && rect.is_positive() {
        view.fit(editor.doc.size(), rect);
    }

    let space_held = ui.input(|i| i.key_down(Key::Space));
    if opts.interactive {
        navigate(ui, &response, view, origin, space_held);
        if !space_held {
            route_pointer(ui, &response, editor, view, origin);
        }
    }

    let hover_world = response
        .hover_pos()
        .map(|p| view.screen_to_world(p, origin));
    let painter = painter.with_clip_rect(rect);
    paint_background(&painter, rect, view, origin, opts.show_grid);
    let board = view.world_rect_to_screen(editor.doc.bounds(), origin);
    paint_artboard(&painter, rect, board, editor, view, origin);
    paint_overlays(
        &painter,
        editor,
        view,
        origin,
        hover_world,
        response.hovered(),
    );
    paint_corner_label(&painter, rect, editor, opts.module);

    if response.hovered() && opts.interactive {
        ui.ctx()
            .set_cursor_icon(cursor_for(editor, hover_world, view, space_held, &response));
    }

    CanvasOutput { hover_world, rect }
}

// ------------------------------------------------------------------ input

fn navigate(
    ui: &Ui,
    response: &egui::Response,
    view: &mut Viewport,
    origin: Pos2,
    space_held: bool,
) {
    if response.hovered() {
        let (scroll, zoom) = ui.input(|i| (i.smooth_scroll_delta, i.zoom_delta()));
        if zoom != 1.0 {
            if let Some(p) = response.hover_pos() {
                view.zoom_around(p, origin, zoom);
            }
        } else if scroll != egui::Vec2::ZERO {
            view.pan(scroll);
        }
    }
    let panning = response.dragged_by(PointerButton::Middle)
        || (space_held && response.dragged_by(PointerButton::Primary));
    if panning {
        view.pan(response.drag_delta());
    }
}

/// Feed primary-button press / drag / release to the editor. Raw pointer
/// state is used (not click/drag events) so painting starts on the very
/// first pixel, with no drag threshold.
fn route_pointer(
    ui: &Ui,
    response: &egui::Response,
    editor: &mut Editor,
    view: &Viewport,
    origin: Pos2,
) {
    let (pressed, down, pos, shift) = ui.input(|i| {
        (
            i.pointer.primary_pressed(),
            i.pointer.primary_down(),
            i.pointer.interact_pos(),
            i.modifiers.shift,
        )
    });
    let Some(pos) = pos else {
        editor.pointer_up();
        return;
    };
    let world = view.screen_to_world(pos, origin);

    if pressed && response.hovered() {
        editor.pointer_down(world, PICK_RADIUS / view.zoom);
    } else if editor.is_busy() {
        if down {
            // Sample brush points about every screen pixel, at any zoom.
            editor.pointer_drag(world, shift, 1.0 / view.zoom);
        } else {
            editor.pointer_up();
        }
    }
}

fn cursor_for(
    editor: &Editor,
    hover: Option<Pos2>,
    view: &Viewport,
    space: bool,
    response: &egui::Response,
) -> CursorIcon {
    if space || response.dragged_by(PointerButton::Middle) {
        return if response.dragged() {
            CursorIcon::Grabbing
        } else {
            CursorIcon::Grab
        };
    }
    match editor.tool {
        Tool::Select => {
            let over = hover.and_then(|p| editor.doc.topmost_at(p, PICK_RADIUS / view.zoom));
            if editor.is_busy() {
                CursorIcon::Grabbing
            } else if over.is_some() {
                CursorIcon::Move
            } else {
                CursorIcon::Default
            }
        }
        Tool::Brush | Tool::Vector => CursorIcon::Crosshair,
        Tool::Text => CursorIcon::Text,
    }
}

// --------------------------------------------------------------- painting

fn paint_background(painter: &Painter, rect: Rect, view: &Viewport, origin: Pos2, show_grid: bool) {
    painter.rect_filled(rect, CornerRadius::ZERO, palette::CANVAS_BG);
    if !show_grid {
        return;
    }
    // Grid step in world units, doubled until lines are at least 16 px apart.
    let mut step = 32.0;
    while step * view.zoom < 16.0 {
        step *= 2.0;
    }
    while step * view.zoom > 128.0 && step > 1.0 {
        step /= 2.0;
    }
    let min = view.screen_to_world(rect.min, origin);
    let max = view.screen_to_world(rect.max, origin);
    let minor = Stroke::new(1.0, Color32::from_white_alpha(6));
    let major = Stroke::new(1.0, Color32::from_white_alpha(12));

    let mut x = (min.x / step).floor() * step;
    while x <= max.x {
        let sx = view.world_to_screen(pos2(x, 0.0), origin).x.round() + 0.5;
        let is_major = ((x / step).round() as i64).rem_euclid(4) == 0;
        painter.vline(sx, rect.y_range(), if is_major { major } else { minor });
        x += step;
    }
    let mut y = (min.y / step).floor() * step;
    while y <= max.y {
        let sy = view.world_to_screen(pos2(0.0, y), origin).y.round() + 0.5;
        let is_major = ((y / step).round() as i64).rem_euclid(4) == 0;
        painter.hline(rect.x_range(), sy, if is_major { major } else { minor });
        y += step;
    }
}

fn paint_artboard(
    painter: &Painter,
    clip: Rect,
    board: Rect,
    editor: &mut Editor,
    view: &Viewport,
    origin: Pos2,
) {
    // Soft drop shadow, then the board itself.
    for (grow, alpha) in [(12.0, 18), (6.0, 30), (2.0, 60)] {
        painter.rect_filled(
            board.expand(grow).translate(vec2(0.0, 4.0)),
            CornerRadius::same(6),
            Color32::from_black_alpha(alpha),
        );
    }
    painter.rect_filled(board, CornerRadius::ZERO, editor.doc.background);

    let board_painter = painter.with_clip_rect(board.intersect(clip));
    if editor.doc.is_empty() {
        paint_empty_state(&board_painter, board);
    }
    for el in editor.doc.elements.iter_mut().filter(|e| e.visible) {
        paint_element(&board_painter, el, view, origin);
    }
    painter.rect_stroke(
        board,
        CornerRadius::ZERO,
        Stroke::new(1.0, palette::BORDER),
        StrokeKind::Outside,
    );
}

/// The branded welcome shown on an empty artboard.
fn paint_empty_state(painter: &Painter, board: Rect) {
    let scale = (board.width() / 1100.0).clamp(0.25, 3.0);
    let c = board.center();

    let mark = Rect::from_center_size(c - vec2(0.0, 92.0 * scale), egui::Vec2::splat(56.0 * scale));
    paint_logo_mark(painter, mark);

    let size = 64.0 * scale;
    let spacing = size * 0.12;
    let mut job = LayoutJob::default();
    let fmt = |color: Color32| TextFormat {
        font_id: FontId::proportional(size),
        color,
        extra_letter_spacing: spacing,
        ..Default::default()
    };
    job.append("GOAT ", 0.0, fmt(palette::ACCENT));
    job.append("CREATIONS", 0.0, fmt(palette::TEXT));
    let galley = painter.layout_job(job);
    let title_pos = c - vec2(galley.size().x * 0.5, galley.size().y * 0.5 - 4.0 * scale);
    painter.galley(title_pos, galley, palette::TEXT);

    painter.text(
        c + vec2(0.0, 58.0 * scale),
        Align2::CENTER_CENTER,
        "The Greatest of All Time Open-Source Creative Suite",
        FontId::proportional(20.0 * scale),
        palette::TEXT_DIM,
    );
    painter.text(
        c + vec2(0.0, 112.0 * scale),
        Align2::CENTER_CENTER,
        "B  brush     P  shapes     T  text     V  select     Space + drag  pan     Ctrl + scroll  zoom",
        FontId::monospace(13.0 * scale),
        Color32::from_white_alpha(70),
    );
}

fn paint_element(painter: &Painter, el: &mut Element, view: &Viewport, origin: Pos2) {
    let color = el.color;
    let zoom = view.zoom;
    let to_screen = |p: Pos2| view.world_to_screen(p, origin);

    match &mut el.kind {
        ElementKind::Stroke { points, width } => {
            let w = (*width * zoom).max(0.75);
            match points.as_slice() {
                [] => {}
                [only] => {
                    painter.circle_filled(to_screen(*only), w * 0.5, color);
                }
                _ => {
                    let screen: Vec<Pos2> = points.iter().map(|p| to_screen(*p)).collect();
                    // Round joins and caps for thick opaque strokes (overlap
                    // would show through on translucent ones, so skip there).
                    if w > 3.0 && color.a() == 255 {
                        for p in &screen {
                            painter.circle_filled(*p, w * 0.5, color);
                        }
                    }
                    painter.add(Shape::line(screen, Stroke::new(w, color)));
                }
            }
        }
        ElementKind::Shape {
            kind,
            rect,
            stroke_width,
            filled,
        } => {
            let r = view.world_rect_to_screen(*rect, origin);
            let stroke = Stroke::new((*stroke_width * zoom).max(0.75), color);
            match kind {
                ShapeKind::Rectangle => {
                    if *filled {
                        painter.rect_filled(r, CornerRadius::ZERO, color);
                    } else {
                        painter.rect_stroke(r, CornerRadius::ZERO, stroke, StrokeKind::Middle);
                    }
                }
                ShapeKind::Ellipse => {
                    let pts = ellipse_points(r, 96);
                    if *filled {
                        painter.add(Shape::convex_polygon(pts, color, Stroke::NONE));
                    } else {
                        painter.add(Shape::closed_line(pts, stroke));
                    }
                }
            }
        }
        ElementKind::Text {
            pos,
            content,
            size,
            measured,
        } => {
            // Whole-pixel font sizes keep the glyph cache small while zooming.
            let px = (*size * zoom).round().clamp(1.0, 600.0);
            let drawn = painter.text(
                to_screen(*pos),
                Align2::LEFT_TOP,
                content.as_str(),
                FontId::proportional(px),
                color,
            );
            *measured = Some(drawn.size() / zoom);
        }
    }
}

fn ellipse_points(r: Rect, segments: usize) -> Vec<Pos2> {
    let (c, rx, ry) = (r.center(), r.width() * 0.5, r.height() * 0.5);
    (0..segments)
        .map(|i| {
            let t = i as f32 / segments as f32 * std::f32::consts::TAU;
            pos2(c.x + rx * t.cos(), c.y + ry * t.sin())
        })
        .collect()
}

fn paint_overlays(
    painter: &Painter,
    editor: &Editor,
    view: &Viewport,
    origin: Pos2,
    hover: Option<Pos2>,
    hovered: bool,
) {
    // Hover highlight for the Select tool.
    if editor.tool == Tool::Select && !editor.is_busy() {
        if let Some(id) = hover.and_then(|p| editor.doc.topmost_at(p, PICK_RADIUS / view.zoom)) {
            if Some(id) != editor.selection() {
                if let Some(el) = editor.doc.get(id) {
                    let r = view.world_rect_to_screen(el.bounds(), origin).expand(3.0);
                    painter.rect_stroke(
                        r,
                        CornerRadius::same(2),
                        Stroke::new(1.0, palette::ACCENT.gamma_multiply(0.5)),
                        StrokeKind::Outside,
                    );
                }
            }
        }
    }

    // Selection box with corner handles.
    if let Some(el) = editor.selected() {
        let r = view.world_rect_to_screen(el.bounds(), origin).expand(4.0);
        painter.rect_stroke(
            r,
            CornerRadius::ZERO,
            Stroke::new(1.5, palette::ACCENT),
            StrokeKind::Outside,
        );
        for corner in [
            r.left_top(),
            r.right_top(),
            r.left_bottom(),
            r.right_bottom(),
        ] {
            let h = Rect::from_center_size(corner, vec2(7.0, 7.0));
            painter.rect_filled(h, CornerRadius::same(1), palette::PANEL);
            painter.rect_stroke(
                h,
                CornerRadius::same(1),
                Stroke::new(1.5, palette::ACCENT),
                StrokeKind::Inside,
            );
        }
    }

    // Brush size preview ring.
    if editor.tool == Tool::Brush && hovered {
        if let Some(p) = hover {
            let r = (editor.settings.brush_width * view.zoom * 0.5).max(2.0);
            let s = view.world_to_screen(p, origin);
            painter.circle_stroke(s, r, Stroke::new(1.0, Color32::from_white_alpha(150)));
            painter.circle_stroke(s, r + 1.0, Stroke::new(1.0, Color32::from_black_alpha(120)));
        }
    }
}

fn paint_corner_label(painter: &Painter, rect: Rect, editor: &Editor, module: Module) {
    let text = format!(
        "{}  ·  Artboard {:.0} × {:.0}",
        module.name(),
        editor.doc.width,
        editor.doc.height
    );
    painter.text(
        rect.left_top() + vec2(14.0, 12.0),
        Align2::LEFT_TOP,
        text,
        FontId::proportional(12.0),
        palette::TEXT_DIM,
    );
}
