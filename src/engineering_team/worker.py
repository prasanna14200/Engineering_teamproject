import json
import logging
import os
import sys
import traceback
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from engineering_team.provider import (
    DEFAULT_MODEL,
    describe_groq_exception,
    describe_groq_http_error,
    groq_request,
    normalize_groq_api_key,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STAGES = (
    ("Engineering Lead", "design.md", "Engineering Lead: system design"),
    ("Backend Engineer", "main.py", "Backend Engineer: implementation"),
    ("Frontend Engineer", "app.py", "Frontend Engineer: demo UI"),
    ("Test Engineer", "tests/test_main.py", "Test Engineer: unit tests"),
)


def _write_state(path: Path, state: dict[str, Any]) -> None:
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(state), encoding="utf-8")
    temporary_path.replace(path)


def _safe_error_message(error: Exception) -> str:
    message = f"{type(error).__name__}: {error}"
    for name, value in os.environ.items():
        if value and any(part in name.upper() for part in ("TOKEN", "SECRET", "API_KEY")):
            message = message.replace(value, "[redacted]")
    return message[:1000]


def _missing_provider_key(model: str) -> str | None:
    provider = model.partition("/")[0].lower()
    key_name = {
        "groq": "GROQ_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "huggingface": "HF_TOKEN",
    }.get(provider)
    if key_name and not os.getenv(key_name):
        return key_name
    return None


def _verify_groq_model_access(model: str, api_key: str) -> None:
    model_id = model.removeprefix("groq/")
    status, headers, catalog = groq_request("/models", api_key)
    if status != 200:
        raise RuntimeError(
            describe_groq_http_error(
                status,
                headers,
                catalog,
                operation="model access check",
                secrets=(api_key,),
            )
        )
    if not catalog or not isinstance(catalog.get("data"), list):
        raise RuntimeError("Groq model access check returned an invalid model catalog.")

    available_models = sorted(
        item["id"]
        for item in catalog["data"]
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    )
    if model_id not in available_models:
        shown_models = ", ".join(available_models[:20]) or "(none listed)"
        if len(available_models) > 20:
            shown_models += ", ..."
        raise RuntimeError(
            f"Groq model '{model_id}' is not available to the configured API key. "
            "Check the GROQ_API_KEY in Render, then choose a chat model returned "
            "by Groq's authenticated GET /openai/v1/models endpoint and set "
            f"ENGINEERING_TEAM_MODEL=groq/<model-id>. Models visible to this key: "
            f"{shown_models}. No model-generation request was sent."
        )


def run(run_directory: Path) -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    state_path = run_directory / "state.json"
    input_path = run_directory / "input.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    request = json.loads(input_path.read_text(encoding="utf-8"))
    model = os.getenv("ENGINEERING_TEAM_MODEL", DEFAULT_MODEL).strip()
    raw_groq_key = os.getenv("GROQ_API_KEY", "")
    groq_key = normalize_groq_api_key(raw_groq_key) if model.startswith("groq/") else ""
    missing_key = _missing_provider_key(model)
    if missing_key or (model.startswith("groq/") and not groq_key):
        state["status"] = "failed"
        state["error"] = (
            f"{missing_key or 'GROQ_API_KEY'} is not configured. No model request was sent; "
            "add a provider key before starting a run."
        )
        _write_state(state_path, state)
        return

    if model.startswith("groq/"):
        os.environ["GROQ_API_KEY"] = groq_key
        try:
            _verify_groq_model_access(model, groq_key)
        except RuntimeError as error:
            state["status"] = "failed"
            state["error"] = _safe_error_message(error)
            _write_state(state_path, state)
            return

    for stage in state["agents"]:
        stage["status"] = "pending"
        stage["output"] = ""
    state["status"] = "running"
    state["current"] = STAGES[0][2]
    state["error"] = None
    _write_state(state_path, state)

    try:
        from engineering_team.crew import EngineeringTeam

        completed = 0

        def task_completed(task_output: Any) -> None:
            nonlocal completed
            agent = state["agents"][completed]
            output_path = run_directory / "project" / STAGES[completed][1]
            output = output_path.read_text(encoding="utf-8") if output_path.is_file() else str(task_output.raw or "")
            agent["status"] = "completed"
            agent["output"] = output
            completed += 1
            if completed < len(STAGES):
                state["agents"][completed]["status"] = "running"
                state["current"] = STAGES[completed][2]
            else:
                state["current"] = "Preparing project README"
            _write_state(state_path, state)

        state["agents"][0]["status"] = "running"
        _write_state(state_path, state)
        crew = EngineeringTeam().crew(task_callback=task_completed)
        for task, (_, filename, _) in zip(crew.tasks, STAGES):
            output_path = run_directory / "project" / filename
            output_path.parent.mkdir(parents=True, exist_ok=True)
            task.output_file = str(output_path)

        crew.kickoff(
            inputs={
                "requirements": request["requirements"],
                "module_name": "main.py",
                "class_name": "GeneratedProject",
            }
        )

        readme = (
            "# Generated Engineering Team project\n\n"
            "## Requirements\n\n"
            f"{request['requirements'].strip()}\n\n"
            "## Generated files\n\n"
            "- `main.py` — backend implementation\n"
            "- `app.py` — generated frontend/demo\n"
            "- `tests/test_main.py` — generated unit tests\n"
            "- `design.md` — engineering design\n\n"
            "## Setup and tests\n\n"
            "Review all generated files before running them. In an isolated "
            "environment, install `requirements.txt`, run "
            "`python -m pytest -q`, then start the generated demo with "
            "`python app.py` if appropriate. The public demo does not execute "
            "generated code.\n"
        )
        project_dir = run_directory / "project"
        (project_dir / "README.md").write_text(readme, encoding="utf-8")
        (project_dir / "requirements.txt").write_text(
            "gradio>=5,<7\npytest>=8,<9\n",
            encoding="utf-8",
        )
        state["files"] = [
            str(path.relative_to(project_dir)).replace(os.sep, "/")
            for path in sorted(project_dir.rglob("*"))
            if path.is_file()
        ]
        state["status"] = "completed"
        state["current"] = "All four agents completed"
        _write_state(state_path, state)
    except Exception as error:
        logging.error("Engineering team worker failed:\n%s", traceback.format_exc())
        failed_stage = next(
            (stage for stage in state["agents"] if stage["status"] in ("pending", "running")),
            None,
        )
        if failed_stage is not None:
            failed_stage["status"] = "failed"
        error_message = _safe_error_message(error)
        if model.startswith("groq/"):
            error_message = describe_groq_exception(error, secrets=(groq_key,)) or error_message
        state["error"] = error_message
        state["files"] = [
            str(path.relative_to(run_directory / "project")).replace(os.sep, "/")
            for path in sorted((run_directory / "project").rglob("*"))
            if path.is_file()
        ] if (run_directory / "project").is_dir() else []
        state["status"] = "partially_completed" if any(
            stage["status"] == "completed" for stage in state["agents"]
        ) else "failed"
        state["current"] = "Workflow stopped"
        _write_state(state_path, state)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m engineering_team.worker RUN_DIRECTORY")
    run(Path(sys.argv[1]))
