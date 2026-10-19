import json
import re
from http.client import HTTPMessage
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

GROQ_API_BASE = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "groq/llama-3.3-70b-versatile"


def normalize_groq_api_key(raw_value: str) -> str:
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1].strip()
    while value[:7].lower() == "bearer ":
        value = value[7:].strip()
    return value


def groq_request(
    path: str,
    api_key: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: int = 15,
) -> tuple[int, HTTPMessage, dict[str, Any] | None]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Authorization": f"Bearer {api_key}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(f"{GROQ_API_BASE}{path}", data=body, headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, response.headers, _read_json(response.read())
    except HTTPError as error:
        return error.code, error.headers, _read_json(error.read())
    except (URLError, TimeoutError, OSError) as error:
        raise RuntimeError(
            f"Could not reach Groq at {GROQ_API_BASE}{path}: "
            f"{type(error).__name__}."
        ) from error


def describe_groq_http_error(
    status: int,
    headers: HTTPMessage,
    payload: dict[str, Any] | None,
    *,
    operation: str,
    secrets: tuple[str, ...] = (),
) -> str:
    error_data = payload.get("error") if payload else None
    if not isinstance(error_data, dict):
        error_data = {}
    message = error_data.get("message")
    code = error_data.get("code")
    request_id = (
        headers.get("x-request-id")
        or headers.get("request-id")
        or headers.get("x-groq-request-id")
    )

    if status == 401:
        classification = "authentication failed; Groq did not accept the API credential"
    elif status == 403:
        classification = "permission denied; the credential was accepted but access is restricted"
    elif status == 404:
        classification = "resource not found; check the API endpoint or model identifier"
    elif status == 429:
        classification = "rate limit or account quota exceeded"
    elif status >= 500:
        classification = "Groq server error"
    else:
        classification = "Groq rejected the request"

    details = []
    if code:
        details.append(f"provider_code={_sanitize(code, secrets)}")
    if message:
        details.append(f"provider_message={_sanitize(message, secrets)}")
    if request_id:
        safe_request_id = re.sub(r"[^A-Za-z0-9._:-]", "", request_id)[:128]
        if safe_request_id:
            details.append(f"request_id={safe_request_id}")
    suffix = f" ({'; '.join(details)})" if details else ""
    return f"Groq {operation} failed with HTTP {status}: {classification}{suffix}."


def describe_groq_exception(error: Exception, *, secrets: tuple[str, ...] = ()) -> str | None:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None) or HTTPMessage()
    body = getattr(error, "body", None)
    if isinstance(body, bytes):
        body = _read_json(body)
    elif isinstance(body, str):
        body = _read_json(body.encode("utf-8"))

    error_text = str(error)
    if not isinstance(body, dict):
        body = _json_object_in_text(error_text)
    if not isinstance(body, dict):
        body = None

    status = getattr(error, "status_code", None)
    if not status:
        error_name = f"{type(error).__name__} {error_text}".lower()
        for name, code in (
            ("authenticationerror", 401),
            ("permissiondeniederror", 403),
            ("notfounderror", 404),
            ("ratelimiterror", 429),
        ):
            if name in error_name:
                status = code
                break
    if status:
        return describe_groq_http_error(
            int(status),
            headers,
            body,
            operation="model inference",
            secrets=secrets,
        )
    if body and isinstance(body.get("error"), dict):
        provider_code = str(body["error"].get("code", "")).lower()
        if provider_code == "model_not_found":
            return describe_groq_http_error(
                404,
                headers,
                body,
                operation="model inference",
                secrets=secrets,
            )
    return None


def _read_json(body: bytes) -> dict[str, Any] | None:
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _json_object_in_text(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    if start < 0:
        return None
    try:
        payload, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _sanitize(value: Any, secrets: tuple[str, ...]) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return text[:500]
