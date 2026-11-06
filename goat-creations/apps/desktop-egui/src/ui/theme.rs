//! GOAT CREATIONS look and feel: a minimalist dark theme with one accent,
//! "GOAT gold". All colors live in [`palette`] so the brand stays consistent.

use egui::{
    epaint::Shadow, Color32, CornerRadius, FontFamily, FontId, Stroke, TextStyle, Theme, Vec2,
};

/// Brand colors. Dark neutrals with a single warm accent.
pub mod palette {
    use egui::Color32;

    /// Deepest background: behind the artboard.
    pub const CANVAS_BG: Color32 = Color32::from_rgb(0x0B, 0x0C, 0x0F);
    /// Text fields and inset areas.
    pub const INSET: Color32 = Color32::from_rgb(0x0F, 0x11, 0x14);
    /// Panels (menu bar, toolbar, inspector, status bar).
    pub const PANEL: Color32 = Color32::from_rgb(0x15, 0x17, 0x1C);
    /// Raised surfaces: buttons, popups, windows.
    pub const RAISED: Color32 = Color32::from_rgb(0x1E, 0x21, 0x28);
    pub const HOVER: Color32 = Color32::from_rgb(0x27, 0x2B, 0x33);
    pub const PRESSED: Color32 = Color32::from_rgb(0x31, 0x36, 0x40);
    pub const BORDER: Color32 = Color32::from_rgb(0x2A, 0x2E, 0x36);
    pub const TEXT: Color32 = Color32::from_rgb(0xE7, 0xE9, 0xEC);
    pub const TEXT_DIM: Color32 = Color32::from_rgb(0x8C, 0x94, 0x9F);
    /// GOAT gold: the one accent color.
    pub const ACCENT: Color32 = Color32::from_rgb(0xF2, 0xB8, 0x2E);
    pub const ACCENT_SOFT: Color32 = Color32::from_rgb(0x3A, 0x30, 0x14);
    pub const DANGER: Color32 = Color32::from_rgb(0xF0, 0x6A, 0x5E);
    pub const SUCCESS: Color32 = Color32::from_rgb(0x5E, 0xD0, 0x8F);

    /// Quick-pick swatches in the inspector.
    pub const SWATCHES: [Color32; 8] = [
        ACCENT,
        Color32::from_rgb(0xF5, 0xF5, 0xF0),
        Color32::from_rgb(0x12, 0x12, 0x14),
        Color32::from_rgb(0xEF, 0x47, 0x47),
        Color32::from_rgb(0xFF, 0x8A, 0x3D),
        Color32::from_rgb(0x3D, 0xD6, 0xB0),
        Color32::from_rgb(0x4C, 0x8D, 0xFF),
        Color32::from_rgb(0xA8, 0x6B, 0xFF),
    ];
}

use palette::*;

/// Install the GOAT dark theme. Call once at start-up.
pub fn apply(ctx: &egui::Context) {
    // Always dark: the suite is designed for it, regardless of the OS setting.
    ctx.set_theme(Theme::Dark);
    ctx.set_visuals_of(Theme::Dark, visuals());
    ctx.style_mut_of(Theme::Dark, |style| {
        style.spacing.item_spacing = Vec2::new(8.0, 6.0);
        style.spacing.button_padding = Vec2::new(10.0, 4.0);
        style.spacing.interact_size.y = 24.0;
        style.spacing.menu_margin = egui::Margin::same(6);
        style.spacing.slider_width = 140.0;

        use FontFamily::{Monospace, Proportional};
        style.text_styles = [
            (TextStyle::Small, FontId::new(11.0, Proportional)),
            (TextStyle::Body, FontId::new(13.5, Proportional)),
            (TextStyle::Button, FontId::new(13.5, Proportional)),
            (TextStyle::Heading, FontId::new(18.0, Proportional)),
            (TextStyle::Monospace, FontId::new(12.5, Monospace)),
        ]
        .into();
    });
}

