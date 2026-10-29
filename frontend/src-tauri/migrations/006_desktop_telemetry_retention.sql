CREATE TRIGGER desktop_telemetry_prune_after_insert
AFTER INSERT ON desktop_telemetry
BEGIN
  DELETE FROM desktop_telemetry
  WHERE id <= NEW.id - 10000;
END;
