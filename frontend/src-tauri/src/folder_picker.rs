use std::{
    fs,
    path::{Path, PathBuf},
};

use serde::Serialize;
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_fs::FsExt;

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FolderPickerErrorCode {
    InvalidSelection,
    Missing,
    NotDirectory,
    PermissionDenied,
    Unreadable,
    ValidationFailed,
}

#[derive(Debug, Clone, Serialize)]
pub struct FolderPickerError {
    pub code: FolderPickerErrorCode,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeFolderSelection {
    pub canonical_path: String,
    pub display_name: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeFolderValidation {
    pub display_name: String,
}

fn io_error_code(error: &std::io::Error) -> FolderPickerErrorCode {
    match error.kind() {
        std::io::ErrorKind::NotFound => FolderPickerErrorCode::Missing,
        std::io::ErrorKind::PermissionDenied => FolderPickerErrorCode::PermissionDenied,
        _ => FolderPickerErrorCode::Unreadable,
    }
}

fn validation_error(code: FolderPickerErrorCode) -> FolderPickerError {
    FolderPickerError { code }
}

fn validate_selected_path(
    selected_path: Option<PathBuf>,
) -> Result<Option<NativeFolderSelection>, FolderPickerError> {
    selected_path.map(|path| validate_folder(&path)).transpose()
}

pub fn validate_folder(path: &Path) -> Result<NativeFolderSelection, FolderPickerError> {
    let canonical_path =
        fs::canonicalize(path).map_err(|error| validation_error(io_error_code(&error)))?;
    let metadata =
        fs::metadata(&canonical_path).map_err(|error| validation_error(io_error_code(&error)))?;

    if !metadata.is_dir() {
        return Err(validation_error(FolderPickerErrorCode::NotDirectory));
    }

    fs::read_dir(&canonical_path).map_err(|error| validation_error(io_error_code(&error)))?;

    let display_name = canonical_path
        .file_name()
        .and_then(|name| name.to_str())
        .filter(|name| !name.is_empty())
        .unwrap_or("Selected folder")
        .to_owned();

    Ok(NativeFolderSelection {
        canonical_path: canonical_path.to_string_lossy().into_owned(),
        display_name,
    })
}

#[tauri::command]
pub async fn pick_local_folder(
    app: tauri::AppHandle,
) -> Result<Option<NativeFolderSelection>, FolderPickerError> {
    #[cfg(debug_assertions)]
    if let Ok(test_path) = std::env::var("TRACE_E2E_PICKER_PATH") {
        if test_path == "__cancel__" {
            return Ok(None);
        }

        let validated = validate_folder(Path::new(&test_path))?;
        let canonical_path = PathBuf::from(&validated.canonical_path);
        app.fs_scope()
            .allow_directory(canonical_path, true)
            .map_err(|_| validation_error(FolderPickerErrorCode::ValidationFailed))?;
        return Ok(Some(validated));
    }

    let dialog_app = app.clone();
    let selected = tauri::async_runtime::spawn_blocking(move || {
        dialog_app
            .dialog()
            .file()
            .set_title("Choose a local project folder")
            .set_can_create_directories(false)
            .blocking_pick_folder()
    })
    .await
    .map_err(|_| validation_error(FolderPickerErrorCode::ValidationFailed))?;

    let selected_path = selected
        .map(|selected| {
            selected
                .into_path()
                .map_err(|_| validation_error(FolderPickerErrorCode::InvalidSelection))
        })
        .transpose()?;
    let Some(validated) = validate_selected_path(selected_path)? else {
        return Ok(None);
    };
    let canonical_path = PathBuf::from(&validated.canonical_path);

    app.fs_scope()
        .allow_directory(canonical_path, true)
        .map_err(|_| validation_error(FolderPickerErrorCode::ValidationFailed))?;

    Ok(Some(validated))
}

#[tauri::command]
pub fn validate_local_folder(
    canonical_path: String,
) -> Result<NativeFolderValidation, FolderPickerError> {
    let validated = validate_folder(Path::new(&canonical_path))?;
    Ok(NativeFolderValidation {
        display_name: validated.display_name,
    })
}

#[cfg(test)]
mod tests {
    use std::{
        fs,
        sync::atomic::{AtomicU64, Ordering},
        time::{SystemTime, UNIX_EPOCH},
    };

    static TEMPORARY_DIRECTORY_ID: AtomicU64 = AtomicU64::new(0);

    use super::{FolderPickerErrorCode, io_error_code, validate_folder, validate_selected_path};

    fn temporary_directory() -> std::path::PathBuf {
        let suffix = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock")
            .as_nanos();
        for attempt in 0..100 {
            let id = TEMPORARY_DIRECTORY_ID.fetch_add(1, Ordering::Relaxed);
            let path =
                std::env::temp_dir().join(format!("trace-folder-picker-{suffix}-{id}-{attempt}"));
            if fs::create_dir(&path).is_ok() {
                return path;
            }
        }
        panic!("temporary directory could not be created")
    }

    #[test]
    fn validates_a_directory_without_exposing_an_error_path() {
        let directory = temporary_directory();

        let result = validate_folder(&directory).expect("directory should validate");

        assert!(result.display_name.starts_with("trace-folder-picker-"));
        assert!(result.canonical_path.contains("trace-folder-picker-"));
        fs::remove_dir_all(directory).expect("temporary directory cleanup");
    }

    #[test]
    fn rejects_a_missing_directory() {
        let directory = temporary_directory();
        let missing = directory.join("missing");

        let error = validate_folder(&missing).expect_err("missing directory should fail");

        assert!(matches!(error.code, FolderPickerErrorCode::Missing));
        fs::remove_dir_all(directory).expect("temporary directory cleanup");
    }

    #[test]
    fn cancellation_does_not_validate_or_create_a_selection() {
        let result = validate_selected_path(None).expect("cancellation should be successful");

        assert!(result.is_none());
    }

    #[test]
    fn rejects_a_file_as_a_folder() {
        let directory = temporary_directory();
        let file = directory.join("project.txt");
        fs::write(&file, "content").expect("file should be created");

        let error = validate_folder(&file).expect_err("file should fail");

        assert!(matches!(error.code, FolderPickerErrorCode::NotDirectory));
        fs::remove_dir_all(directory).expect("temporary directory cleanup");
    }

    #[test]
    fn rejects_a_path_that_changes_from_directory_to_file() {
        let directory = temporary_directory();
        let changing_path = directory.join("changing");
        fs::create_dir(&changing_path).expect("directory should be created");
        fs::remove_dir(&changing_path).expect("directory should be removed");
        fs::write(&changing_path, "now a file").expect("file should be created");

        let error = validate_folder(&changing_path).expect_err("file should fail");

        assert!(matches!(error.code, FolderPickerErrorCode::NotDirectory));
        fs::remove_dir_all(directory).expect("temporary directory cleanup");
    }

    #[test]
    fn maps_permission_denied_errors_to_a_stable_code() {
        let error = std::io::Error::new(std::io::ErrorKind::PermissionDenied, "denied");

        assert!(matches!(
            io_error_code(&error),
            FolderPickerErrorCode::PermissionDenied
        ));
    }

    #[test]
    fn maps_other_io_errors_to_unreadable() {
        let error = std::io::Error::new(std::io::ErrorKind::Other, "unreadable");

        assert!(matches!(
            io_error_code(&error),
            FolderPickerErrorCode::Unreadable
        ));
    }

    #[cfg(unix)]
    #[test]
    fn rejects_a_directory_without_read_permission() {
        use std::os::unix::fs::PermissionsExt;

        let directory = temporary_directory();
        let original_permissions = fs::metadata(&directory)
            .expect("directory metadata")
            .permissions();
        let mut denied_permissions = original_permissions.clone();
        denied_permissions.set_mode(0o000);
        fs::set_permissions(&directory, denied_permissions).expect("permissions should be denied");

        let result = validate_folder(&directory);

        fs::set_permissions(&directory, original_permissions)
            .expect("permissions should be restored");
        assert!(matches!(
            result.expect_err("unreadable directory should fail").code,
            FolderPickerErrorCode::PermissionDenied | FolderPickerErrorCode::Unreadable
        ));
        fs::remove_dir_all(directory).expect("temporary directory cleanup");
    }

    #[cfg(windows)]
    #[test]
    fn rejects_a_directory_without_read_permission() {
        use std::process::Command;

        let directory = temporary_directory();
        let directory_string = directory.to_string_lossy().into_owned();
        let account = String::from_utf8(
            Command::new("whoami")
                .output()
                .expect("whoami should be available")
                .stdout,
        )
        .expect("whoami output should be UTF-8")
        .trim()
        .to_owned();

        let deny_status = Command::new("icacls")
            .args([
                &directory_string,
                "/deny",
                &format!("{account}:(OI)(CI)(RX)"),
            ])
            .status()
            .expect("icacls should be available");
        assert!(deny_status.success(), "icacls should deny directory access");

        let result = validate_folder(&directory);

        let restore_status = Command::new("icacls")
            .args([&directory_string, "/remove:d", &account])
            .status()
            .expect("icacls should restore directory access");
        assert!(
            restore_status.success(),
            "icacls should restore directory access"
        );

        assert!(matches!(
            result.expect_err("unreadable directory should fail").code,
            FolderPickerErrorCode::PermissionDenied | FolderPickerErrorCode::Unreadable
        ));
        fs::remove_dir_all(directory).expect("temporary directory cleanup");
    }

    #[cfg(unix)]
    #[test]
    fn follows_a_valid_directory_symlink() {
        use std::os::unix::fs::symlink;

        let directory = temporary_directory();
        let target = directory.join("target");
        let link = directory.join("link");
        fs::create_dir(&target).expect("target directory");
        symlink(&target, &link).expect("directory symlink");

        let result = validate_folder(&link).expect("valid symlink should validate");

        assert_eq!(result.display_name, "target");
        fs::remove_dir_all(directory).expect("temporary directory cleanup");
    }

    #[cfg(unix)]
    #[test]
    fn rejects_a_broken_directory_symlink() {
        use std::os::unix::fs::symlink;

        let directory = temporary_directory();
        let link = directory.join("broken-link");
        symlink(directory.join("missing"), &link).expect("broken directory symlink");

        let error = validate_folder(&link).expect_err("broken symlink should fail");

        assert!(matches!(error.code, FolderPickerErrorCode::Missing));
        fs::remove_dir_all(directory).expect("temporary directory cleanup");
    }
}
