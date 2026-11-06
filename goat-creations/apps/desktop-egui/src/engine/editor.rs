//! The editing pipeline: turns pointer gestures and commands into document
//! changes, with undo checkpoints in the right places.
//!
//! The UI calls `pointer_down` / `pointer_drag` / `pointer_up` with positions
//! already converted to world units, so this code never deals with zoom or
//! screen space.

use egui::{Pos2, Rect, Vec2};

use super::document::{Document, Element, ElementId, ElementKind};
use super::history::{CoalesceKey, History};
use super::tools::{Tool, ToolSettings};

/// A press-drag-release that is in progress.
#[derive(Clone, Copy, Debug, PartialEq)]
enum Gesture {
    Idle,
    Stroke {
        id: ElementId,
    },
    Shape {
        id: ElementId,
        anchor: Pos2,
    },
    Move {
        id: ElementId,
        last: Pos2,
        moved: bool,
    },
}

#[derive(Debug)]
pub struct Editor {
    pub doc: Document,
    pub history: History,
    pub tool: Tool,
    pub settings: ToolSettings,
    selection: Option<ElementId>,
    gesture: Gesture,
    modified: bool,
}

impl Default for Editor {
    fn default() -> Self {
        Self {
            doc: Document::default(),
            history: History::default(),
            tool: Tool::default(),
            settings: ToolSettings::default(),
            selection: None,
            gesture: Gesture::Idle,
            modified: false,
        }
    }
}

impl Editor {
    // ----------------------------------------------------------------- state

    /// True while a drag gesture is running.
    pub fn is_busy(&self) -> bool {
        self.gesture != Gesture::Idle
    }

    /// True when the document changed since it was created, opened or saved.
    pub fn is_modified(&self) -> bool {
        self.modified
    }

    pub fn mark_saved(&mut self) {
        self.modified = false;
    }

    pub fn selection(&self) -> Option<ElementId> {
        self.selection
    }

    pub fn selected(&self) -> Option<&Element> {
        self.selection.and_then(|id| self.doc.get(id))
    }

    pub fn select(&mut self, id: Option<ElementId>) {
        self.selection = id.filter(|id| self.doc.get(*id).is_some());
        self.history.break_coalescing();
    }

    pub fn set_tool(&mut self, tool: Tool) {
        self.pointer_up();
        self.tool = tool;
    }

    // -------------------------------------------------------------- gestures

    /// Primary button pressed on the canvas at `world`. `tolerance` is the
    /// pick radius in world units (the UI scales it with zoom).
    pub fn pointer_down(&mut self, world: Pos2, tolerance: f32) {
        self.pointer_up(); // finish anything left over (e.g. focus lost mid-drag)
        match self.tool {
            Tool::Select => {
                self.selection = self.doc.topmost_at(world, tolerance);
                self.history.break_coalescing();
                if let Some(id) = self.selection {
                    self.history.checkpoint(&self.doc);
                    self.gesture = Gesture::Move {
                        id,
                        last: world,
                        moved: false,
                    };
                }
            }
            Tool::Brush => {
                self.history.checkpoint(&self.doc);
                let id = self.doc.add(
                    ElementKind::Stroke {
                        points: vec![world],
                        width: self.settings.brush_width,
                    },
                    self.settings.color,
                );
                self.selection = None;
                self.gesture = Gesture::Stroke { id };
                self.modified = true;
            }
            Tool::Vector => {
                self.history.checkpoint(&self.doc);
                let id = self.doc.add(
                    ElementKind::Shape {
                        kind: self.settings.shape,
                        rect: Rect::from_min_max(world, world),
                        stroke_width: self.settings.stroke_width,
                        filled: self.settings.filled,
                    },
                    self.settings.color,
                );
                self.selection = None;
                self.gesture = Gesture::Shape { id, anchor: world };
                self.modified = true;
            }
            Tool::Text => {
                if self.settings.text.trim().is_empty() {
                    return;
                }
                self.history.checkpoint(&self.doc);
                let id = self.doc.add(
                    ElementKind::Text {
                        pos: world,
                        content: self.settings.text.clone(),
                        size: self.settings.font_size,
                        measured: None,
                    },
                    self.settings.color,
                );
                self.selection = Some(id);
                self.modified = true;
            }
        }
    }

