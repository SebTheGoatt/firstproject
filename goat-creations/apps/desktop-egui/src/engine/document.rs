//! Document model: an artboard holding an ordered stack of elements.
//!
//! Coordinates are in *world units* (artboard pixels), with (0, 0) at the
//! artboard's top-left corner. The last element in [`Document::elements`]
//! is drawn on top.

use egui::{Color32, Pos2, Rect, Vec2};
use serde::{Deserialize, Serialize};

/// Stable identifier of an element; survives reordering, undo and save/load.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct ElementId(pub u64);

/// Geometric primitives the Vector tool can draw.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum ShapeKind {
    Rectangle,
    Ellipse,
}

impl ShapeKind {
    pub const ALL: [ShapeKind; 2] = [ShapeKind::Rectangle, ShapeKind::Ellipse];

    pub fn label(self) -> &'static str {
        match self {
            ShapeKind::Rectangle => "Rectangle",
            ShapeKind::Ellipse => "Ellipse",
        }
    }
}

/// What an element is, with its geometry.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub enum ElementKind {
    /// Freehand brush stroke: a polyline of sampled pointer positions.
    Stroke { points: Vec<Pos2>, width: f32 },
    /// Vector shape fitted to `rect`.
    Shape {
        kind: ShapeKind,
        rect: Rect,
        stroke_width: f32,
        filled: bool,
    },
    /// A block of text whose top-left corner sits at `pos`.
    Text {
        pos: Pos2,
        content: String,
        size: f32,
        /// Laid-out size in world units, written back by the renderer so hit
        /// testing matches what is on screen. A cache only: never saved.
        #[serde(skip)]
        measured: Option<Vec2>,
    },
}

impl ElementKind {
    /// Human-readable type name, used for default layer names.
    pub fn type_label(&self) -> &'static str {
        match self {
            ElementKind::Stroke { .. } => "Stroke",
            ElementKind::Shape { kind, .. } => kind.label(),
            ElementKind::Text { .. } => "Text",
        }
    }
}

/// One item on the artboard (a "layer" in the inspector).
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Element {
    pub id: ElementId,
    pub name: String,
    pub color: Color32,
    pub visible: bool,
    pub kind: ElementKind,
}

impl Element {
    /// Axis-aligned bounds in world units, including stroke thickness.
    pub fn bounds(&self) -> Rect {
        match &self.kind {
            ElementKind::Stroke { points, width } => {
                if points.is_empty() {
                    Rect::NOTHING
                } else {
                    Rect::from_points(points).expand(width * 0.5)
                }
            }
            ElementKind::Shape {
                rect, stroke_width, ..
            } => rect.expand(stroke_width * 0.5),
            ElementKind::Text {
                pos,
                content,
                size,
                measured,
            } => Rect::from_min_size(
                *pos,
                measured.unwrap_or_else(|| approx_text_size(content, *size)),
            ),
        }
    }

    /// Does `p` (world units) touch this element? `tolerance` widens the hit
    /// area so thin lines stay easy to grab at any zoom level.
    pub fn hit_test(&self, p: Pos2, tolerance: f32) -> bool {
        if !self.visible {
            return false;
        }
        match &self.kind {
            ElementKind::Stroke { points, width } => {
                let reach = width * 0.5 + tolerance;
                match points.as_slice() {
                    [] => false,
                    [only] => only.distance(p) <= reach,
                    _ => points
                        .windows(2)
                        .any(|seg| distance_to_segment(p, seg[0], seg[1]) <= reach),
                }
            }
            ElementKind::Shape {
                kind,
                rect,
                stroke_width,
                filled,
            } => {
                let reach = stroke_width * 0.5 + tolerance;
                match kind {
                    ShapeKind::Rectangle => {
                        let outer = rect.expand(reach).contains(p);
                        if *filled {
                            outer
                        } else {
                            // Only the outline counts; the hollow middle lets
                            // clicks through to whatever is underneath.
                            outer && !rect.shrink(reach).contains(p)
                        }
                    }
                    ShapeKind::Ellipse => {
                        let r = rect.size() * 0.5;
                        if r.x <= f32::EPSILON || r.y <= f32::EPSILON {
                            return rect.expand(reach).contains(p);
                        }
                        let q = p - rect.center();
                        let norm = ((q.x / r.x).powi(2) + (q.y / r.y).powi(2)).sqrt();
                        // Approximate distance to the outline, good enough for picking.
                        let dist = (norm - 1.0) * r.min_elem();
                        if *filled {
                            dist <= reach
                        } else {
                            dist.abs() <= reach
                        }
                    }
                }
            }
            ElementKind::Text { .. } => self.bounds().expand(tolerance).contains(p),
        }
    }

