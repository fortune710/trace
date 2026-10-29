use std::io::Write;

use base64::{Engine as _, engine::general_purpose::STANDARD};
use flate2::{Compression, write::GzEncoder};
use serde::Serialize;

const MAX_TELEMETRY_JSON_BYTES: usize = 64 * 1024;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeDesktopPlatform {
    pub operating_system: &'static str,
    pub architecture: &'static str,
}

#[tauri::command]
pub fn desktop_telemetry_platform() -> NativeDesktopPlatform {
    NativeDesktopPlatform {
        operating_system: std::env::consts::OS,
        architecture: std::env::consts::ARCH,
    }
}

#[tauri::command]
pub fn compress_desktop_telemetry(json: String) -> Result<String, String> {
    if json.len() > MAX_TELEMETRY_JSON_BYTES {
        return Err("telemetry payload exceeds the local size limit".to_owned());
    }
    serde_json::from_str::<serde_json::Value>(&json)
        .map_err(|_| "telemetry payload must be valid JSON".to_owned())?;

    let mut encoder = GzEncoder::new(Vec::new(), Compression::best());
    encoder
        .write_all(json.as_bytes())
        .map_err(|_| "telemetry payload could not be compressed".to_owned())?;
    let compressed = encoder
        .finish()
        .map_err(|_| "telemetry payload could not be compressed".to_owned())?;
    serde_json::to_string(&serde_json::json!({
        "v": 1,
        "codec": "gzip+base64",
        "data": STANDARD.encode(compressed),
    }))
    .map_err(|_| "telemetry payload could not be encoded".to_owned())
}

#[cfg(test)]
mod tests {
    use std::io::Read;

    use base64::{Engine as _, engine::general_purpose::STANDARD};
    use flate2::read::GzDecoder;

    use super::compress_desktop_telemetry;

    #[test]
    fn compresses_a_json_payload_into_a_json_envelope() {
        let envelope =
            compress_desktop_telemetry(r#"{"event":"local_remediation.applied"}"#.to_owned())
                .expect("compression should succeed");
        let value: serde_json::Value = serde_json::from_str(&envelope).expect("envelope JSON");
        assert_eq!(value["v"], 1);
        assert_eq!(value["codec"], "gzip+base64");

        let bytes = STANDARD
            .decode(value["data"].as_str().expect("encoded payload"))
            .expect("base64 payload");
        let mut decoder = GzDecoder::new(bytes.as_slice());
        let mut decoded = String::new();
        decoder.read_to_string(&mut decoded).expect("gzip payload");
        assert_eq!(decoded, r#"{"event":"local_remediation.applied"}"#);
    }

    #[test]
    fn rejects_non_json_and_oversized_payloads() {
        assert!(compress_desktop_telemetry("not-json".to_owned()).is_err());
        assert!(compress_desktop_telemetry(format!("\"{}\"", "x".repeat(65 * 1024))).is_err());
    }
}