    /// Pointer moved while the button is held. `constrain` (Shift) makes
    /// shapes square; `min_step` thins brush samples (world units).
    pub fn pointer_drag(&mut self, world: Pos2, constrain: bool, min_step: f32) {
        match self.gesture {
            Gesture::Idle => {}
            Gesture::Stroke { id } => {
                if let Some(Element {
                    kind: ElementKind::Stroke { points, .. },
                    ..
                }) = self.doc.get_mut(id)
                {
                    if points
                        .last()
                        .is_none_or(|last| last.distance(world) >= min_step)
                    {
                        points.push(world);
                    }
                }
            }
            Gesture::Shape { id, anchor } => {
                let end = if constrain {
                    square_corner(anchor, world)
                } else {
                    world
                };
                if let Some(Element {
                    kind: ElementKind::Shape { rect, .. },
                    ..
                }) = self.doc.get_mut(id)
                {
                    *rect = Rect::from_two_pos(anchor, end);
                }
            }
            Gesture::Move { id, last, moved } => {
                let delta = world - last;
                if delta != Vec2::ZERO {
                    if let Some(el) = self.doc.get_mut(id) {
                        el.translate(delta);
                    }
                    self.gesture = Gesture::Move {
                        id,
                        last: world,
                        moved: true,
                    };
                    self.modified = true;
                } else {
                    self.gesture = Gesture::Move { id, last, moved };
                }
            }
        }
    }

    /// Button released (or the gesture was interrupted). Safe to call any time.
    pub fn pointer_up(&mut self) {
        match std::mem::replace(&mut self.gesture, Gesture::Idle) {
            Gesture::Idle | Gesture::Stroke { .. } => {}
            Gesture::Shape { id, .. } => {
                let tiny = matches!(
                    self.doc.get(id),
                    Some(Element { kind: ElementKind::Shape { rect, .. }, .. })
                        if rect.width() < 2.0 && rect.height() < 2.0
                );
                if tiny {
                    // A click without a drag: don't leave an invisible shape behind.
                    self.doc.remove(id);
                    self.history.discard_last();
                } else {
                    self.selection = Some(id);
                }
            }
            Gesture::Move { moved, .. } => {
                if !moved {
                    // Plain click to select: nothing to undo.
                    self.history.discard_last();
                }
            }
        }
    }

    // -------------------------------------------------------------- commands

    pub fn undo(&mut self) -> bool {
        self.pointer_up();
        let changed = self.history.undo(&mut self.doc);
        self.after_history_jump(changed)
    }

    pub fn redo(&mut self) -> bool {
        self.pointer_up();
        let changed = self.history.redo(&mut self.doc);
        self.after_history_jump(changed)
    }

    fn after_history_jump(&mut self, changed: bool) -> bool {
        if changed {
            self.modified = true;
            // The selected element may not exist in the restored snapshot.
            self.selection = self.selection.filter(|id| self.doc.get(*id).is_some());
        }
        changed
    }

    /// Delete the selected element. Returns false when nothing was selected.
    pub fn delete_selection(&mut self) -> bool {
        let Some(id) = self.selection else {
            return false;
        };
        self.history.checkpoint(&self.doc);
        self.doc.remove(id);
        self.selection = None;
        self.modified = true;
        true
    }

    /// Remove every element, keeping the artboard settings. Undoable.
    pub fn clear_canvas(&mut self) {
        if self.doc.is_empty() {
            return;
        }
        self.pointer_up();
        self.history.checkpoint(&self.doc);
        self.doc.elements.clear();
        self.selection = None;
        self.modified = true;
    }

