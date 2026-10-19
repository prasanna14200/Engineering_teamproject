import json
import os
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from io import BytesIO

from fastapi.testclient import TestClient

from engineering_team.crew import EngineeringTeam, configured_llm
from engineering_team.provider import (
    GROQ_API_BASE,
    describe_groq_exception,
    describe_groq_http_error,
    normalize_groq_api_key,
)
from engineering_team.web import _worker_environment, app
from engineering_team import worker
from engineering_team.worker import _verify_groq_model_access, run


class MockResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.status = 200
        self.headers = Message()
        self.headers["Content-Type"] = "application/json"

    def __enter__(self) -> "MockResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


def groq_http_error(status: int, body: dict[str, object], request_id: str = "test-request-id") -> HTTPError:
    headers = Message()
    headers["x-request-id"] = request_id
    headers["Content-Type"] = "application/json"
    return HTTPError(
        "https://api.groq.com/openai/v1/models",
        status,
        "test error",
        headers,
        BytesIO(json.dumps(body).encode()),
    )


class EngineeringTeamWebTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_health_check(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_home_page_describes_non_executing_workflow(self) -> None:
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Engineering Team", response.text)
        self.assertIn("does not execute generated code", response.text)

    def test_rejects_too_short_requirements_before_starting_worker(self) -> None:
        response = self.client.post("/api/runs", json={"requirements": "too short"})

        self.assertEqual(response.status_code, 422)
        self.assertIn("at least 20 characters", response.json()["detail"])

    def test_unknown_run_is_not_exposed(self) -> None:
        response = self.client.get("/api/runs/not-a-real-run")

        self.assertEqual(response.status_code, 404)

    def test_all_agents_keep_code_execution_disabled(self) -> None:
        callback = lambda output: None
        crew = EngineeringTeam().crew(task_callback=callback)

        self.assertEqual(len(crew.agents), 4)
        self.assertEqual(len(crew.tasks), 4)
        self.assertIs(crew.task_callback, callback)
        self.assertTrue(all(not agent.allow_code_execution for agent in crew.agents))

    def test_groq_model_preflight_accepts_model_listed_for_key(self) -> None:
        with patch(
            "engineering_team.provider.urlopen",
            return_value=MockResponse({"data": [{"id": "llama-3.3-70b-versatile"}]}),
        ) as mocked_urlopen:
            _verify_groq_model_access("groq/llama-3.3-70b-versatile", "test-key")

        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, f"{GROQ_API_BASE}/models")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")

    def test_groq_model_preflight_reports_models_not_available_to_key(self) -> None:
        with patch(
            "engineering_team.provider.urlopen",
            return_value=MockResponse({"data": [{"id": "available-chat-model"}]}),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "not available to the configured API key",
            ) as error:
                _verify_groq_model_access(
                    "groq/llama-3.3-70b-versatile",
                    "test-key",
                )

        self.assertIn("available-chat-model", str(error.exception))
        self.assertIn("ENGINEERING_TEAM_MODEL=groq/<model-id>", str(error.exception))

    def test_http_401_is_reported_as_authentication_failure(self) -> None:
        error = groq_http_error(
            401,
            {"error": {"code": "invalid_api_key", "message": "Invalid API key"}},
        )

        with patch("engineering_team.provider.urlopen", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "HTTP 401: authentication failed"):
                _verify_groq_model_access("groq/available-chat-model", "test-key")

    def test_http_403_is_reported_as_permission_failure_not_bad_key(self) -> None:
        error = groq_http_error(
            403,
            {"error": {"code": "permission_denied", "message": "Project lacks access"}},
        )

        with patch("engineering_team.provider.urlopen", side_effect=error):
            with self.assertRaises(RuntimeError) as raised:
                _verify_groq_model_access("groq/available-chat-model", "test-key")

        message = str(raised.exception)
        self.assertIn("HTTP 403: permission denied", message)
        self.assertIn("permission_denied", message)
        self.assertIn("test-request-id", message)
        self.assertNotIn("authentication failed", message)
        self.assertNotIn("test-key", message)

    def test_http_429_is_reported_as_quota_or_rate_limit(self) -> None:
        message = describe_groq_http_error(
            429,
            Message(),
            {"error": {"code": "rate_limit_exceeded", "message": "Too many requests"}},
            operation="model access check",
        )

        self.assertIn("HTTP 429: rate limit or account quota exceeded", message)
        self.assertIn("rate_limit_exceeded", message)

    def test_http_404_is_reported_as_resource_or_model_error(self) -> None:
        message = describe_groq_http_error(
            404,
            Message(),
            {"error": {"code": "model_not_found", "message": "Unknown model"}},
            operation="chat request",
        )

        self.assertIn("HTTP 404: resource not found", message)
        self.assertIn("model_not_found", message)

    def test_litellm_model_not_found_error_is_not_reported_as_bad_credentials(self) -> None:
        error = RuntimeError(
            'Task execution failed: litellm.NotFoundError - '
            '{"error":{"message":"The model does not exist or you do not have access",'
            '"code":"model_not_found"}}'
        )

        message = describe_groq_exception(error, secrets=("test-key",))

        self.assertIsNotNone(message)
        self.assertIn("HTTP 404: resource not found", message)
        self.assertIn("model_not_found", message)
        self.assertNotIn("authentication failed", message)
        self.assertNotIn("test-key", message)

    def test_litellm_permission_error_is_reported_as_http_403(self) -> None:
        error = RuntimeError(
            "litellm.PermissionDeniedError: model access is not enabled"
        )

        message = describe_groq_exception(error)

        self.assertIsNotNone(message)
        self.assertIn("HTTP 403: permission denied", message)

    def test_network_failure_is_not_reported_as_authentication_failure(self) -> None:
        with patch("engineering_team.provider.urlopen", side_effect=URLError("offline")):
            with self.assertRaisesRegex(RuntimeError, "Could not reach Groq"):
                _verify_groq_model_access("groq/available-chat-model", "test-key")

    def test_provider_error_redacts_api_key_from_body(self) -> None:
        message = describe_groq_http_error(
            401,
            Message(),
            {"error": {"message": "Rejected test-key"}},
            operation="model access check",
            secrets=("test-key",),
        )

        self.assertIn("[redacted]", message)
        self.assertNotIn("test-key", message)

    def test_groq_key_normalization_removes_common_copy_formatting(self) -> None:
        self.assertEqual(normalize_groq_api_key('  "Bearer Bearer gsk-example "  '), "gsk-example")

    def test_configured_llm_uses_same_normalized_key_model_and_groq_endpoint(self) -> None:
        with patch.dict(
            os.environ,
            {
                "ENGINEERING_TEAM_MODEL": "groq/llama-3.3-70b-versatile",
                "GROQ_API_KEY": "  Bearer gsk-example  ",
            },
        ):
            llm = configured_llm()

        self.assertEqual(llm.model, "groq/llama-3.3-70b-versatile")
        self.assertEqual(llm.api_key, "gsk-example")
        self.assertEqual(llm.base_url, GROQ_API_BASE)

    def test_litellm_completion_parameters_match_direct_groq_configuration(self) -> None:
        with patch.dict(
            os.environ,
            {
                "ENGINEERING_TEAM_MODEL": "groq/llama-3.3-70b-versatile",
                "GROQ_API_KEY": "gsk-example",
            },
        ):
            params = configured_llm()._prepare_completion_params("Reply with OK.")

        self.assertEqual(params["model"], "groq/llama-3.3-70b-versatile")
        self.assertEqual(params["api_key"], "gsk-example")
        self.assertEqual(params["base_url"], GROQ_API_BASE)

    def test_worker_environment_inherits_render_key_without_logging_it(self) -> None:
        with patch.dict(os.environ, {"GROQ_API_KEY": "private-test-value"}):
            child_environment = _worker_environment()

        self.assertEqual(child_environment["GROQ_API_KEY"], "private-test-value")

    def test_worker_process_key_takes_precedence_over_dotenv_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / ".env").write_text(
                "GROQ_API_KEY=dotenv-placeholder\n",
                encoding="utf-8",
            )
            run_directory = root / "run"
            run_directory.mkdir()
            state = {
                "status": "running",
                "current": "Starting engineering team",
                "error": None,
                "files": [],
                "agents": [{"status": "pending", "output": ""}],
            }
            (run_directory / "state.json").write_text(json.dumps(state), encoding="utf-8")
            (run_directory / "input.json").write_text(
                json.dumps({"requirements": "test"}),
                encoding="utf-8",
            )

            with (
                patch.object(worker, "PROJECT_ROOT", root),
                patch.dict(
                    os.environ,
                    {
                        "ENGINEERING_TEAM_MODEL": "groq/llama-3.3-70b-versatile",
                        "GROQ_API_KEY": "  Bearer gsk-process-value  ",
                    },
                ),
                patch(
                    "engineering_team.worker._verify_groq_model_access",
                    side_effect=RuntimeError("test stops before inference"),
                ) as verify_access,
            ):
                run(run_directory)
                final_state = json.loads(
                    (run_directory / "state.json").read_text(encoding="utf-8")
                )

        verify_access.assert_called_once_with(
            "groq/llama-3.3-70b-versatile",
            "gsk-process-value",
        )
        self.assertEqual(final_state["status"], "failed")
        self.assertNotIn("dotenv-placeholder", final_state["error"])

    def test_worker_rejects_unavailable_model_before_starting_agents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            run_directory = Path(temporary_directory)
            initial_state = {
                "status": "running",
                "current": "Starting engineering team",
                "error": None,
                "files": [],
                "agents": [{"status": "pending", "output": ""}],
            }
            (run_directory / "state.json").write_text(json.dumps(initial_state))
            (run_directory / "input.json").write_text(json.dumps({"requirements": "test"}))

            with (
                patch.dict(
                    os.environ,
                    {
                        "ENGINEERING_TEAM_MODEL": "groq/llama-3.3-70b-versatile",
                        "GROQ_API_KEY": "test-key",
                    },
                ),
                patch(
                    "engineering_team.provider.urlopen",
                    return_value=MockResponse({"data": [{"id": "available-chat-model"}]}),
                ),
            ):
                run(run_directory)

            result = json.loads((run_directory / "state.json").read_text())
            self.assertFalse((run_directory / "project").exists())

        self.assertEqual(result["status"], "failed")
        self.assertIn("available-chat-model", result["error"])
        self.assertEqual(result["agents"][0]["status"], "pending")


if __name__ == "__main__":
    unittest.main()
