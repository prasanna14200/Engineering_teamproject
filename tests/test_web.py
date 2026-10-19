import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from engineering_team.crew import EngineeringTeam
from engineering_team.web import app
from engineering_team.worker import _verify_groq_model_access, run


class MockResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "MockResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


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
            "engineering_team.worker.urlopen",
            return_value=MockResponse({"data": [{"id": "llama-3.3-70b-versatile"}]}),
        ):
            _verify_groq_model_access("groq/llama-3.3-70b-versatile", "test-key")

    def test_groq_model_preflight_reports_models_not_available_to_key(self) -> None:
        with patch(
            "engineering_team.worker.urlopen",
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
                    "engineering_team.worker.urlopen",
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
