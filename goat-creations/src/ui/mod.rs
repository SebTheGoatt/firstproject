//! Reusable UI building blocks. Each panel is a plain function that draws
//! into a `Ui` and reports what the user asked for as [`crate::app::Action`]s,
//! so all state changes are routed through one place in `app.rs`.

pub mod canvas;
pub mod inspector;
pub mod menu_bar;
pub mod status_bar;
pub mod theme;
pub mod toolbar;
pub mod widgets;
