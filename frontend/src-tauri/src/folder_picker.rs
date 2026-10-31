use std::{
    collections::HashSet,
    fs,
    io::{Read, Write},
    path::{Path, PathBuf},
};

#[cfg(test)]
use std::sync::{Mutex, OnceLock};

use base64::Engine as _;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tauri::Manager;
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
    SnapshotUploadTooLarge,
    InvalidDiff,
    SourceChanged,
    ApplyFailed,
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

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeStoredSourceSnapshot {
    pub snapshot_id: String,
    pub integrity_algorithm: String,
    pub digest: String,
    pub upload: NativeLocalSourceUpload,
}

#[derive(Debug, Clone, Serialize)]
pub struct NativeLocalSourceEntry {
    path: String,
    directory: bool,
    content_base64: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct NativeLocalSourceUpload {
    digest: String,
    entries: Vec<NativeLocalSourceEntry>,
}

fn snapshot_upload(
    root: &Path,
    digest: &str,
) -> Result<NativeLocalSourceUpload, FolderPickerError> {
    let mut entries = Vec::new();
    let mut total = 0;
    for entry in WalkDir::new(root).follow_links(false) {
        let entry = entry.map_err(|_| snapshot_error())?;
        if entry.path() == root {
            continue;
        }
        if entries.len() == 3000 {
            return Err(FolderPickerError {
                code: FolderPickerErrorCode::SnapshotUploadTooLarge,
            });
        }
        if entry.file_type().is_symlink() {
            return Err(snapshot_error());
        }
        let path = entry
            .path()
            .strip_prefix(root)
            .map_err(|_| snapshot_error())?
            .to_str()
            .ok_or_else(snapshot_error)?
            .replace('\\', "/");
        if !is_safe_relative_path(&path) {
            return Err(snapshot_error());
        }
        let directory = entry.file_type().is_dir();
        let content_base64 = if directory {
            None
        } else {
            if !entry.file_type().is_file() {
                return Err(snapshot_error());
            }
            if entry.metadata().map_err(|_| snapshot_error())?.len() > 256_000 {
                return Err(FolderPickerError {
                    code: FolderPickerErrorCode::SnapshotUploadTooLarge,
                });
            }
            let bytes = fs::read(entry.path()).map_err(|_| snapshot_error())?;
            total += bytes.len();
            if bytes.len() > 256_000 || total > 4_000_000 {
                return Err(FolderPickerError {
                    code: FolderPickerErrorCode::SnapshotUploadTooLarge,
                });
            }
            Some(base64::engine::general_purpose::STANDARD.encode(bytes))
        };
        entries.push(NativeLocalSourceEntry {
            path,
            directory,
            content_base64,
        });
    }
    entries.sort_by(|left, right| left.path.cmp(&right.path));
    Ok(NativeLocalSourceUpload {
        digest: digest.to_owned(),
        entries,
    })
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeLocalRemediationFile {
    pub file_path: String,
    pub backup_reference: String,
    pub source_hash: String,
    pub applied_hash: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeLocalRemediationResult {
    pub files: Vec<NativeLocalRemediationFile>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct NativeExecutablePatchFile {
    path: String,
    operation: String,
    original_sha256: Option<String>,
    result_sha256: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct NativeExecutablePatch {
    diff: String,
    sha256: String,
    files: Vec<NativeExecutablePatchFile>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeLocalRemediationRestoreFile {
    pub file_path: String,
    pub backup_reference: String,
    pub applied_hash: String,
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
type WriteFailureHook = Box<dyn Fn(&Path) -> bool + Send + Sync>;

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

#[cfg(test)]
fn write_failure_hook() -> &'static Mutex<Option<WriteFailureHook>> {
    static HOOK: OnceLock<Mutex<Option<WriteFailureHook>>> = OnceLock::new();
    HOOK.get_or_init(|| Mutex::new(None))
}

#[cfg(test)]
fn should_fail_write(path: &Path) -> bool {
    write_failure_hook()
        .lock()
        .expect("write failure hook lock")
        .as_ref()
        .is_some_and(|hook| hook(path))
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

fn apply_error(code: FolderPickerErrorCode) -> FolderPickerError {
    validation_error(code)
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

fn copy_source_snapshot(
    source_root: &Path,
    destination_root: &Path,
) -> Result<NativeSourceSnapshot, FolderPickerError> {
    let expected = capture_snapshot(source_root)?;
    let source_root = fs::canonicalize(source_root).map_err(|_| snapshot_error())?;
    if destination_root.exists() {
        return Err(snapshot_error());
    }
    fs::create_dir_all(destination_root).map_err(|_| snapshot_error())?;

    let copy_result = (|| -> Result<(), FolderPickerError> {
        for entry in WalkDir::new(&source_root)
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
            if entry.path() == source_root {
                continue;
            }
            let file_type = entry.file_type();
            if file_type.is_symlink() || (!file_type.is_dir() && !file_type.is_file()) {
                return Err(snapshot_error());
            }
            let relative = entry
                .path()
                .strip_prefix(&source_root)
                .map_err(|_| snapshot_error())?;
            if relative.to_str().is_none() {
                return Err(snapshot_error());
            }
            let destination = destination_root.join(relative);
            if file_type.is_dir() {
                fs::create_dir_all(destination).map_err(|_| snapshot_error())?;
            } else {
                let parent = destination.parent().ok_or_else(snapshot_error)?;
                fs::create_dir_all(parent).map_err(|_| snapshot_error())?;
                fs::copy(entry.path(), destination).map_err(|_| snapshot_error())?;
            }
        }
        Ok(())
    })();
    if copy_result.is_err() {
        let _ = fs::remove_dir_all(destination_root);
    }
    copy_result?;
    let copied = capture_snapshot(destination_root)?;
    if copied.digest != expected.digest {
        let _ = fs::remove_dir_all(destination_root);
        return Err(snapshot_error());
    }
    Ok(copied)
}

fn is_safe_relative_path(path: &str) -> bool {
    if cfg!(windows)
        && (path.chars().any(|value| "<>:\"|?*".contains(value))
            || path
                .split('/')
                .any(|part| part.ends_with('.') || part.ends_with(' ')))
    {
        return false;
    }
    !path.is_empty()
        && !path.starts_with('/')
        && !path.contains('\\')
        && !path.chars().any(|value| value.is_control())
        && !path.as_bytes().get(1).is_some_and(|value| *value == b':')
        && path
            .split('/')
            .all(|part| !matches!(part, "" | "." | "..") && !part.eq_ignore_ascii_case(".git"))
}

#[derive(Debug, Clone)]
struct PatchHunk {
    old_start: usize,
    old_count: usize,
    new_count: usize,
    lines: Vec<(char, String)>,
}

#[derive(Debug, Clone)]
struct SingleFilePatch {
    path: String,
    create: bool,
    hunks: Vec<PatchHunk>,
}

fn parse_hunk_header(value: &str) -> Option<(usize, usize, usize)> {
    let body = value.strip_prefix("@@ -")?.split_once(" +")?;
    let old = body.0;
    let new = body.1.split_once(" @@")?.0;

    fn range(value: &str) -> Option<(usize, usize)> {
        let (start, count) = value.split_once(',').unwrap_or((value, "1"));
        Some((start.parse().ok()?, count.parse().ok()?))
    }

    let (old_start, old_count) = range(old)?;
    let (_, new_count) = range(new)?;
    Some((old_start, old_count, new_count))
}

fn is_git_index_line(line: &str) -> bool {
    let Some((old_hash, new_and_mode)) = line
        .strip_prefix("index ")
        .and_then(|value| value.split_once(".."))
    else {
        return false;
    };
    let mut new_and_mode = new_and_mode.split_whitespace();
    let Some(new_hash) = new_and_mode.next() else {
        return false;
    };
    let mode_is_valid = match new_and_mode.next() {
        Some(mode) => mode.len() == 6 && mode.chars().all(|character| character.is_ascii_digit()),
        None => true,
    };

    old_hash
        .chars()
        .all(|character| character.is_ascii_hexdigit())
        && !old_hash.is_empty()
        && new_hash
            .chars()
            .all(|character| character.is_ascii_hexdigit())
        && !new_hash.is_empty()
        && mode_is_valid
        && new_and_mode.next().is_none()
}

fn parse_single_file_patch(diff: &str) -> Result<SingleFilePatch, FolderPickerError> {
    if !diff.starts_with("diff --git ") {
        return Err(apply_error(FolderPickerErrorCode::InvalidDiff));
    }

    let mut lines = diff.split_terminator('\n');
    let header = lines
        .next()
        .ok_or_else(|| apply_error(FolderPickerErrorCode::InvalidDiff))?;
    let raw = header
        .strip_prefix("diff --git ")
        .ok_or_else(|| apply_error(FolderPickerErrorCode::InvalidDiff))?;
    let (old, new) = if raw.starts_with('"') {
        let mut stream = serde_json::Deserializer::from_str(raw).into_iter::<String>();
        let old = stream
            .next()
            .and_then(Result::ok)
            .ok_or_else(|| apply_error(FolderPickerErrorCode::InvalidDiff))?;
        let new = stream
            .next()
            .and_then(Result::ok)
            .ok_or_else(|| apply_error(FolderPickerErrorCode::InvalidDiff))?;
        (old, new)
    } else {
        let (old, new) = raw
            .match_indices(" b/")
            .filter_map(|(index, _)| {
                let old = &raw[..index];
                let new = &raw[index + 3..];
                (old.strip_prefix("a/") == Some(new)).then_some((old, new))
            })
            .next()
            .ok_or_else(|| apply_error(FolderPickerErrorCode::InvalidDiff))?;
        (old.to_owned(), format!("b/{new}"))
    };
    let path = old
        .strip_prefix("a/")
        .ok_or_else(|| apply_error(FolderPickerErrorCode::InvalidDiff))?
        .to_owned();
    if new != format!("b/{path}")
        || !is_safe_relative_path(&path)
        || path
            .split('/')
            .any(|part| part.eq_ignore_ascii_case(".git"))
    {
        return Err(apply_error(FolderPickerErrorCode::InvalidDiff));
    }

    let mut old_header = lines
        .next()
        .ok_or_else(|| apply_error(FolderPickerErrorCode::InvalidDiff))?;
    let create = old_header == "new file mode 100644";
    if old_header.starts_with("new file mode ") && !create {
        return Err(apply_error(FolderPickerErrorCode::InvalidDiff));
    }
    if create {
        old_header = lines
            .next()
            .ok_or_else(|| apply_error(FolderPickerErrorCode::InvalidDiff))?;
    }
    if old_header.starts_with("index ") {
        if !is_git_index_line(old_header) {
            return Err(apply_error(FolderPickerErrorCode::InvalidDiff));
        }
        if let Some(value) = lines.next() {
            old_header = value;
        } else if create {
            return Ok(SingleFilePatch {
                path,
                create,
                hunks: Vec::new(),
            });
        } else {
            return Err(apply_error(FolderPickerErrorCode::InvalidDiff));
        }
    }
    let new_header = lines
        .next()
        .ok_or_else(|| apply_error(FolderPickerErrorCode::InvalidDiff))?;
    fn decoded_header(value: &str, prefix: &str) -> Option<String> {
        let path = value.strip_prefix(prefix)?;
        if path.starts_with('"') {
            serde_json::from_str(path).ok()
        } else {
            Some(path.to_owned())
        }
    }
    let expected_old = if create {
        "/dev/null".to_owned()
    } else {
        format!("a/{path}")
    };
    if decoded_header(old_header, "--- ") != Some(expected_old)
        || decoded_header(new_header, "+++ ") != Some(format!("b/{path}"))
    {
        return Err(apply_error(FolderPickerErrorCode::InvalidDiff));
    }

    let mut hunks = Vec::new();
    let mut current: Option<PatchHunk> = None;
    for line in lines {
        if line.starts_with("diff --git ") {
            return Err(apply_error(FolderPickerErrorCode::InvalidDiff));
        }
        if line.starts_with("@@ -") {
            if let Some(hunk) = current.take() {
                hunks.push(hunk);
            }
            let (old_start, old_count, new_count) = parse_hunk_header(line)
                .ok_or_else(|| apply_error(FolderPickerErrorCode::InvalidDiff))?;
            current = Some(PatchHunk {
                old_start,
                old_count,
                new_count,
                lines: Vec::new(),
            });
            continue;
        }
        if line == "\\ No newline at end of file" {
            let last_kind = current
                .as_ref()
                .and_then(|hunk| hunk.lines.last())
                .map(|(kind, _)| *kind)
                .ok_or_else(|| apply_error(FolderPickerErrorCode::InvalidDiff))?;
            let _ = last_kind;
            if let Some((_, text)) = current.as_mut().and_then(|hunk| hunk.lines.last_mut()) {
                if text.ends_with('\n') {
                    text.pop();
                }
            }
            continue;
        }
        let hunk = current
            .as_mut()
            .ok_or_else(|| apply_error(FolderPickerErrorCode::InvalidDiff))?;
        let (kind, value) = line
            .chars()
            .next()
            .filter(|kind| matches!(kind, ' ' | '+' | '-'))
            .map(|kind| (kind, format!("{}\n", &line[1..])))
            .ok_or_else(|| apply_error(FolderPickerErrorCode::InvalidDiff))?;
        hunk.lines.push((kind, value));
    }
    if let Some(hunk) = current {
        hunks.push(hunk);
    }
    if hunks.is_empty() {
        return Err(apply_error(FolderPickerErrorCode::InvalidDiff));
    }
    for hunk in &hunks {
        let old_count = hunk.lines.iter().filter(|(kind, _)| *kind != '+').count();
        let new_count = hunk.lines.iter().filter(|(kind, _)| *kind != '-').count();
        if old_count != hunk.old_count || new_count != hunk.new_count {
            return Err(apply_error(FolderPickerErrorCode::InvalidDiff));
        }
    }
    Ok(SingleFilePatch {
        path,
        create,
        hunks,
    })
}

fn parse_patches(diff: &str) -> Result<Vec<SingleFilePatch>, FolderPickerError> {
    if !diff.starts_with("diff --git ") {
        return Err(apply_error(FolderPickerErrorCode::InvalidDiff));
    }

    let mut patches = Vec::new();
    let mut paths = HashSet::new();
    for (index, chunk) in diff.split("\ndiff --git ").enumerate() {
        let file_diff = if index == 0 {
            chunk.to_owned()
        } else {
            format!("diff --git {chunk}")
        };
        let patch = parse_single_file_patch(&file_diff)?;
        if !paths.insert(patch.path.clone()) {
            return Err(apply_error(FolderPickerErrorCode::InvalidDiff));
        }
        patches.push(patch);
    }
    if patches.is_empty() {
        return Err(apply_error(FolderPickerErrorCode::InvalidDiff));
    }
    Ok(patches)
}

fn apply_patch_to_text(source: &str, patch: &SingleFilePatch) -> Result<String, FolderPickerError> {
    let source_lines: Vec<&str> = source.split_inclusive('\n').collect();
    let mut output = Vec::new();
    let mut source_index = 0usize;

    for hunk in &patch.hunks {
        let hunk_start = if hunk.old_count == 0 {
            hunk.old_start
        } else {
            hunk.old_start
                .checked_sub(1)
                .ok_or_else(|| apply_error(FolderPickerErrorCode::InvalidDiff))?
        };
        if hunk_start < source_index || hunk_start > source_lines.len() {
            return Err(apply_error(FolderPickerErrorCode::SourceChanged));
        }
        output.extend_from_slice(&source_lines[source_index..hunk_start]);
        source_index = hunk_start;
        for (kind, value) in &hunk.lines {
            match kind {
                ' ' => {
                    if source_lines.get(source_index) != Some(&value.as_str()) {
                        return Err(apply_error(FolderPickerErrorCode::SourceChanged));
                    }
                    output.push(value.as_str());
                    source_index += 1;
                }
                '-' => {
                    if source_lines.get(source_index) != Some(&value.as_str()) {
                        return Err(apply_error(FolderPickerErrorCode::SourceChanged));
                    }
                    source_index += 1;
                }
                '+' => output.push(value.as_str()),
                _ => return Err(apply_error(FolderPickerErrorCode::InvalidDiff)),
            }
        }
    }
    output.extend_from_slice(&source_lines[source_index..]);
    Ok(output.concat())
}

fn sha256_hex(value: &[u8]) -> String {
    format!("{:x}", Sha256::digest(value))
}

struct PreparedLocalRemediationFile {
    path: String,
    target: PathBuf,
    source_bytes: Vec<u8>,
    applied_bytes: Vec<u8>,
    backup_reference: PathBuf,
    created: bool,
}

fn prepare_local_remediation_files(
    root: &Path,
    diff: &str,
) -> Result<Vec<PreparedLocalRemediationFile>, FolderPickerError> {
    let root =
        fs::canonicalize(root).map_err(|_| apply_error(FolderPickerErrorCode::ApplyFailed))?;
    let mut files = Vec::new();
    for patch in parse_patches(diff)? {
        let mut current = root.to_path_buf();
        for component in patch.path.split('/') {
            current.push(component);
            if fs::symlink_metadata(&current)
                .is_ok_and(|metadata| metadata.file_type().is_symlink())
            {
                return Err(apply_error(FolderPickerErrorCode::InvalidDiff));
            }
        }
        let candidate = root.join(&patch.path);
        let target = if patch.create {
            if candidate.exists() || fs::symlink_metadata(&candidate).is_ok() {
                return Err(apply_error(FolderPickerErrorCode::SourceChanged));
            }
            let mut ancestor = candidate
                .parent()
                .ok_or_else(|| apply_error(FolderPickerErrorCode::InvalidDiff))?;
            while !ancestor.exists() {
                ancestor = ancestor
                    .parent()
                    .ok_or_else(|| apply_error(FolderPickerErrorCode::InvalidDiff))?;
            }
            if !fs::canonicalize(ancestor)
                .map_err(|_| apply_error(FolderPickerErrorCode::InvalidDiff))?
                .starts_with(&root)
            {
                return Err(apply_error(FolderPickerErrorCode::InvalidDiff));
            }
            candidate
        } else {
            fs::canonicalize(candidate)
                .map_err(|_| apply_error(FolderPickerErrorCode::SourceChanged))?
        };
        if !target.starts_with(&root)
            || (!patch.create
                && !fs::metadata(&target)
                    .map_err(|_| apply_error(FolderPickerErrorCode::SourceChanged))?
                    .is_file())
        {
            return Err(apply_error(FolderPickerErrorCode::InvalidDiff));
        }
        let source_bytes = if patch.create {
            Vec::new()
        } else {
            fs::read(&target).map_err(|_| apply_error(FolderPickerErrorCode::ApplyFailed))?
        };
        let source_text = std::str::from_utf8(&source_bytes)
            .map_err(|_| apply_error(FolderPickerErrorCode::InvalidDiff))?;
        let applied_bytes = apply_patch_to_text(source_text, &patch)?.into_bytes();
        files.push(PreparedLocalRemediationFile {
            path: patch.path,
            target,
            source_bytes,
            applied_bytes,
            backup_reference: PathBuf::new(),
            created: patch.create,
        });
    }
    Ok(files)
}

fn write_file_atomically(
    target: &Path,
    contents: &[u8],
    remediation_id: &str,
) -> Result<(), FolderPickerError> {
    #[cfg(test)]
    if should_fail_write(target) {
        return Err(apply_error(FolderPickerErrorCode::ApplyFailed));
    }
    let file_name = target
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| apply_error(FolderPickerErrorCode::ApplyFailed))?;
    let temporary = target.with_file_name(format!(".{file_name}.trace-{remediation_id}.tmp"));
    let write_result = (|| -> Result<(), FolderPickerError> {
        let mut file = fs::File::create(&temporary)
            .map_err(|_| apply_error(FolderPickerErrorCode::ApplyFailed))?;
        if let Ok(metadata) = fs::metadata(target) {
            fs::set_permissions(&temporary, metadata.permissions())
                .map_err(|_| apply_error(FolderPickerErrorCode::ApplyFailed))?;
        }
        file.write_all(contents)
            .map_err(|_| apply_error(FolderPickerErrorCode::ApplyFailed))?;
        file.sync_all()
            .map_err(|_| apply_error(FolderPickerErrorCode::ApplyFailed))?;
        fs::rename(&temporary, target)
            .map_err(|_| apply_error(FolderPickerErrorCode::ApplyFailed))?;
        Ok(())
    })();
    if write_result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    write_result?;
    Ok(())
}

fn restore_prepared_files(
    files: &[PreparedLocalRemediationFile],
    remediation_id: &str,
) -> Result<(), FolderPickerError> {
    for file in files.iter().rev() {
        let current =
            fs::read(&file.target).map_err(|_| apply_error(FolderPickerErrorCode::ApplyFailed))?;
        if sha256_hex(&current) != sha256_hex(&file.applied_bytes) {
            return Err(apply_error(FolderPickerErrorCode::ApplyFailed));
        }
        if file.created {
            fs::remove_file(&file.target)
                .map_err(|_| apply_error(FolderPickerErrorCode::ApplyFailed))?;
        } else {
            write_file_atomically(&file.target, &file.source_bytes, remediation_id)?;
        }
    }
    Ok(())
}

fn apply_local_remediation_at(
    root: &Path,
    backup_root: &Path,
    remediation_id: &str,
    diff: &str,
    is_allowed: impl Fn(&Path) -> bool,
) -> Result<NativeLocalRemediationResult, FolderPickerError> {
    let root =
        fs::canonicalize(root).map_err(|_| apply_error(FolderPickerErrorCode::ApplyFailed))?;
    if !is_allowed(&root) {
        return Err(apply_error(FolderPickerErrorCode::InvalidSelection));
    }
    let mut files = prepare_local_remediation_files(&root, diff)?;
    if files.iter().any(|file| !is_allowed(&file.target)) {
        return Err(apply_error(FolderPickerErrorCode::InvalidSelection));
    }

    let mut created_backups = Vec::new();
    for file in &mut files {
        let backup_reference = Path::new("local-remediation-backups")
            .join(remediation_id)
            .join(&file.path);
        let backup_path = backup_root.join(&backup_reference);
        let backup_parent = backup_path
            .parent()
            .ok_or_else(|| apply_error(FolderPickerErrorCode::ApplyFailed))?;
        if let Err(error) = fs::create_dir_all(backup_parent)
            .and_then(|_| fs::write(&backup_path, &file.source_bytes))
        {
            for path in created_backups {
                let _ = fs::remove_file(path);
            }
            return Err(apply_error(io_error_code(&error)));
        }
        file.backup_reference = backup_reference;
        created_backups.push(backup_path);
        if file.created {
            let marker = backup_root
                .join("local-remediation-created")
                .join(remediation_id)
                .join(&file.path);
            fs::create_dir_all(marker.parent().unwrap())
                .and_then(|_| fs::write(marker, b"created"))
                .map_err(|_| apply_error(FolderPickerErrorCode::ApplyFailed))?;
        }
    }

    let mut written_count = 0;
    for file in &files {
        let current = if file.created {
            Ok(Vec::new())
        } else {
            fs::read(&file.target)
        };
        let write_result = if file.created {
            fs::create_dir_all(file.target.parent().unwrap())
                .and_then(|_| {
                    let mut target = fs::OpenOptions::new()
                        .write(true)
                        .create_new(true)
                        .open(&file.target)?;
                    let result = target
                        .write_all(&file.applied_bytes)
                        .and_then(|_| target.sync_all());
                    if result.is_err() {
                        drop(target);
                        let _ = fs::remove_file(&file.target);
                    }
                    result
                })
                .map_err(|_| apply_error(FolderPickerErrorCode::ApplyFailed))
        } else if current.as_ref().ok() == Some(&file.source_bytes) {
            write_file_atomically(&file.target, &file.applied_bytes, remediation_id)
        } else {
            Err(apply_error(FolderPickerErrorCode::SourceChanged))
        };
        if current.as_ref().ok() != Some(&file.source_bytes) || write_result.is_err() {
            let _ = restore_prepared_files(&files[..written_count], remediation_id);
            return Err(apply_error(FolderPickerErrorCode::SourceChanged));
        }
        written_count += 1;
    }

    Ok(NativeLocalRemediationResult {
        files: files
            .into_iter()
            .map(|file| NativeLocalRemediationFile {
                file_path: file.path,
                backup_reference: file.backup_reference.to_string_lossy().into_owned(),
                source_hash: sha256_hex(&file.source_bytes),
                applied_hash: sha256_hex(&file.applied_bytes),
            })
            .collect(),
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

#[tauri::command]
pub fn create_local_review_snapshot(
    app: tauri::AppHandle,
    canonical_path: String,
    snapshot_id: String,
) -> Result<NativeStoredSourceSnapshot, FolderPickerError> {
    if snapshot_id.is_empty()
        || snapshot_id.len() > 128
        || !snapshot_id
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || character == '-')
    {
        return Err(snapshot_error());
    }
    let app_data = app.path().app_data_dir().map_err(|_| snapshot_error())?;
    let source_root = fs::canonicalize(&canonical_path).map_err(|_| snapshot_error())?;
    if !app.fs_scope().is_allowed(&source_root) {
        return Err(snapshot_error());
    }
    let destination = app_data.join("local-review-snapshots").join(&snapshot_id);
    let snapshot = copy_source_snapshot(Path::new(&canonical_path), &destination)?;
    let upload = match snapshot_upload(&destination, &snapshot.digest) {
        Ok(upload) => upload,
        Err(error) => {
            let _ = fs::remove_dir_all(&destination);
            return Err(error);
        }
    };
    Ok(NativeStoredSourceSnapshot {
        snapshot_id,
        integrity_algorithm: snapshot.integrity_algorithm,
        digest: snapshot.digest,
        upload,
    })
}

fn verify_executable_patch(
    root: &Path,
    patch: &NativeExecutablePatch,
) -> Result<(), FolderPickerError> {
    if patch.diff.len() > 1_048_576
        || sha256_hex(patch.diff.as_bytes()) != patch.sha256
        || patch.files.is_empty()
        || patch.files.len() > 20
    {
        return Err(apply_error(FolderPickerErrorCode::InvalidDiff));
    }
    let prepared = prepare_local_remediation_files(root, &patch.diff)?;
    if prepared.len() != patch.files.len()
        || patch
            .files
            .iter()
            .map(|file| &file.path)
            .collect::<HashSet<_>>()
            .len()
            != patch.files.len()
    {
        return Err(apply_error(FolderPickerErrorCode::InvalidDiff));
    }
    for file in &prepared {
        let expected = patch
            .files
            .iter()
            .find(|item| item.path == file.path)
            .ok_or_else(|| apply_error(FolderPickerErrorCode::InvalidDiff))?;
        if expected.operation != if file.created { "create" } else { "replace" }
            || expected.original_sha256
                != if file.created {
                    None
                } else {
                    Some(sha256_hex(&file.source_bytes))
                }
            || expected.result_sha256 != sha256_hex(&file.applied_bytes)
        {
            return Err(apply_error(FolderPickerErrorCode::SourceChanged));
        }
    }
    Ok(())
}

#[tauri::command]
pub fn apply_local_remediation(
    app: tauri::AppHandle,
    canonical_path: String,
    remediation_id: String,
    patch: NativeExecutablePatch,
) -> Result<NativeLocalRemediationResult, FolderPickerError> {
    if remediation_id.is_empty()
        || remediation_id.len() > 128
        || !remediation_id
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || character == '-')
    {
        return Err(apply_error(FolderPickerErrorCode::InvalidDiff));
    }
    let app_data = app
        .path()
        .app_data_dir()
        .map_err(|_| apply_error(FolderPickerErrorCode::ApplyFailed))?;
    let root = fs::canonicalize(&canonical_path)
        .map_err(|_| apply_error(FolderPickerErrorCode::InvalidSelection))?;
    if !app.fs_scope().is_allowed(&root) {
        return Err(apply_error(FolderPickerErrorCode::InvalidSelection));
    }
    verify_executable_patch(&root, &patch)?;
    apply_local_remediation_at(
        Path::new(&canonical_path),
        &app_data,
        &remediation_id,
        &patch.diff,
        |path| {
            if !app.fs_scope().is_allowed(path) {
                return false;
            }
            if path == root {
                return true;
            }
            let Some(relative) = path
                .strip_prefix(&root)
                .ok()
                .and_then(|value| value.to_str())
            else {
                return false;
            };
            let relative = relative.replace('\\', "/");
            let Some(expected) = patch.files.iter().find(|file| file.path == relative) else {
                return false;
            };
            match &expected.original_sha256 {
                None => fs::symlink_metadata(path).is_err(),
                Some(hash) => fs::read(path)
                    .map(|bytes| sha256_hex(&bytes) == *hash)
                    .unwrap_or(false),
            }
        },
    )
}

#[tauri::command]
pub fn restore_local_remediation(
    app: tauri::AppHandle,
    canonical_path: String,
    remediation_id: String,
    files: Vec<NativeLocalRemediationRestoreFile>,
) -> Result<(), FolderPickerError> {
    if remediation_id.is_empty()
        || remediation_id.len() > 128
        || !remediation_id
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || character == '-')
        || files.is_empty()
    {
        return Err(apply_error(FolderPickerErrorCode::InvalidDiff));
    }
    let root = fs::canonicalize(Path::new(&canonical_path))
        .map_err(|_| apply_error(FolderPickerErrorCode::ApplyFailed))?;
    if !app.fs_scope().is_allowed(&root) {
        return Err(apply_error(FolderPickerErrorCode::InvalidSelection));
    }
    let app_data = app
        .path()
        .app_data_dir()
        .map_err(|_| apply_error(FolderPickerErrorCode::ApplyFailed))?;
    let mut restored = Vec::new();
    for file in &files {
        if !is_safe_relative_path(&file.file_path) {
            return Err(apply_error(FolderPickerErrorCode::InvalidDiff));
        }
        let expected_backup = Path::new("local-remediation-backups")
            .join(&remediation_id)
            .join(&file.file_path);
        if Path::new(&file.backup_reference) != expected_backup {
            return Err(apply_error(FolderPickerErrorCode::InvalidDiff));
        }
        let target = fs::canonicalize(root.join(&file.file_path))
            .map_err(|_| apply_error(FolderPickerErrorCode::SourceChanged))?;
        if !target.starts_with(&root) || !app.fs_scope().is_allowed(&target) {
            return Err(apply_error(FolderPickerErrorCode::InvalidSelection));
        }
        let current =
            fs::read(&target).map_err(|_| apply_error(FolderPickerErrorCode::ApplyFailed))?;
        if sha256_hex(&current) != file.applied_hash {
            return Err(apply_error(FolderPickerErrorCode::SourceChanged));
        }
        let backup = fs::read(app_data.join(&expected_backup))
            .map_err(|_| apply_error(FolderPickerErrorCode::ApplyFailed))?;
        let marker = app_data
            .join("local-remediation-created")
            .join(&remediation_id)
            .join(&file.file_path);
        if fs::read(&marker).ok().as_deref() == Some(b"created") {
            fs::remove_file(&target)
                .map_err(|_| apply_error(FolderPickerErrorCode::ApplyFailed))?;
            let _ = fs::remove_file(marker);
        } else {
            write_file_atomically(&target, &backup, &remediation_id)?;
        }
        restored.push((target, backup));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::{
        fs,
        sync::atomic::{AtomicU64, Ordering},
        time::{SystemTime, UNIX_EPOCH},
    };

    static TEMPORARY_DIRECTORY_ID: AtomicU64 = AtomicU64::new(0);
    static WRITE_HOOK_TEST_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

    #[test]
    fn snapshot_upload_is_relative_sorted_and_bounded() {
        let root = temporary_directory();
        fs::create_dir_all(root.join("src")).unwrap();
        fs::write(root.join("src/a.ts"), b"const value = 1;\n").unwrap();
        let snapshot = capture_snapshot(&root).unwrap();
        let upload = super::snapshot_upload(&root, &snapshot.digest).unwrap();
        assert_eq!(upload.digest, snapshot.digest);
        assert_eq!(upload.entries.len(), 2);
        assert_eq!(upload.entries[0].path, "src");
        assert!(upload.entries[0].directory);
        assert_eq!(upload.entries[1].path, "src/a.ts");
        assert_eq!(
            base64::Engine::decode(
                &base64::engine::general_purpose::STANDARD,
                upload.entries[1].content_base64.as_ref().unwrap()
            )
            .unwrap(),
            b"const value = 1;\n"
        );
        fs::write(root.join("large.bin"), vec![b'x'; 256_001]).unwrap();
        let error = super::snapshot_upload(&root, &snapshot.digest).unwrap_err();
        assert!(matches!(
            error.code,
            FolderPickerErrorCode::SnapshotUploadTooLarge
        ));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn applies_shared_backend_fixtures_without_changing_bytes() {
        let fixtures: Vec<serde_json::Value> = serde_json::from_str(include_str!(
            "../../src/components/findings/fixtures/reliable-patches.json"
        ))
        .expect("shared fixtures");
        for fixture in fixtures {
            let root = temporary_directory();
            let backups = temporary_directory();
            let path = fixture["path"].as_str().unwrap();
            if cfg!(windows) && path.contains('"') {
                fs::remove_dir_all(root).unwrap();
                fs::remove_dir_all(backups).unwrap();
                continue;
            }
            if let Some(before) = fixture["before"].as_str() {
                fs::create_dir_all(root.join(path).parent().unwrap()).unwrap();
                fs::write(root.join(path), before.as_bytes()).unwrap();
            }
            apply_local_remediation_at(
                &root,
                &backups,
                "shared-fixture",
                fixture["diff"].as_str().unwrap(),
                |_| true,
            )
            .expect("apply shared fixture");
            assert_eq!(
                fs::read(root.join(path)).unwrap(),
                fixture["after"].as_str().unwrap().as_bytes()
            );
            fs::remove_dir_all(root).unwrap();
            fs::remove_dir_all(backups).unwrap();
        }
    }

    fn executable_patch(
        diff: &str,
        original: Option<&str>,
        result: &str,
        path: &str,
    ) -> super::NativeExecutablePatch {
        use super::{NativeExecutablePatch, NativeExecutablePatchFile, sha256_hex};
        NativeExecutablePatch {
            diff: diff.to_string(),
            sha256: sha256_hex(diff.as_bytes()),
            files: vec![NativeExecutablePatchFile {
                path: path.to_string(),
                operation: if original.is_some() {
                    "replace"
                } else {
                    "create"
                }
                .to_string(),
                original_sha256: original.map(|value| sha256_hex(value.as_bytes())),
                result_sha256: sha256_hex(result.as_bytes()),
            }],
        }
    }

    #[test]
    fn executable_patch_requires_the_verified_patch_and_unchanged_local_files() {
        use super::verify_executable_patch;
        let diff = "diff --git a/file.txt b/file.txt\n--- a/file.txt\n+++ b/file.txt\n@@ -1 +1 @@\n-before\n+after\n";
        let root = temporary_directory();
        fs::write(root.join("file.txt"), "before\n").unwrap();
        let patch = executable_patch(diff, Some("before\n"), "after\n", "file.txt");
        verify_executable_patch(&root, &patch).expect("matching source verifies");

        // A different diff than the one whose hash the backend recorded is refused.
        let mut tampered = patch.clone();
        tampered.sha256 = "0".repeat(64);
        assert!(matches!(
            verify_executable_patch(&root, &tampered).unwrap_err().code,
            FolderPickerErrorCode::InvalidDiff
        ));

        // Recorded result bytes that the patch cannot produce are refused.
        let mut wrong_result = patch.clone();
        wrong_result.files[0].result_sha256 = "1".repeat(64);
        assert!(matches!(
            verify_executable_patch(&root, &wrong_result)
                .unwrap_err()
                .code,
            FolderPickerErrorCode::SourceChanged
        ));

        // The local file changed after the review captured its snapshot.
        let changed = executable_patch(diff, Some("someone else's edit\n"), "after\n", "file.txt");
        assert!(matches!(
            verify_executable_patch(&root, &changed).unwrap_err().code,
            FolderPickerErrorCode::SourceChanged
        ));
        assert_eq!(fs::read(root.join("file.txt")).unwrap(), b"before\n");
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn executable_patch_refuses_to_create_a_file_that_now_exists() {
        use super::verify_executable_patch;
        let diff = "diff --git a/new.txt b/new.txt\nnew file mode 100644\n--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1 @@\n+created\n";
        let root = temporary_directory();
        let patch = executable_patch(diff, None, "created\n", "new.txt");
        verify_executable_patch(&root, &patch).expect("absent file verifies");
        fs::write(root.join("new.txt"), "appeared meanwhile\n").unwrap();
        assert!(matches!(
            verify_executable_patch(&root, &patch).unwrap_err().code,
            FolderPickerErrorCode::SourceChanged
        ));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn rolls_back_only_new_files_created_by_the_operation() {
        let _guard = WRITE_HOOK_TEST_LOCK.lock().unwrap();
        let root = temporary_directory();
        let backups = temporary_directory();
        fs::write(root.join("second.txt"), "before\n").unwrap();
        let second = fs::canonicalize(root.join("second.txt")).unwrap();
        *write_failure_hook().lock().unwrap() = Some(Box::new(move |path| path == second));
        let diff = "diff --git a/first.txt b/first.txt\nnew file mode 100644\n--- /dev/null\n+++ b/first.txt\n@@ -0,0 +1 @@\n+created\ndiff --git a/second.txt b/second.txt\n--- a/second.txt\n+++ b/second.txt\n@@ -1 +1 @@\n-before\n+after\n";
        let result = apply_local_remediation_at(&root, &backups, "create-rollback", diff, |_| true);
        *write_failure_hook().lock().unwrap() = None;
        assert!(result.is_err());
        assert!(!root.join("first.txt").exists());
        assert_eq!(fs::read(root.join("second.txt")).unwrap(), b"before\n");
        fs::remove_dir_all(root).unwrap();
        fs::remove_dir_all(backups).unwrap();
    }

    use super::{
        EXCLUDED_DIRECTORIES, FolderPickerErrorCode, apply_local_remediation_at,
        apply_patch_to_text, capture_snapshot, copy_source_snapshot, io_error_code,
        parse_single_file_patch, snapshot_read_hook, validate_folder, validate_selected_path,
        write_failure_hook,
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

    #[test]
    fn applies_one_existing_text_file_and_keeps_a_recoverable_backup() {
        let root = temporary_directory();
        let backups = temporary_directory();
        let source = root.join("src").join("example.txt");
        fs::create_dir_all(source.parent().expect("source parent")).expect("source parent");
        fs::write(&source, "before\nunchanged\n").expect("source file");
        let diff = "diff --git a/src/example.txt b/src/example.txt\n--- a/src/example.txt\n+++ b/src/example.txt\n@@ -1,2 +1,2 @@\n-before\n+after\n unchanged\n";

        let result = apply_local_remediation_at(&root, &backups, "remediation-1", diff, |_| true)
            .expect("patch should apply");

        assert_eq!(
            fs::read_to_string(&source).expect("updated source"),
            "after\nunchanged\n"
        );
        assert_eq!(result.files[0].file_path, "src/example.txt");
        assert_eq!(
            fs::read_to_string(backups.join(&result.files[0].backup_reference)).expect("backup"),
            "before\nunchanged\n"
        );
        fs::remove_dir_all(root).expect("source cleanup");
        fs::remove_dir_all(backups).expect("backup cleanup");
    }

    #[test]
    fn applies_pure_insertions_at_the_start_and_after_an_old_line() {
        let at_start = parse_single_file_patch(
            "diff --git a/example.txt b/example.txt\n--- a/example.txt\n+++ b/example.txt\n@@ -0,0 +1 @@\n+zero\n",
        )
        .expect("start insertion patch");
        let after_first_line = parse_single_file_patch(
            "diff --git a/example.txt b/example.txt\n--- a/example.txt\n+++ b/example.txt\n@@ -1,0 +2 @@\n+between\n",
        )
        .expect("mid-file insertion patch");

        assert_eq!(
            apply_patch_to_text("one\ntwo\n", &at_start).expect("start insertion"),
            "zero\none\ntwo\n"
        );
        assert_eq!(
            apply_patch_to_text("one\ntwo\n", &after_first_line).expect("mid-file insertion"),
            "one\nbetween\ntwo\n"
        );
    }

    #[test]
    fn accepts_an_index_line_and_preserves_a_removed_trailing_newline() {
        let patch = parse_single_file_patch(
            "diff --git a/example.txt b/example.txt\nindex abc1234..def5678 100644\n--- a/example.txt\n+++ b/example.txt\n@@ -1 +1 @@\n-before\n+after\n\\ No newline at end of file\n",
        )
        .expect("patch with index and newline marker");

        assert_eq!(
            apply_patch_to_text("before\n", &patch).expect("patch application"),
            "after"
        );
    }

    #[test]
    fn applies_multiple_files_only_after_every_file_passes_preflight() {
        let root = temporary_directory();
        let backups = temporary_directory();
        let first = root.join("src").join("first.txt");
        let second = root.join("src").join("second.txt");
        fs::create_dir_all(first.parent().expect("source parent")).expect("source parent");
        fs::write(&first, "before-one\n").expect("first source");
        fs::write(&second, "before-two\n").expect("second source");
        let diff = "diff --git a/src/first.txt b/src/first.txt\n--- a/src/first.txt\n+++ b/src/first.txt\n@@ -1 +1 @@\n-before-one\n+after-one\ndiff --git a/src/second.txt b/src/second.txt\n--- a/src/second.txt\n+++ b/src/second.txt\n@@ -1 +1 @@\n-before-two\n+after-two\n";

        let result = apply_local_remediation_at(&root, &backups, "remediation-2", diff, |_| true)
            .expect("patches should apply");

        assert_eq!(result.files.len(), 2);
        assert_eq!(
            fs::read_to_string(&first).expect("first result"),
            "after-one\n"
        );
        assert_eq!(
            fs::read_to_string(&second).expect("second result"),
            "after-two\n"
        );
        assert_eq!(
            fs::read_to_string(backups.join(&result.files[0].backup_reference))
                .expect("first backup"),
            "before-one\n"
        );
        assert_eq!(
            fs::read_to_string(backups.join(&result.files[1].backup_reference))
                .expect("second backup"),
            "before-two\n"
        );
        fs::remove_dir_all(root).expect("source cleanup");
        fs::remove_dir_all(backups).expect("backup cleanup");
    }

    #[test]
    fn missing_file_in_a_multi_file_diff_leaves_every_file_untouched() {
        let root = temporary_directory();
        let backups = temporary_directory();
        let first = root.join("first.txt");
        fs::write(&first, "before\n").expect("first source");
        let diff = "diff --git a/first.txt b/first.txt\n--- a/first.txt\n+++ b/first.txt\n@@ -1 +1 @@\n-before\n+after\ndiff --git a/missing.txt b/missing.txt\n--- a/missing.txt\n+++ b/missing.txt\n@@ -1 +1 @@\n-before\n+after\n";

        let error = apply_local_remediation_at(&root, &backups, "remediation-3", diff, |_| true)
            .expect_err("missing target should reject the whole operation");

        assert!(matches!(error.code, FolderPickerErrorCode::SourceChanged));
        assert_eq!(
            fs::read_to_string(&first).expect("first source"),
            "before\n"
        );
        assert!(!backups.join("local-remediation-backups").exists());
        fs::remove_dir_all(root).expect("source cleanup");
        fs::remove_dir_all(backups).expect("backup cleanup");
    }

    #[test]
    fn rejects_a_target_outside_the_allowed_scope_without_writing() {
        let root = temporary_directory();
        let backups = temporary_directory();
        let source = root.join("source.txt");
        fs::write(&source, "before\n").expect("source file");
        let root_for_scope = fs::canonicalize(&root).expect("canonical root");
        let diff = "diff --git a/source.txt b/source.txt\n--- a/source.txt\n+++ b/source.txt\n@@ -1 +1 @@\n-before\n+after\n";

        let error = apply_local_remediation_at(&root, &backups, "remediation-4", diff, |path| {
            path == root_for_scope
        })
        .expect_err("target outside scope should reject");

        assert!(matches!(
            error.code,
            FolderPickerErrorCode::InvalidSelection
        ));
        assert_eq!(fs::read_to_string(&source).expect("source"), "before\n");
        assert!(!backups.join("local-remediation-backups").exists());
        fs::remove_dir_all(root).expect("source cleanup");
        fs::remove_dir_all(backups).expect("backup cleanup");
    }

    #[cfg(unix)]
    #[test]
    fn rejects_a_symlink_that_escapes_the_selected_root() {
        use std::os::unix::fs::symlink;

        let root = temporary_directory();
        let outside = temporary_directory();
        let backups = temporary_directory();
        let external = outside.join("external.txt");
        fs::write(&external, "before\n").expect("external source");
        symlink(&external, root.join("escape.txt")).expect("symlink");
        let diff = "diff --git a/escape.txt b/escape.txt\n--- a/escape.txt\n+++ b/escape.txt\n@@ -1 +1 @@\n-before\n+after\n";

        let error = apply_local_remediation_at(&root, &backups, "remediation-5", diff, |_| true)
            .expect_err("symlink escape should reject");

        assert!(matches!(error.code, FolderPickerErrorCode::InvalidDiff));
        assert_eq!(
            fs::read_to_string(&external).expect("external source"),
            "before\n"
        );
        assert!(!backups.join("local-remediation-backups").exists());
        fs::remove_dir_all(root).expect("root cleanup");
        fs::remove_dir_all(outside).expect("outside cleanup");
        fs::remove_dir_all(backups).expect("backup cleanup");
    }

    #[test]
    fn restores_already_written_files_when_a_later_write_fails() {
        let _guard = WRITE_HOOK_TEST_LOCK.lock().unwrap();
        let root = temporary_directory();
        let backups = temporary_directory();
        let first = root.join("first.txt");
        let second = root.join("second.txt");
        fs::write(&first, "before-one\n").expect("first source");
        fs::write(&second, "before-two\n").expect("second source");
        let second_for_hook = fs::canonicalize(&second).expect("canonical second source");
        *write_failure_hook().lock().expect("write hook lock") =
            Some(Box::new(move |path| path == second_for_hook));
        let diff = "diff --git a/first.txt b/first.txt\n--- a/first.txt\n+++ b/first.txt\n@@ -1 +1 @@\n-before-one\n+after-one\ndiff --git a/second.txt b/second.txt\n--- a/second.txt\n+++ b/second.txt\n@@ -1 +1 @@\n-before-two\n+after-two\n";

        let error = apply_local_remediation_at(&root, &backups, "remediation-6", diff, |_| true)
            .expect_err("later write should fail");

        *write_failure_hook().lock().expect("write hook lock") = None;
        assert!(matches!(error.code, FolderPickerErrorCode::SourceChanged));
        assert_eq!(
            fs::read_to_string(&first).expect("first source"),
            "before-one\n"
        );
        assert_eq!(
            fs::read_to_string(&second).expect("second source"),
            "before-two\n"
        );
        fs::remove_dir_all(root).expect("source cleanup");
        fs::remove_dir_all(backups).expect("backup cleanup");
    }

    #[test]
    fn copies_a_private_review_snapshot_without_dependency_directories() {
        let source = temporary_directory();
        let destination_parent = temporary_directory();
        let snapshot_path = destination_parent.join("review-1");
        fs::write(source.join("app.txt"), "review source").expect("source file");
        fs::create_dir_all(source.join("node_modules")).expect("dependencies");
        fs::write(source.join("node_modules").join("ignored.js"), "ignored")
            .expect("dependency file");

        let snapshot = copy_source_snapshot(&source, &snapshot_path).expect("snapshot copy");

        assert!(snapshot.digest.len() == 64);
        assert_eq!(
            fs::read_to_string(snapshot_path.join("app.txt")).expect("copied source"),
            "review source"
        );
        assert!(!snapshot_path.join("node_modules").exists());
        fs::remove_dir_all(source).expect("source cleanup");
        fs::remove_dir_all(destination_parent).expect("destination cleanup");
    }

    #[test]
    fn rejects_malformed_or_multi_file_diffs_before_writing() {
        let malformed =
            "diff --git a/file.txt b/file.txt\n--- a/file.txt\n+++ b/file.txt\n+missing hunk\n";
        let multi_file = "diff --git a/first.txt b/first.txt\n--- a/first.txt\n+++ b/first.txt\n@@ -1 +1 @@\n-before\n+after\ndiff --git a/second.txt b/second.txt\n--- a/second.txt\n+++ b/second.txt\n@@ -1 +1 @@\n-before\n+after\n";

        assert!(parse_single_file_patch(malformed).is_err());
        assert!(parse_single_file_patch(multi_file).is_err());
    }
}
