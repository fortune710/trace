use std::{
    fs,
    io::Read,
    path::{Path, PathBuf},
};

#[cfg(test)]
use std::sync::{Mutex, OnceLock};

use serde::Serialize;
use sha2::{Digest, Sha256};
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_fs::FsExt;
use walkdir::WalkDir;

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FolderPickerErrorCode {
    InvalidSelection,
    Missing,
    NotDirectory,
    PermissionDenied,
    Unreadable,
    ValidationFailed,
    SnapshotFailed,
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

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeSourceSnapshot {
    pub integrity_algorithm: String,
    pub digest: String,
}

const SNAPSHOT_ALGORITHM: &str = "sha256-directory-manifest-v1";
const EXCLUDED_DIRECTORIES: &[&str] = &[
    ".git",
    "node_modules",
    "bower_components",
    "jspm_packages",
    ".venv",
    "venv",
    "env",
    "vendor",
    ".bundle",
    "packages",
    ".pub-cache",
    "deps",
    "Pods",
    "Carthage",
    ".terraform",
];

#[cfg(test)]
type SnapshotReadHook = Box<dyn Fn(&Path) + Send + Sync>;

#[cfg(test)]
fn snapshot_read_hook() -> &'static Mutex<Option<SnapshotReadHook>> {
    static HOOK: OnceLock<Mutex<Option<SnapshotReadHook>>> = OnceLock::new();
    HOOK.get_or_init(|| Mutex::new(None))
}

#[cfg(test)]
fn run_snapshot_read_hook(path: &Path) {
    let hook = snapshot_read_hook().lock().expect("snapshot hook lock");
    if let Some(hook) = hook.as_ref() {
        hook(path);
    }
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

fn snapshot_error() -> FolderPickerError {
    validation_error(FolderPickerErrorCode::SnapshotFailed)
}

fn encode_record(hasher: &mut Sha256, marker: u8, path: &str, digest: Option<[u8; 32]>) {
    hasher.update([marker]);
    hasher.update((path.len() as u64).to_be_bytes());
    hasher.update(path.as_bytes());
    if let Some(digest) = digest {
        hasher.update(digest);
    }
}

fn digest_file(path: &Path) -> Result<[u8; 32], FolderPickerError> {
    let before = fs::metadata(path).map_err(|_| snapshot_error())?;
    #[cfg(test)]
    run_snapshot_read_hook(path);
    let mut file = fs::File::open(path).map_err(|_| snapshot_error())?;
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 65_536];
    loop {
        let count = file.read(&mut buffer).map_err(|_| snapshot_error())?;
        if count == 0 {
            break;
        }
        hasher.update(&buffer[..count]);
    }
    let after = fs::metadata(path).map_err(|_| snapshot_error())?;
    if before.len() != after.len() || before.modified().ok() != after.modified().ok() {
        return Err(snapshot_error());
    }
    Ok(hasher.finalize().into())
}