    pub fn bring_forward(&mut self) -> bool {
        self.reorder(Document::bring_forward)
    }

    pub fn send_backward(&mut self) -> bool {
        self.reorder(Document::send_backward)
    }

    fn reorder(&mut self, op: fn(&mut Document, ElementId) -> bool) -> bool {
        let Some(id) = self.selection else {
            return false;
        };
        let snapshot = self.doc.clone();
        if op(&mut self.doc, id) {
            self.history.checkpoint(&snapshot);
            self.modified = true;
            true
        } else {
            false
        }
    }

    /// Show or hide an element (layer eye toggle). Undoable.
    pub fn set_visible(&mut self, id: ElementId, visible: bool) {
        if self.doc.get(id).is_some_and(|e| e.visible != visible) {
            self.history.checkpoint(&self.doc);
            if let Some(el) = self.doc.get_mut(id) {
                el.visible = visible;
            }
            self.modified = true;
        }
    }

    /// Edit a property of the selected element. Repeated edits of the same
    /// `field` (a slider drag, a color picker) collapse into one undo step.
    pub fn edit_selected(&mut self, field: &'static str, edit: impl FnOnce(&mut Element)) {
        let Some(id) = self.selection else { return };
        if self.doc.get(id).is_none() {
            return;
        }
        self.history
            .checkpoint_coalesced(&self.doc, CoalesceKey::element(id, field));
        if let Some(el) = self.doc.get_mut(id) {
            edit(el);
        }
        self.modified = true;
    }

    /// Edit a document-level property (size, background), coalesced by `field`.
    pub fn edit_document(&mut self, field: &'static str, edit: impl FnOnce(&mut Document)) {
        self.history
            .checkpoint_coalesced(&self.doc, CoalesceKey::document(field));
        edit(&mut self.doc);
        self.modified = true;
    }

    /// Start over with a blank artboard. Tool and settings are kept.
    pub fn new_document(&mut self) {
        self.replace_document(Document::default());
    }

    /// Swap in a freshly opened document; history starts clean.
    pub fn replace_document(&mut self, doc: Document) {
        self.gesture = Gesture::Idle;
        self.doc = doc;
        self.history.clear();
        self.selection = None;
        self.modified = false;
    }
}

