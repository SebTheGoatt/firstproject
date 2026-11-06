//! Saving and opening `.goat.json` project files.
//!
//! The file wraps the document in a small header so future versions can
//! recognise and migrate older files.

use std::fmt;
use std::path::Path;

use serde::{Deserialize, Serialize};

use super::document::Document;

/// Marker written into every project file.
const FORMAT: &str = "goat-creations";
/// Bump when the document layout changes in a way that needs migration.
const VERSION: u32 = 1;

#[derive(Serialize, Deserialize)]
struct ProjectFile {
    format: String,
    version: u32,
    document: Document,
}

/// Why a project could not be saved or opened.
#[derive(Debug)]
pub enum ProjectError {
    Io(std::io::Error),
    Format(serde_json::Error),
    NotAProject,
    TooNew(u32),
}

impl fmt::Display for ProjectError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ProjectError::Io(e) => write!(f, "{e}"),
            ProjectError::Format(e) => write!(f, "not a valid project file ({e})"),
            ProjectError::NotAProject => write!(f, "this file is not a GOAT CREATIONS project"),
            ProjectError::TooNew(v) => {
                write!(
                    f,
                    "project was saved by a newer version (format {v}); please update"
                )
            }
        }
    }
}

impl std::error::Error for ProjectError {}

impl From<std::io::Error> for ProjectError {
    fn from(e: std::io::Error) -> Self {
        ProjectError::Io(e)
    }
}

impl From<serde_json::Error> for ProjectError {
    fn from(e: serde_json::Error) -> Self {
        ProjectError::Format(e)
    }
}

/// Serialize a document to project-file JSON.
pub fn to_json(doc: &Document) -> Result<String, ProjectError> {
    let file = ProjectFile {
        format: FORMAT.to_owned(),
        version: VERSION,
        document: doc.clone(),
    };
    Ok(serde_json::to_string_pretty(&file)?)
}

/// Parse project-file JSON back into a document.
pub fn from_json(json: &str) -> Result<Document, ProjectError> {
    let file: ProjectFile = serde_json::from_str(json)?;
    if file.format != FORMAT {
        return Err(ProjectError::NotAProject);
    }
    if file.version > VERSION {
        return Err(ProjectError::TooNew(file.version));
    }
    let mut doc = file.document;
    doc.repair();
    Ok(doc)
}

/// Write the document to `path`. Writes to a temporary file first and then
/// renames it, so a crash mid-save never leaves a half-written project.
pub fn save(doc: &Document, path: &Path) -> Result<(), ProjectError> {
    let json = to_json(doc)?;
    let tmp = path.with_extension("tmp");
    std::fs::write(&tmp, json)?;
    std::fs::rename(&tmp, path)?;
    Ok(())
}

/// Read a document from `path`.
pub fn load(path: &Path) -> Result<Document, ProjectError> {
    let json = std::fs::read_to_string(path)?;
    from_json(&json)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::document::{ElementKind, ShapeKind};
    use egui::{pos2, Color32, Rect};

    #[test]
    fn json_round_trip_keeps_elements() {
        let mut doc = Document::default();
        doc.add(
            ElementKind::Shape {
                kind: ShapeKind::Ellipse,
                rect: Rect::from_min_max(pos2(1.0, 2.0), pos2(30.0, 40.0)),
                stroke_width: 3.0,
                filled: true,
            },
            Color32::from_rgb(1, 2, 3),
        );
        doc.add(
            ElementKind::Text {
                pos: pos2(5.0, 5.0),
                content: "GOAT".into(),
                size: 48.0,
                measured: None,
            },
            Color32::WHITE,
        );

        let back = from_json(&to_json(&doc).unwrap()).unwrap();
        assert_eq!(back.elements.len(), 2);
        assert_eq!(back.elements[0].color, Color32::from_rgb(1, 2, 3));
        assert!(
            matches!(back.elements[1].kind, ElementKind::Text { ref content, .. } if content == "GOAT")
        );
    }

    #[test]
    fn rejects_foreign_and_future_files() {
        let foreign = r#"{"format":"other","version":1,"document":{"width":1,"height":1,"background":[0,0,0,255],"elements":[],"next_id":1}}"#;
        assert!(matches!(from_json(foreign), Err(ProjectError::NotAProject)));

        let json = to_json(&Document::default())
            .unwrap()
            .replace("\"version\": 1", "\"version\": 99");
        assert!(matches!(from_json(&json), Err(ProjectError::TooNew(99))));
    }

    #[test]
    fn save_and_load_from_disk() {
        let dir = std::env::temp_dir().join(format!("goat-io-test-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("art.goat.json");

        let mut doc = Document::default();
        doc.add(
            ElementKind::Stroke {
                points: vec![pos2(0.0, 0.0), pos2(9.0, 9.0)],
                width: 4.0,
            },
            Color32::RED,
        );
        save(&doc, &path).unwrap();
        let back = load(&path).unwrap();
        assert_eq!(back.elements.len(), 1);

        std::fs::remove_dir_all(&dir).ok();
    }
}
