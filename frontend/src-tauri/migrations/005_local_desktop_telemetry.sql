CREATE TABLE desktop_telemetry (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  log_data JSON NOT NULL CHECK (json_valid(log_data))
);