fn capture_snapshot(path: &Path) -> Result<NativeSourceSnapshot, FolderPickerError> {
    let root = fs::canonicalize(path).map_err(|_| snapshot_error())?;
    if !fs::metadata(&root).map_err(|_| snapshot_error())?.is_dir() {
        return Err(snapshot_error());
    }

    let mut entries = Vec::new();
    for entry in WalkDir::new(&root)
        .follow_links(false)
        .into_iter()
        .filter_entry(|entry| {
            entry
                .file_name()
                .to_str()
                .is_some_and(|name| !EXCLUDED_DIRECTORIES.contains(&name))
        })
    {
        let entry = entry.map_err(|_| snapshot_error())?;
        if entry.path() == root {
            continue;
        }
        let file_type = entry.file_type();
        if file_type.is_symlink() || (!file_type.is_dir() && !file_type.is_file()) {
            return Err(snapshot_error());
        }
        let relative = entry
            .path()
            .strip_prefix(&root)
            .map_err(|_| snapshot_error())?;
        let relative = relative.to_str().ok_or_else(snapshot_error)?;
        entries.push((
            relative.replace('\\', "/"),
            entry.path().to_path_buf(),
            file_type.is_dir(),
        ));
    }
    entries.sort_by(|left, right| left.0.cmp(&right.0));

    let mut hasher = Sha256::new();
    hasher.update(b"trace-local-source-snapshot\0v1\0");
    for (relative, path, is_directory) in entries {
        if is_directory {
            encode_record(&mut hasher, b'D', &relative, None);
        } else {
            encode_record(&mut hasher, b'F', &relative, Some(digest_file(&path)?));
        }
    }
    Ok(NativeSourceSnapshot {
        integrity_algorithm: SNAPSHOT_ALGORITHM.to_owned(),
        digest: format!("{:x}", hasher.finalize()),
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

#[tauri::command]
pub fn capture_local_source_snapshot(
    canonical_path: String,
) -> Result<NativeSourceSnapshot, FolderPickerError> {
    capture_snapshot(Path::new(&canonical_path))
}

#[cfg(test)]
mod tests {
    use std::{
        fs,
        sync::atomic::{AtomicU64, Ordering},
        time::{SystemTime, UNIX_EPOCH},
    };

    static TEMPORARY_DIRECTORY_ID: AtomicU64 = AtomicU64::new(0);

    use super::{
        EXCLUDED_DIRECTORIES, FolderPickerErrorCode, capture_snapshot, io_error_code,
        snapshot_read_hook, validate_folder, validate_selected_path,
    };

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

    #[test]
    fn snapshot_is_deterministic_and_changes_when_a_source_file_changes() {
        let directory = temporary_directory();
        fs::write(directory.join("main.rs"), "fn main() {}\n").expect("source file");
        fs::create_dir(directory.join("nested")).expect("nested directory");
        fs::write(
            directory.join("nested").join("lib.rs"),
            "pub fn value() -> u8 { 1 }\n",
        )
        .expect("nested source file");

        let first = capture_snapshot(&directory).expect("first snapshot");
        let repeat = capture_snapshot(&directory).expect("repeat snapshot");
        fs::write(
            directory.join("nested").join("lib.rs"),
            "pub fn value() -> u8 { 2 }\n",
        )
        .expect("updated source file");
        let changed = capture_snapshot(&directory).expect("changed snapshot");

        assert_eq!(first.integrity_algorithm, "sha256-directory-manifest-v1");
        assert_eq!(first.digest, repeat.digest);
        assert_ne!(first.digest, changed.digest);
        fs::remove_dir_all(directory).expect("temporary directory cleanup");
    }

    #[test]
    fn snapshot_ignores_dependency_directories_but_keeps_lockfiles() {
        let directory = temporary_directory();
        let lockfiles = [
            "package-lock.json",
            "bun.lock",
            "pnpm-lock.yaml",
            "yarn.lock",
            "requirements.txt",
            "requirements-dev.txt",
            "poetry.lock",
            "Pipfile.lock",
            "Cargo.lock",
            "go.sum",
            "composer.lock",
        ];
        for lockfile in lockfiles {
            fs::write(directory.join(lockfile), "version-one\n").expect("lockfile");
        }
        for excluded in EXCLUDED_DIRECTORIES {
            let excluded_directory = directory.join("nested").join(excluded);
            fs::create_dir_all(&excluded_directory).expect("excluded directory");
            fs::write(excluded_directory.join("ignored.txt"), "one").expect("ignored file");
        }

        let initial = capture_snapshot(&directory).expect("initial snapshot");
        for excluded in EXCLUDED_DIRECTORIES {
            fs::write(
                directory.join("nested").join(excluded).join("ignored.txt"),
                "two",
            )
            .expect("changed ignored file");
        }
        let dependency_changes = capture_snapshot(&directory).expect("dependency snapshot");

        assert_eq!(initial.digest, dependency_changes.digest);
        for lockfile in lockfiles {
            fs::write(directory.join(lockfile), "version-two\n").expect("changed lockfile");
            let lockfile_change = capture_snapshot(&directory).expect("lockfile snapshot");
            assert_ne!(
                initial.digest, lockfile_change.digest,
                "{lockfile} must be included"
            );
            fs::write(directory.join(lockfile), "version-one\n").expect("restored lockfile");
        }
        fs::remove_dir_all(directory).expect("temporary directory cleanup");
    }

    #[test]
    fn snapshot_uses_lexical_relative_path_order() {
        let first_directory = temporary_directory();
        let second_directory = temporary_directory();
        for (directory, names) in [
            (&first_directory, ["z.txt", "a.txt", "middle.txt"]),
            (&second_directory, ["middle.txt", "z.txt", "a.txt"]),
        ] {
            for name in names {
                fs::write(directory.join(name), name).expect("source file");
            }
        }

        assert_eq!(
            capture_snapshot(&first_directory)
                .expect("first snapshot")
                .digest,
            capture_snapshot(&second_directory)
                .expect("second snapshot")
                .digest,
        );
        fs::remove_dir_all(first_directory).expect("first directory cleanup");
        fs::remove_dir_all(second_directory).expect("second directory cleanup");
    }

    #[cfg(unix)]
    #[test]
    fn snapshot_rejects_a_symlink_without_exposing_its_path() {
        use std::os::unix::fs::symlink;

        let directory = temporary_directory();
        fs::write(directory.join("source.txt"), "source").expect("source file");
        symlink(directory.join("source.txt"), directory.join("source-link")).expect("file symlink");

        let error = capture_snapshot(&directory).expect_err("symlink should fail");

        assert!(matches!(error.code, FolderPickerErrorCode::SnapshotFailed));
        fs::remove_dir_all(directory).expect("temporary directory cleanup");
    }

    #[cfg(unix)]
    #[test]
    fn snapshot_rejects_a_directory_symlink_without_exposing_its_path() {
        use std::os::unix::fs::symlink;

        let directory = temporary_directory();
        let target = directory.join("target");
        fs::create_dir(&target).expect("target directory");
        symlink(&target, directory.join("target-link")).expect("directory symlink");

        let error = capture_snapshot(&directory).expect_err("symlink should fail");

        assert!(matches!(error.code, FolderPickerErrorCode::SnapshotFailed));
        fs::remove_dir_all(directory).expect("temporary directory cleanup");
    }

    #[cfg(unix)]
    #[test]
    fn snapshot_rejects_unreadable_and_special_inputs_without_paths() {
        use std::os::unix::fs::PermissionsExt;

        let unreadable_directory = temporary_directory();
        let unreadable_file = unreadable_directory.join("private.txt");
        fs::write(&unreadable_file, "private").expect("source file");
        let original_permissions = fs::metadata(&unreadable_file)
            .expect("file metadata")
            .permissions();
        let mut unreadable_permissions = original_permissions.clone();
        unreadable_permissions.set_mode(0o000);
        fs::set_permissions(&unreadable_file, unreadable_permissions).expect("deny read");

        let unreadable = capture_snapshot(&unreadable_directory).expect_err("unreadable file");

        fs::set_permissions(&unreadable_file, original_permissions).expect("restore read");
        assert!(matches!(
            unreadable.code,
            FolderPickerErrorCode::SnapshotFailed
        ));
        fs::remove_dir_all(unreadable_directory).expect("unreadable directory cleanup");

        let special_directory = temporary_directory();
        let _socket = match std::os::unix::net::UnixListener::bind(special_directory.join("socket"))
        {
            Ok(socket) => socket,
            Err(error) if error.kind() == std::io::ErrorKind::PermissionDenied => {
                fs::remove_dir_all(special_directory).expect("special directory cleanup");
                return;
            }
            Err(error) => panic!("unix socket: {error}"),
        };
        let special = capture_snapshot(&special_directory).expect_err("special file");

        assert!(matches!(
            special.code,
            FolderPickerErrorCode::SnapshotFailed
        ));
        fs::remove_dir_all(special_directory).expect("special directory cleanup");
    }

    #[cfg(unix)]
    #[test]
    fn snapshot_rejects_non_utf8_paths_without_exposing_them() {
        use std::os::unix::ffi::OsStringExt;

        let directory = temporary_directory();
        let invalid_name = std::ffi::OsString::from_vec(vec![b'i', b'n', b'v', 0xff]);
        match fs::write(directory.join(invalid_name), "source") {
            Ok(()) => {}
            Err(error)
                if error.kind() == std::io::ErrorKind::PermissionDenied
                    || error.kind() == std::io::ErrorKind::InvalidInput
                    || error.raw_os_error() == Some(92) =>
            {
                fs::remove_dir_all(directory).expect("temporary directory cleanup");
                return;
            }
            Err(error) => panic!("non-utf8 source: {error}"),
        }

        let error = capture_snapshot(&directory).expect_err("non-utf8 path");

        assert!(matches!(error.code, FolderPickerErrorCode::SnapshotFailed));
        fs::remove_dir_all(directory).expect("temporary directory cleanup");
    }

    #[test]
    fn snapshot_rejects_files_that_change_during_capture() {
        let directory = temporary_directory();
        let source = directory.join("changing.txt");
        fs::write(&source, "before").expect("source file");
        let source_for_hook = fs::canonicalize(&source).expect("canonical source path");
        *snapshot_read_hook().lock().expect("snapshot hook lock") = Some(Box::new(move |path| {
            if path == source_for_hook {
                fs::write(path, "changed during capture").expect("change source");
            }
        }));

        let error = capture_snapshot(&directory).expect_err("changed source");

        *snapshot_read_hook().lock().expect("snapshot hook lock") = None;
        assert!(matches!(error.code, FolderPickerErrorCode::SnapshotFailed));
        fs::remove_dir_all(directory).expect("temporary directory cleanup");
    }
}