    /// Move the element by `delta` world units.
    pub fn translate(&mut self, delta: Vec2) {
        match &mut self.kind {
            ElementKind::Stroke { points, .. } => points.iter_mut().for_each(|p| *p += delta),
            ElementKind::Shape { rect, .. } => *rect = rect.translate(delta),
            ElementKind::Text { pos, .. } => *pos += delta,
        }
    }
}

/// The artboard and everything on it.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Document {
    pub width: f32,
    pub height: f32,
    pub background: Color32,
    pub elements: Vec<Element>,
    next_id: u64,
}

impl Default for Document {
    fn default() -> Self {
        Self {
            width: 1920.0,
            height: 1080.0,
            background: Color32::from_rgb(0x1B, 0x1E, 0x24),
            elements: Vec::new(),
            next_id: 1,
        }
    }
}

impl Document {
    pub fn size(&self) -> Vec2 {
        Vec2::new(self.width, self.height)
    }

    /// The artboard rectangle in world units.
    pub fn bounds(&self) -> Rect {
        Rect::from_min_size(Pos2::ZERO, self.size())
    }

    pub fn is_empty(&self) -> bool {
        self.elements.is_empty()
    }

    /// Add an element on top of the stack and return its id.
    pub fn add(&mut self, kind: ElementKind, color: Color32) -> ElementId {
        let id = ElementId(self.next_id);
        self.next_id += 1;
        let name = format!("{} {}", kind.type_label(), id.0);
        self.elements.push(Element {
            id,
            name,
            color,
            visible: true,
            kind,
        });
        id
    }

    pub fn index_of(&self, id: ElementId) -> Option<usize> {
        self.elements.iter().position(|e| e.id == id)
    }

    pub fn get(&self, id: ElementId) -> Option<&Element> {
        self.elements.iter().find(|e| e.id == id)
    }

    pub fn get_mut(&mut self, id: ElementId) -> Option<&mut Element> {
        self.elements.iter_mut().find(|e| e.id == id)
    }

    pub fn remove(&mut self, id: ElementId) -> Option<Element> {
        self.index_of(id).map(|i| self.elements.remove(i))
    }

    /// The top-most visible element under `p`, if any.
    pub fn topmost_at(&self, p: Pos2, tolerance: f32) -> Option<ElementId> {
        self.elements
            .iter()
            .rev()
            .find(|e| e.hit_test(p, tolerance))
            .map(|e| e.id)
    }

    /// Move an element one step towards the top. Returns false if it already is.
    pub fn bring_forward(&mut self, id: ElementId) -> bool {
        match self.index_of(id) {
            Some(i) if i + 1 < self.elements.len() => {
                self.elements.swap(i, i + 1);
                true
            }
            _ => false,
        }
    }

    /// Move an element one step towards the bottom. Returns false if it already is.
    pub fn send_backward(&mut self, id: ElementId) -> bool {
        match self.index_of(id) {
            Some(i) if i > 0 => {
                self.elements.swap(i, i - 1);
                true
            }
            _ => false,
        }
    }

    /// Restore invariants after loading a file written by hand or by an
    /// older version: ids must stay unique and sizes positive.
    pub fn repair(&mut self) {
        let max_id = self.elements.iter().map(|e| e.id.0).max().unwrap_or(0);
        self.next_id = self.next_id.max(max_id + 1);
        self.width = self.width.max(1.0);
        self.height = self.height.max(1.0);
    }
}

/// Rough text size before the renderer has measured it (proportional font).
fn approx_text_size(content: &str, size: f32) -> Vec2 {
    let lines = content.lines().count().max(1) as f32;
    let longest = content
        .lines()
        .map(|l| l.chars().count())
        .max()
        .unwrap_or(0) as f32;
    Vec2::new((longest * size * 0.55).max(size * 0.5), lines * size * 1.2)
}

