//! Undo / redo as document snapshots.
//!
//! Every editing action calls [`History::checkpoint`] *before* it mutates the
//! document. Snapshots are simple and bullet-proof for an MVP; when documents
//! grow large (raster layers in ImageGOAT) this is the place to switch to
//! command objects or structural sharing without touching the UI.

use std::collections::VecDeque;

use super::document::{Document, ElementId};

/// Identifies a run of small edits that should undo as one step, such as
/// dragging a color picker or a width slider across many frames.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct CoalesceKey {
    target: u64,
    field: &'static str,
}

impl CoalesceKey {
    /// A property edit on one element.
    pub fn element(id: ElementId, field: &'static str) -> Self {
        Self {
            target: id.0,
            field,
        }
    }

    /// A property edit on the document itself (size, background).
    pub fn document(field: &'static str) -> Self {
        Self {
            target: u64::MAX,
            field,
        }
    }
}

#[derive(Debug)]
pub struct History {
    undo: VecDeque<Document>,
    redo: Vec<Document>,
    limit: usize,
    coalesce: Option<CoalesceKey>,
}

impl Default for History {
    fn default() -> Self {
        Self::new(200)
    }
}

impl History {
    /// Keep at most `limit` undo steps (oldest are dropped first).
    pub fn new(limit: usize) -> Self {
        Self {
            undo: VecDeque::new(),
            redo: Vec::new(),
            limit: limit.max(1),
            coalesce: None,
        }
    }

    /// Record the document as it is *before* an edit.
    pub fn checkpoint(&mut self, doc: &Document) {
        self.coalesce = None;
        self.push(doc);
    }

    /// Like [`checkpoint`](Self::checkpoint), but consecutive calls with the
    /// same key share one undo step. Returns true if a snapshot was taken.
    pub fn checkpoint_coalesced(&mut self, doc: &Document, key: CoalesceKey) -> bool {
        if self.coalesce == Some(key) {
            return false;
        }
        self.push(doc);
        self.coalesce = Some(key);
        true
    }

    /// End the current coalescing run, so the next edit gets its own step.
    pub fn break_coalescing(&mut self) {
        self.coalesce = None;
    }

    /// Drop the latest checkpoint: used when a gesture turned out to change
    /// nothing (a click without a drag, a zero-size shape).
    pub fn discard_last(&mut self) {
        self.undo.pop_back();
        self.coalesce = None;
    }

    /// Step back. Returns false when there is nothing to undo.
    pub fn undo(&mut self, current: &mut Document) -> bool {
        self.coalesce = None;
        match self.undo.pop_back() {
            Some(previous) => {
                self.redo.push(std::mem::replace(current, previous));
                true
            }
            None => false,
        }
    }

    /// Step forward again. Returns false when there is nothing to redo.
    pub fn redo(&mut self, current: &mut Document) -> bool {
        self.coalesce = None;
        match self.redo.pop() {
            Some(next) => {
                self.undo.push_back(std::mem::replace(current, next));
                true
            }
            None => false,
        }
    }

    pub fn can_undo(&self) -> bool {
        !self.undo.is_empty()
    }

    pub fn can_redo(&self) -> bool {
        !self.redo.is_empty()
    }

    pub fn clear(&mut self) {
        self.undo.clear();
        self.redo.clear();
        self.coalesce = None;
    }

    fn push(&mut self, doc: &Document) {
        self.undo.push_back(doc.clone());
        while self.undo.len() > self.limit {
            self.undo.pop_front();
        }
        self.redo.clear();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::document::ElementKind;
    use egui::{pos2, Color32};

    fn add_dot(doc: &mut Document) -> ElementId {
        doc.add(
            ElementKind::Stroke {
                points: vec![pos2(1.0, 1.0)],
                width: 2.0,
            },
            Color32::WHITE,
        )
    }

    #[test]
    fn undo_then_redo_round_trips() {
        let mut doc = Document::default();
        let mut history = History::default();

        history.checkpoint(&doc);
        add_dot(&mut doc);
        assert_eq!(doc.elements.len(), 1);

        assert!(history.undo(&mut doc));
        assert!(doc.is_empty());
        assert!(history.redo(&mut doc));
        assert_eq!(doc.elements.len(), 1);
        assert!(!history.redo(&mut doc));
    }

    #[test]
    fn new_edit_clears_redo() {
        let mut doc = Document::default();
        let mut history = History::default();
        history.checkpoint(&doc);
        add_dot(&mut doc);
        history.undo(&mut doc);
        assert!(history.can_redo());
        history.checkpoint(&doc);
        assert!(!history.can_redo());
    }

    #[test]
    fn coalesced_edits_share_one_step() {
        let mut doc = Document::default();
        let mut history = History::default();
        let id = add_dot(&mut doc);
        let key = CoalesceKey::element(id, "color");

        for shade in 0..10u8 {
            history.checkpoint_coalesced(&doc, key);
            doc.get_mut(id).unwrap().color = Color32::from_gray(shade);
        }
        assert!(history.undo(&mut doc));
        assert_eq!(doc.get(id).unwrap().color, Color32::WHITE);
        assert!(!history.can_undo());
    }

    #[test]
    fn limit_drops_oldest() {
        let mut doc = Document::default();
        let mut history = History::new(3);
        for _ in 0..10 {
            history.checkpoint(&doc);
            add_dot(&mut doc);
        }
        let mut steps = 0;
        while history.undo(&mut doc) {
            steps += 1;
        }
        assert_eq!(steps, 3);
        assert_eq!(doc.elements.len(), 7);
    }
}
