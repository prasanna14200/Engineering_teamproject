import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

from dotenv import dotenv_values, load_dotenv

from engineering_team.provider import (
    DEFAULT_MODEL,
    GROQ_API_BASE,
    describe_groq_exception,
    describe_groq_http_error,
    groq_request,
    normalize_groq_api_key,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _available_model_ids(catalog: dict[str, Any]) -> list[str]:
    return sorted(
        model["id"]
        for model in catalog.get("data", [])
        if isinstance(model, dict) and isinstance(model.get("id"), str)
    )


def _redact(message: str, secrets: tuple[str, ...]) -> str:
    for secret in secrets:
        if secret:
            message = message.replace(secret, "[redacted]")
    return message[:1000]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check Groq authentication and optionally send two minimal chat requests."
    )
    parser.add_argument(
        "--test-inference",
        action="store_true",
        help="Send one minimal direct Groq and one CrewAI/LiteLLM chat request.",
    )
    args = parser.parse_args()

    process_key = os.environ.get("GROQ_API_KEY")
    dotenv_key = dotenv_values(PROJECT_ROOT / ".env").get("GROQ_API_KEY")
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    raw_key = os.getenv("GROQ_API_KEY", "")
    api_key = normalize_groq_api_key(raw_key)
    model = os.getenv("ENGINEERING_TEAM_MODEL", DEFAULT_MODEL).strip()
    stripped_key = raw_key.strip()
    wrapped_in_quotes = (
        len(stripped_key) >= 2
        and stripped_key[0] == stripped_key[-1]
        and stripped_key[0] in {"'", '"'}
    )
    print(f"credential_present={bool(api_key)}")
    print(f"process_credential_present={bool(process_key)}")
    print(f"dotenv_credential_present={bool(dotenv_key)}")
    print(
        "credential_source="
        + ("process" if process_key is not None else "dotenv" if dotenv_key else "unset")
    )
    print(
        "process_dotenv_values_differ="
        + str(bool(process_key and dotenv_key and process_key != dotenv_key)).lower()
    )
    print(f"credential_surrounding_whitespace={raw_key != raw_key.strip()}")
    print(f"credential_wrapped_in_quotes={wrapped_in_quotes}")
    print(f"credential_has_bearer_prefix={raw_key.strip().lower().startswith('bearer ')}")
    print(f"credential_normalized_for_requests={raw_key != api_key}")
    print(f"configured_model={model}")
    print(f"api_base={GROQ_API_BASE}")

    if not api_key:
        print("authentication_check=not_run (GROQ_API_KEY is unset or empty)")
        return 2
    if not model.startswith("groq/"):
        print("authentication_check=not_run (ENGINEERING_TEAM_MODEL is not a Groq model)")
        return 2

    os.environ["GROQ_API_KEY"] = api_key
    secrets = (raw_key, api_key)
    try:
        status, headers, catalog = groq_request("/models", api_key)
    except RuntimeError as error:
        print(f"authentication_check=failed ({_redact(str(error), secrets)})")
        return 1
    if status != 200:
        print(
            "authentication_check="
            + describe_groq_http_error(
                status,
                headers,
                catalog,
                operation="model-list request",
                secrets=secrets,
            )
        )
        return 1
    if not catalog or not isinstance(catalog.get("data"), list):
        print("authentication_check=failed (Groq returned an invalid model catalog)")
        return 1

    model_ids = _available_model_ids(catalog)
    model_id = model.removeprefix("groq/")
    print("authentication_check=passed (HTTP 200)")
    print(f"configured_model_listed={model_id in model_ids}")
    print("models_visible_to_key=" + ", ".join(model_ids[:40]))
    if model_id not in model_ids:
        print("inference_check=not_run (configured model is not listed for this key)")
        return 1
    if not args.test_inference:
        print("inference_check=not_run (pass --test-inference to send chat requests)")
        return 0

    chat_payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": "Reply with OK."}],
        "max_completion_tokens": 8,
    }
    try:
        status, headers, response = groq_request(
            "/chat/completions",
            api_key,
            payload=chat_payload,
            timeout=30,
        )
    except RuntimeError as error:
        print(f"direct_chat=failed ({_redact(str(error), secrets)})")
        return 1
    if status != 200:
        print(
            "direct_chat="
            + describe_groq_http_error(
                status,
                headers,
                response,
                operation="direct chat-completion request",
                secrets=secrets,
            )
        )
        return 1
    direct_request_id = _request_id(headers) or "unavailable"
    print(f"direct_chat=passed (HTTP 200, request_id={direct_request_id})")

    try:
        from engineering_team.crew import configured_llm

        completion = configured_llm(max_tokens=8, timeout=30).call("Reply with OK.")
    except Exception as error:
        message = describe_groq_exception(error, secrets=secrets)
        if message:
            print(f"crewai_litellm=failed ({type(error).__name__}: {message})")
        else:
            print(f"crewai_litellm=failed ({type(error).__name__}: {_redact(str(error), secrets)})")
        return 1
    print(f"crewai_litellm=passed (output_chars={len(str(completion))})")
    return 0


def _request_id(headers: Any) -> str | None:
    request_id = (
        headers.get("x-request-id")
        or headers.get("request-id")
        or headers.get("x-groq-request-id")
    )
    if not request_id:
        return None
    return re.sub(r"[^A-Za-z0-9._:-]", "", request_id)[:128] or None


if __name__ == "__main__":
    sys.exit(main())