/// Shortest distance from `p` to the segment `a`-`b`.
pub fn distance_to_segment(p: Pos2, a: Pos2, b: Pos2) -> f32 {
    let ab = b - a;
    let len_sq = ab.length_sq();
    if len_sq <= f32::EPSILON {
        return p.distance(a);
    }
    let t = ((p - a).dot(ab) / len_sq).clamp(0.0, 1.0);
    p.distance(a + ab * t)
}

#[cfg(test)]
mod tests {
    use super::*;
    use egui::pos2;

    fn doc_with_rect(filled: bool) -> (Document, ElementId) {
        let mut doc = Document::default();
        let id = doc.add(
            ElementKind::Shape {
                kind: ShapeKind::Rectangle,
                rect: Rect::from_min_max(pos2(10.0, 10.0), pos2(110.0, 60.0)),
                stroke_width: 4.0,
                filled,
            },
            Color32::WHITE,
        );
        (doc, id)
    }

    #[test]
    fn ids_are_unique_and_names_follow_type() {
        let mut doc = Document::default();
        let a = doc.add(
            ElementKind::Stroke {
                points: vec![pos2(0.0, 0.0)],
                width: 2.0,
            },
            Color32::RED,
        );
        let b = doc.add(
            ElementKind::Text {
                pos: Pos2::ZERO,
                content: "GOAT".into(),
                size: 32.0,
                measured: None,
            },
            Color32::RED,
        );
        assert_ne!(a, b);
        assert_eq!(doc.get(a).unwrap().name, "Stroke 1");
        assert_eq!(doc.get(b).unwrap().name, "Text 2");
    }

    #[test]
    fn hollow_rectangle_only_hits_its_outline() {
        let (doc, id) = doc_with_rect(false);
        assert_eq!(doc.topmost_at(pos2(10.0, 30.0), 1.0), Some(id));
        assert_eq!(doc.topmost_at(pos2(60.0, 35.0), 1.0), None);
    }

    #[test]
    fn filled_rectangle_hits_inside() {
        let (doc, id) = doc_with_rect(true);
        assert_eq!(doc.topmost_at(pos2(60.0, 35.0), 1.0), Some(id));
        assert_eq!(doc.topmost_at(pos2(500.0, 500.0), 1.0), None);
    }

    #[test]
    fn stroke_hit_respects_width() {
        let mut doc = Document::default();
        let id = doc.add(
            ElementKind::Stroke {
                points: vec![pos2(0.0, 0.0), pos2(100.0, 0.0)],
                width: 10.0,
            },
            Color32::WHITE,
        );
        assert_eq!(doc.topmost_at(pos2(50.0, 5.0), 0.5), Some(id));
        assert_eq!(doc.topmost_at(pos2(50.0, 9.0), 0.5), None);
    }

    #[test]
    fn hidden_elements_are_not_picked() {
        let (mut doc, id) = doc_with_rect(true);
        doc.get_mut(id).unwrap().visible = false;
        assert_eq!(doc.topmost_at(pos2(60.0, 35.0), 1.0), None);
    }

    #[test]
    fn reorder_and_translate() {
        let (mut doc, a) = doc_with_rect(true);
        let b = doc.add(
            ElementKind::Stroke {
                points: vec![pos2(1.0, 1.0)],
                width: 1.0,
            },
            Color32::RED,
        );
        assert!(doc.send_backward(b));
        assert_eq!(doc.elements[0].id, b);
        assert!(!doc.send_backward(b));
        assert!(doc.bring_forward(b));
        assert_eq!(doc.elements[1].id, b);

        doc.get_mut(a).unwrap().translate(Vec2::new(5.0, -5.0));
        assert_eq!(doc.get(a).unwrap().bounds().min, pos2(13.0, 3.0));
    }

    #[test]
    fn repair_keeps_ids_unique() {
        let mut doc = Document::default();
        doc.add(
            ElementKind::Stroke {
                points: vec![],
                width: 1.0,
            },
            Color32::RED,
        );
        doc.elements[0].id = ElementId(40);
        doc.next_id = 2;
        doc.repair();
        let next = doc.add(
            ElementKind::Stroke {
                points: vec![],
                width: 1.0,
            },
            Color32::RED,
        );
        assert_eq!(next, ElementId(41));
    }
}
