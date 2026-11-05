//! GOAT CREATIONS: The Greatest of All Time Open-Source Creative Suite.
//!
//! Application entry point. This file only owns the window lifecycle:
//! it configures the native window, hands control to eframe's event loop,
//! and lets [`app::GoatApp`] do everything else.
//!
//! Layout of the crate:
//! - [`app`]    : application state, event (action) routing, the frame loop.
//! - [`ui`]     : reusable widgets and panels: menu bar, toolbar, inspector, canvas.
//! - [`engine`] : the document model and editing pipeline (no UI code).

// Hide the console window on Windows release builds.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod app;
mod engine;
mod ui;

use std::sync::Arc;

/// Name shown in the title bar, the OS task switcher and used as the app id.
pub const APP_NAME: &str = "GOAT CREATIONS";

fn main() -> eframe::Result {
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_title(APP_NAME)
            .with_app_id("goat-creations")
            .with_inner_size([1440.0, 900.0])
            .with_min_inner_size([960.0, 600.0])
            .with_icon(Arc::new(ui::theme::app_icon())),
        ..Default::default()
    };

    eframe::run_native(
        APP_NAME,
        options,
        Box::new(|cc| Ok(Box::new(app::GoatApp::new(cc)))),
    )
}
