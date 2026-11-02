use std::sync::Arc;

use reqwest::{Client, Method, Url, cookie::Jar, header::HeaderName};
use serde::{Deserialize, Serialize};
use tauri::State;

pub struct DesktopHttp {
    client: Client,
}

impl DesktopHttp {
    pub fn new() -> Result<Self, reqwest::Error> {
        let jar = Arc::new(Jar::default());
        let client = Client::builder()
            .cookie_provider(jar)
            .redirect(reqwest::redirect::Policy::none())
            .build()?;
        Ok(Self { client })
    }
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DesktopRequest {
    base_url: String,
    path: String,
    method: String,
    headers: std::collections::HashMap<String, String>,
    body: Option<DesktopBody>,
}

#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "camelCase")]
enum DesktopBody {
    Text { value: String },
    Multipart { fields: Vec<MultipartField> },
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct MultipartField {
    name: String,
    value: serde_json::Value,
    filename: Option<String>,
    content_type: Option<String>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DesktopResponse {
    status: u16,
    body: String,
    retry_after: Option<String>,
    request_id: Option<String>,
}

fn validated_url(base_url: &str, path: &str) -> Result<Url, String> {
    let parsed_base = Url::parse(base_url).map_err(|_| "Invalid desktop API host")?;
    let local_debug_origin = cfg!(debug_assertions)
        && parsed_base.scheme() == "http"
        && matches!(parsed_base.host_str(), Some("localhost" | "127.0.0.1"))
        && parsed_base.port().is_some()
        && parsed_base.path() == "/"
        && parsed_base.query().is_none()
        && parsed_base.fragment().is_none()
        && parsed_base.username().is_empty()
        && parsed_base.password().is_none();
    let allowed = base_url == "https://traceapi.fortunealebiosu.dev" || local_debug_origin;
    if !allowed {
        return Err("Invalid desktop API host".into());
    }
    if !path.starts_with('/')
        || path.starts_with("//")
        || path.contains(['\\', '#'])
        || path
            .split('?')
            .next()
            .unwrap_or("")
            .split('/')
            .any(|part| part == ".." || part == ".")
        || !(path.starts_with("/auth/") || path.starts_with("/api/v1/"))
    {
        return Err("Invalid desktop API path".into());
    }
    let url =
        Url::parse(&format!("{}{}", base_url, path)).map_err(|_| "Invalid desktop API path")?;
    if !(url.path().starts_with("/auth/") || url.path().starts_with("/api/v1/")) {
        return Err("Invalid desktop API path".into());
    }
    Ok(url)
}

#[tauri::command]
pub async fn desktop_http_request(
    state: State<'_, DesktopHttp>,
    request: DesktopRequest,
) -> Result<DesktopResponse, String> {
    let url = validated_url(&request.base_url, &request.path)?;
    let method = match request.method.as_str() {
        "GET" => Method::GET,
        "POST" => Method::POST,
        "PATCH" => Method::PATCH,
        "DELETE" => Method::DELETE,
        _ => return Err("Unsupported desktop API method".into()),
    };
    let mut builder = state.client.request(method, url);
    for (name, value) in request.headers {
        let normalized = name.to_ascii_lowercase();
        if !matches!(
            normalized.as_str(),
            "content-type" | "x-csrf-token" | "idempotency-key"
        ) {
            return Err("Unsupported desktop API header".into());
        }
        let header_name = HeaderName::from_bytes(normalized.as_bytes())
            .map_err(|_| "Invalid desktop API header")?;
        builder = builder.header(header_name, value);
    }
    if let Some(body) = request.body {
        builder = match body {
            DesktopBody::Text { value } => builder.body(value),
            DesktopBody::Multipart { fields } => {
                let mut form = reqwest::multipart::Form::new();
                for field in fields {
                    let part = if let Some(text) = field.value.as_str() {
                        reqwest::multipart::Part::text(text.to_owned())
                    } else {
                        let bytes: Vec<u8> = serde_json::from_value(field.value)
                            .map_err(|_| "Invalid desktop multipart field")?;
                        let mut part = reqwest::multipart::Part::bytes(bytes);
                        if let Some(filename) = field.filename {
                            part = part.file_name(filename);
                        }
                        if let Some(content_type) = field.content_type {
                            part = part
                                .mime_str(&content_type)
                                .map_err(|_| "Invalid desktop multipart type")?;
                        }
                        part
                    };
                    form = form.part(field.name, part);
                }
                builder.multipart(form)
            }
        };
    }
    let response = builder
        .send()
        .await
        .map_err(|_| "Desktop API request failed")?;
    let status = response.status().as_u16();
    let retry_after = response
        .headers()
        .get("retry-after")
        .and_then(|value| value.to_str().ok())
        .map(str::to_owned);
    let request_id = response
        .headers()
        .get("x-request-id")
        .and_then(|value| value.to_str().ok())
        .map(str::to_owned);
    let body = response
        .text()
        .await
        .map_err(|_| "Desktop API response failed")?;
    Ok(DesktopResponse {
        status,
        body,
        retry_after,
        request_id,
    })
}

#[cfg(test)]
mod tests {
    use super::validated_url;

    #[test]
    fn accepts_a_relative_api_path_on_the_approved_host() {
        let url = validated_url("https://traceapi.fortunealebiosu.dev", "/auth/session")
            .expect("approved API path");
        assert_eq!(
            url.as_str(),
            "https://traceapi.fortunealebiosu.dev/auth/session"
        );
    }

    #[test]
    fn rejects_external_hosts_and_path_traversal() {
        assert!(validated_url("https://example.com", "/auth/session").is_err());
        assert!(
            validated_url(
                "https://traceapi.fortunealebiosu.dev",
                "//example.com/auth/session"
            )
            .is_err()
        );
        assert!(
            validated_url(
                "https://traceapi.fortunealebiosu.dev",
                "/auth/../api/v1/projects"
            )
            .is_err()
        );
    }
}
