//! Pan and zoom: the mapping between world units and screen points.
//!
//! `screen = origin + offset + world * zoom`, where `origin` is the top-left
//! corner of the canvas widget on screen.

use egui::{Pos2, Rect, Vec2};

pub const MIN_ZOOM: f32 = 0.05;
pub const MAX_ZOOM: f32 = 32.0;

#[derive(Clone, Copy, Debug)]
pub struct Viewport {
    /// Screen offset of the world origin, relative to the canvas origin.
    pub offset: Vec2,
    /// Screen points per world unit.
    pub zoom: f32,
    /// When true, the canvas fits the artboard to the view on its next frame
    /// (at start-up, after "New" or "Reset view").
    pub needs_fit: bool,
}

impl Default for Viewport {
    fn default() -> Self {
        Self {
            offset: Vec2::ZERO,
            zoom: 1.0,
            needs_fit: true,
        }
    }
}

impl Viewport {
    pub fn world_to_screen(&self, world: Pos2, origin: Pos2) -> Pos2 {
        origin + self.offset + world.to_vec2() * self.zoom
    }

    pub fn screen_to_world(&self, screen: Pos2, origin: Pos2) -> Pos2 {
        ((screen - origin - self.offset) / self.zoom).to_pos2()
    }

    pub fn world_rect_to_screen(&self, rect: Rect, origin: Pos2) -> Rect {
        Rect::from_min_max(
            self.world_to_screen(rect.min, origin),
            self.world_to_screen(rect.max, origin),
        )
    }

    pub fn pan(&mut self, screen_delta: Vec2) {
        self.offset += screen_delta;
    }

    /// Multiply the zoom by `factor`, keeping the world point under
    /// `screen_anchor` fixed (zoom towards the cursor).
    pub fn zoom_around(&mut self, screen_anchor: Pos2, origin: Pos2, factor: f32) {
        let anchor_world = self.screen_to_world(screen_anchor, origin);
        self.zoom = (self.zoom * factor).clamp(MIN_ZOOM, MAX_ZOOM);
        self.offset = screen_anchor - origin - anchor_world.to_vec2() * self.zoom;
    }

    /// Fit `content` (world size) inside `view` (screen rect), centered,
    /// with a comfortable margin.
    pub fn fit(&mut self, content: Vec2, view: Rect) {
        const MARGIN: f32 = 48.0;
        let avail = (view.size() - Vec2::splat(MARGIN * 2.0)).max(Vec2::splat(1.0));
        let content = content.max(Vec2::splat(1.0));
        self.zoom = (avail.x / content.x)
            .min(avail.y / content.y)
            .clamp(MIN_ZOOM, MAX_ZOOM);
        self.offset = (view.size() - content * self.zoom) * 0.5;
        self.needs_fit = false;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use egui::{pos2, vec2};

    #[test]
    fn screen_world_round_trip() {
        let view = Viewport {
            offset: vec2(30.0, -12.0),
            zoom: 2.5,
            needs_fit: false,
        };
        let origin = pos2(56.0, 28.0);
        let world = pos2(123.0, 456.0);
        let back = view.screen_to_world(view.world_to_screen(world, origin), origin);
        assert!((back - world).length() < 1e-3);
    }

    #[test]
    fn zoom_keeps_anchor_fixed() {
        let mut view = Viewport {
            offset: vec2(10.0, 10.0),
            zoom: 1.0,
            needs_fit: false,
        };
        let origin = pos2(0.0, 0.0);
        let anchor = pos2(300.0, 200.0);
        let before = view.screen_to_world(anchor, origin);
        view.zoom_around(anchor, origin, 1.7);
        let after = view.screen_to_world(anchor, origin);
        assert!((before - after).length() < 1e-3);
        assert!((view.zoom - 1.7).abs() < 1e-6);
    }

    #[test]
    fn zoom_is_clamped() {
        let mut view = Viewport::default();
        view.zoom_around(Pos2::ZERO, Pos2::ZERO, 1e6);
        assert_eq!(view.zoom, MAX_ZOOM);
        view.zoom_around(Pos2::ZERO, Pos2::ZERO, 1e-9);
        assert_eq!(view.zoom, MIN_ZOOM);
    }

    #[test]
    fn fit_centers_content() {
        let mut view = Viewport::default();
        let screen = Rect::from_min_size(pos2(100.0, 50.0), vec2(1096.0, 696.0));
        view.fit(vec2(1000.0, 600.0), screen);
        assert!(!view.needs_fit);
        assert!((view.zoom - 1.0).abs() < 1e-6);
        let board = view.world_rect_to_screen(
            Rect::from_min_size(Pos2::ZERO, vec2(1000.0, 600.0)),
            screen.min,
        );
        assert!((board.center() - screen.center()).length() < 1e-3);
    }
}