fn visuals() -> egui::Visuals {
    let mut v = egui::Visuals::dark();
    let radius = CornerRadius::same(6);

    v.override_text_color = None;
    v.panel_fill = PANEL;
    v.window_fill = RAISED;
    v.faint_bg_color = RAISED;
    v.extreme_bg_color = INSET;
    v.code_bg_color = INSET;
    v.hyperlink_color = ACCENT;
    v.warn_fg_color = ACCENT;
    v.error_fg_color = DANGER;

    v.window_stroke = Stroke::new(1.0, BORDER);
    v.window_corner_radius = CornerRadius::same(10);
    v.menu_corner_radius = CornerRadius::same(8);
    v.window_shadow = Shadow {
        offset: [0, 8],
        blur: 24,
        spread: 0,
        color: Color32::from_black_alpha(140),
    };
    v.popup_shadow = Shadow {
        offset: [0, 4],
        blur: 12,
        spread: 0,
        color: Color32::from_black_alpha(120),
    };

    v.selection.bg_fill = ACCENT_SOFT;
    v.selection.stroke = Stroke::new(1.0, ACCENT);

    let w = &mut v.widgets;
    w.noninteractive.bg_fill = PANEL;
    w.noninteractive.weak_bg_fill = PANEL;
    w.noninteractive.bg_stroke = Stroke::new(1.0, BORDER);
    w.noninteractive.fg_stroke = Stroke::new(1.0, TEXT);
    w.noninteractive.corner_radius = radius;

    w.inactive.bg_fill = RAISED;
    w.inactive.weak_bg_fill = RAISED;
    w.inactive.bg_stroke = Stroke::NONE;
    w.inactive.fg_stroke = Stroke::new(1.0, TEXT);
    w.inactive.corner_radius = radius;

    w.hovered.bg_fill = HOVER;
    w.hovered.weak_bg_fill = HOVER;
    w.hovered.bg_stroke = Stroke::new(1.0, BORDER);
    w.hovered.fg_stroke = Stroke::new(1.5, TEXT);
    w.hovered.corner_radius = radius;

    w.active.bg_fill = PRESSED;
    w.active.weak_bg_fill = PRESSED;
    w.active.bg_stroke = Stroke::new(1.0, ACCENT);
    w.active.fg_stroke = Stroke::new(1.5, TEXT);
    w.active.corner_radius = radius;

    w.open.bg_fill = RAISED;
    w.open.weak_bg_fill = HOVER;
    w.open.bg_stroke = Stroke::new(1.0, BORDER);
    w.open.fg_stroke = Stroke::new(1.0, TEXT);
    w.open.corner_radius = radius;

    v
}

/// Window / taskbar icon, drawn in code so the binary needs no image files:
/// a gold rounded square with a dark "G"-like ring cut into it.
pub fn app_icon() -> egui::IconData {
    const N: u32 = 64;
    let mut rgba = Vec::with_capacity((N * N * 4) as usize);
    let c = (N as f32 - 1.0) / 2.0;
    for y in 0..N {
        for x in 0..N {
            let (fx, fy) = (x as f32 - c, y as f32 - c);
            // Rounded-square mask (superellipse).
            let inside = (fx.abs() / 31.0).powi(5) + (fy.abs() / 31.0).powi(5) <= 1.0;
            let r = (fx * fx + fy * fy).sqrt();
            let ring = (13.0..=21.0).contains(&r);
            // Open the ring on the right (like a "G"), then add its crossbar.
            let gap = fx > 4.0 && fy < 0.0 && fy > -21.0;
            let bar = (0.0..=21.0).contains(&fx) && (-1.0..=5.0).contains(&fy) && r <= 21.0;
            let [r8, g8, b8, _] = if (ring && !gap) || bar {
                CANVAS_BG
            } else {
                ACCENT
            }
            .to_array();
            rgba.extend_from_slice(&[r8, g8, b8, if inside { 255 } else { 0 }]);
        }
    }
    egui::IconData {
        rgba,
        width: N,
        height: N,
    }
}