/// Push `end` out so the box from `anchor` to it is square (Shift-drag).
fn square_corner(anchor: Pos2, end: Pos2) -> Pos2 {
    let d = end - anchor;
    let side = d.x.abs().max(d.y.abs());
    anchor + Vec2::new(side.copysign(d.x), side.copysign(d.y))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::document::ShapeKind;
    use egui::pos2;

    #[test]
    fn brush_drag_paints_one_undoable_stroke() {
        let mut ed = Editor {
            tool: Tool::Brush,
            ..Default::default()
        };
        ed.pointer_down(pos2(0.0, 0.0), 1.0);
        for i in 1..=10 {
            ed.pointer_drag(pos2(i as f32 * 3.0, 0.0), false, 1.0);
        }
        ed.pointer_up();

        assert_eq!(ed.doc.elements.len(), 1);
        match &ed.doc.elements[0].kind {
            ElementKind::Stroke { points, .. } => assert_eq!(points.len(), 11),
            other => panic!("expected stroke, got {other:?}"),
        }
        assert!(ed.is_modified());
        assert!(ed.undo());
        assert!(ed.doc.is_empty());
    }

    #[test]
    fn vector_click_without_drag_leaves_nothing() {
        let mut ed = Editor {
            tool: Tool::Vector,
            ..Default::default()
        };
        ed.pointer_down(pos2(50.0, 50.0), 1.0);
        ed.pointer_up();
        assert!(ed.doc.is_empty());
        assert!(!ed.history.can_undo());
    }

    #[test]
    fn shift_drag_makes_a_square() {
        let mut ed = Editor {
            tool: Tool::Vector,
            ..Default::default()
        };
        ed.settings.shape = ShapeKind::Ellipse;
        ed.pointer_down(pos2(100.0, 100.0), 1.0);
        ed.pointer_drag(pos2(40.0, 180.0), true, 1.0);
        ed.pointer_up();
        let sel = ed.selected().expect("new shape is selected");
        match &sel.kind {
            ElementKind::Shape { rect, kind, .. } => {
                assert_eq!(*kind, ShapeKind::Ellipse);
                assert_eq!(rect.width(), 80.0);
                assert_eq!(rect.height(), 80.0);
                assert_eq!(rect.min, pos2(20.0, 100.0));
            }
            other => panic!("expected shape, got {other:?}"),
        }
    }

    #[test]
    fn select_and_move_then_undo_restores_position() {
        let mut ed = Editor {
            tool: Tool::Text,
            ..Default::default()
        };
        ed.pointer_down(pos2(10.0, 10.0), 1.0);
        let id = ed.selection().unwrap();

        ed.set_tool(Tool::Select);
        ed.pointer_down(pos2(12.0, 12.0), 2.0);
        assert_eq!(ed.selection(), Some(id));
        ed.pointer_drag(pos2(52.0, 32.0), false, 1.0);
        ed.pointer_up();
        assert_eq!(ed.doc.get(id).unwrap().bounds().min, pos2(50.0, 30.0));

        assert!(ed.undo());
        assert_eq!(ed.doc.get(id).unwrap().bounds().min, pos2(10.0, 10.0));
    }

    #[test]
    fn click_to_select_adds_no_undo_step() {
        let mut ed = Editor {
            tool: Tool::Text,
            ..Default::default()
        };
        ed.pointer_down(pos2(10.0, 10.0), 1.0);
        ed.set_tool(Tool::Select);
        ed.pointer_down(pos2(12.0, 12.0), 2.0);
        ed.pointer_up();
        assert!(ed.undo()); // undoes the text placement, not the click
        assert!(ed.doc.is_empty());
        assert!(!ed.history.can_undo());
    }

    #[test]
    fn clicking_empty_space_deselects() {
        let mut ed = Editor {
            tool: Tool::Text,
            ..Default::default()
        };
        ed.pointer_down(pos2(10.0, 10.0), 1.0);
        ed.set_tool(Tool::Select);
        ed.pointer_down(pos2(1500.0, 900.0), 2.0);
        ed.pointer_up();
        assert_eq!(ed.selection(), None);
    }

    #[test]
    fn delete_and_property_edits_are_undoable() {
        let mut ed = Editor {
            tool: Tool::Text,
            ..Default::default()
        };
        ed.pointer_down(pos2(10.0, 10.0), 1.0);
        for gray in 0..5 {
            ed.edit_selected("color", |el| el.color = egui::Color32::from_gray(gray));
        }
        assert!(ed.delete_selection());
        assert!(ed.doc.is_empty());
        assert!(ed.undo()); // back comes the text...
        assert!(ed.undo()); // ...with its original color, in one step
        assert_eq!(ed.doc.elements[0].color, ToolSettings::default().color);
    }

    #[test]
    fn undo_drops_stale_selection() {
        let mut ed = Editor {
            tool: Tool::Text,
            ..Default::default()
        };
        ed.pointer_down(pos2(10.0, 10.0), 1.0);
        assert!(ed.selection().is_some());
        ed.undo();
        assert_eq!(ed.selection(), None);
    }

    #[test]
    fn empty_text_is_not_placed() {
        let mut ed = Editor {
            tool: Tool::Text,
            ..Default::default()
        };
        ed.settings.text = "   ".into();
        ed.pointer_down(pos2(10.0, 10.0), 1.0);
        assert!(ed.doc.is_empty());
    }
}
