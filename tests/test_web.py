import unittest

from fastapi.testclient import TestClient

from engineering_team.crew import EngineeringTeam
from engineering_team.web import app


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


if __name__ == "__main__":
    unittest.main()
