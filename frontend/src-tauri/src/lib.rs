mod folder_picker;
mod telemetry;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let migrations = vec![
        tauri_plugin_sql::Migration {
            version: 1,
            description: "create desktop project storage",
            sql: include_str!("../migrations/001_desktop_projects.sql"),
            kind: tauri_plugin_sql::MigrationKind::Up,
        },
        tauri_plugin_sql::Migration {
            version: 2,
            description: "prevent duplicate local projects",
            sql: include_str!("../migrations/002_local_project_uniqueness.sql"),
            kind: tauri_plugin_sql::MigrationKind::Up,
        },
        tauri_plugin_sql::Migration {
            version: 3,
            description: "allow local projects to retain a backend identity",
            sql: include_str!("../migrations/003_local_project_api_identity.sql"),
            kind: tauri_plugin_sql::MigrationKind::Up,
        },
        tauri_plugin_sql::Migration {
            version: 4,
            description: "store local review snapshots and remediation confirmation state",
            sql: include_str!("../migrations/004_local_review_state.sql"),
            kind: tauri_plugin_sql::MigrationKind::Up,
        },
        tauri_plugin_sql::Migration {
            version: 5,
            description: "store compressed desktop-only telemetry",
            sql: include_str!("../migrations/005_local_desktop_telemetry.sql"),
            kind: tauri_plugin_sql::MigrationKind::Up,
        },
        tauri_plugin_sql::Migration {
            version: 6,
            description: "retain the newest desktop telemetry entries",
            sql: include_str!("../migrations/006_desktop_telemetry_retention.sql"),
            kind: tauri_plugin_sql::MigrationKind::Up,
        },
    ];

    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            folder_picker::pick_local_folder,
            folder_picker::validate_local_folder,
            folder_picker::capture_local_source_snapshot,
            folder_picker::create_local_review_snapshot,
            folder_picker::apply_local_remediation,
            folder_picker::restore_local_remediation,
            telemetry::desktop_telemetry_platform,
            telemetry::compress_desktop_telemetry
        ])
        .plugin(tauri_plugin_single_instance::init(|_app, _argv, _cwd| {}))
        .plugin(tauri_plugin_deep_link::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(
            tauri_plugin_sql::Builder::default()
                .add_migrations("sqlite:trace.db", migrations)
                .build(),
        )
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while building tauri application");
}
