import asyncio
import hashlib
import io
import json
import logging
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MAX_REQUIREMENTS_LENGTH = 4000
MAX_WORKFLOW_SECONDS = 600
RUN_RETENTION_SECONDS = 3600
AGENT_NAMES = (
    ("Engineering Lead", "design.md", "Engineering Lead: system design"),
    ("Backend Engineer", "main.py", "Backend Engineer: implementation"),
    ("Frontend Engineer", "app.py", "Frontend Engineer: demo UI"),
    ("Test Engineer", "tests/test_main.py", "Test Engineer: unit tests"),
)

app = FastAPI(
    title="Engineering Team",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
_runs: dict[str, dict[str, Any]] = {}
_idempotency: dict[str, tuple[str, str]] = {}
_active_run: str | None = None


class RunRequest(BaseModel):
    requirements: str


def _new_state() -> dict[str, Any]:
    return {
        "status": "running",
        "current": "Starting engineering team",
        "error": None,
        "files": [],
        "agents": [
            {"name": name, "filename": filename, "label": label, "status": "pending", "output": ""}
            for name, filename, label in AGENT_NAMES
        ],
    }


def _cleanup_expired() -> None:
    global _active_run
    cutoff = time.monotonic() - RUN_RETENTION_SECONDS
    for run_id, run in list(_runs.items()):
        if run["created"] >= cutoff or run["process"].poll() is None:
            continue
        try:
            shutil.rmtree(run["directory"])
        except OSError:
            logging.exception("Could not remove expired run directory %s", run_id)
            continue
        del _runs[run_id]
        for key, (stored_id, _) in list(_idempotency.items()):
            if stored_id == run_id:
                del _idempotency[key]
        if _active_run == run_id:
            _active_run = None


async def _expire_run(run_id: str) -> None:
    run = _runs.get(run_id)
    if run is None:
        return
    remaining = run["created"] + RUN_RETENTION_SECONDS - time.monotonic()
    if remaining > 0:
        await asyncio.sleep(remaining)
    _cleanup_expired()


def _read_state(run: dict[str, Any]) -> dict[str, Any]:
    state_path = run["directory"] / "state.json"
    if state_path.is_file():
        try:
            run["state"] = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logging.exception("Could not read state for run %s", run["id"])

    process: subprocess.Popen[bytes] = run["process"]
    if process.poll() is not None and run["state"]["status"] == "running":
        files = run["directory"] / "project"
        found_files = []
        if files.is_dir():
            found_files = [
                str(path.relative_to(files)).replace(os.sep, "/")
                for path in sorted(files.rglob("*"))
                if path.is_file()
            ]
        run["state"]["files"] = found_files
        if process.returncode == 0 and len(found_files) == len(AGENT_NAMES) + 2:
            run["state"]["status"] = "completed"
            run["state"]["current"] = "All four agents completed"
        else:
            run["state"]["status"] = "partially_completed" if found_files else "failed"
            run["state"]["error"] = "Worker exited before the workflow completed. See server logs."
            run["state"]["current"] = "Workflow stopped"
        run["updated"] = time.monotonic()

    return run["state"]


def _public_run(run: dict[str, Any]) -> dict[str, Any]:
    state = _read_state(run)
    return {
        "id": run["id"],
        "status": state["status"],
        "current": state["current"],
        "error": state["error"],
        "agents": state["agents"],
        "files": state["files"],
        "download_url": f"/api/runs/{run['id']}/download" if state["files"] else None,
    }


def _get_run(run_id: str) -> dict[str, Any]:
    run = _runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found or it has expired.")
    return run


def _worker_environment() -> dict[str, str]:
    return os.environ.copy()


async def _monitor(run_id: str) -> None:
    global _active_run
    run = _runs[run_id]
    process: subprocess.Popen[bytes] = run["process"]
    while process.poll() is None:
        if time.monotonic() - run["created"] >= MAX_WORKFLOW_SECONDS:
            process.kill()
            process.wait()
            state = _read_state(run)
            files = run["directory"] / "project"
            if files.is_dir():
                state["files"] = [
                    str(path.relative_to(files)).replace(os.sep, "/")
                    for path in sorted(files.rglob("*"))
                    if path.is_file()
                ]
            state["status"] = "partially_completed" if any(
                agent["status"] == "completed" for agent in state["agents"]
            ) else "timed_out"
            state["current"] = "Workflow time limit reached"
            state["error"] = f"Workflow exceeded the {MAX_WORKFLOW_SECONDS}-second time limit."
            run["updated"] = time.monotonic()
            break
        _read_state(run)
        await asyncio.sleep(1)
    else:
        _read_state(run)
    if _active_run == run_id:
        _active_run = None


@app.get("/", response_class=HTMLResponse)
async def home() -> str:
    return HTML_PAGE


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/runs", status_code=202)
async def start_run(
    request: RunRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    global _active_run
    _cleanup_expired()
    requirements = request.requirements.strip()
    if len(requirements) < 20:
        raise HTTPException(status_code=422, detail="Requirements must contain at least 20 characters.")
    if len(requirements) > MAX_REQUIREMENTS_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"Requirements must be no longer than {MAX_REQUIREMENTS_LENGTH} characters.",
        )

    request_hash = hashlib.sha256(requirements.encode("utf-8")).hexdigest()
    if idempotency_key:
        previous = _idempotency.get(idempotency_key)
        if previous:
            if previous[1] != request_hash:
                raise HTTPException(status_code=409, detail="This submission key was already used.")
            existing = _runs.get(previous[0])
            if existing:
                return _public_run(existing)
    if _active_run is not None:
        active = _runs.get(_active_run)
        if active and _read_state(active)["status"] == "running":
            raise HTTPException(status_code=409, detail="A team run is already in progress. Please wait.")
        _active_run = None

    run_id = secrets.token_urlsafe(24)
    run_directory = Path(tempfile.mkdtemp(prefix=f"engineering-team-{run_id[:8]}-"))
    state = _new_state()
    request_data = {"requirements": requirements}
    (run_directory / "input.json").write_text(json.dumps(request_data), encoding="utf-8")
    (run_directory / "state.json").write_text(json.dumps(state), encoding="utf-8")
    process_env = _worker_environment()
    command = [sys.executable, "-m", "engineering_team.worker", str(run_directory)]
    try:
        with (run_directory / "worker.log").open("wb") as log_file:
            process = subprocess.Popen(
                command,
                cwd=PROJECT_ROOT,
                env=process_env,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                close_fds=True,
            )
    except OSError as error:
        shutil.rmtree(run_directory)
        logging.exception("Could not start engineering team worker")
        raise HTTPException(status_code=503, detail=f"Could not start the workflow worker: {error}") from error

    run = {
        "id": run_id,
        "directory": run_directory,
        "process": process,
        "created": time.monotonic(),
        "updated": time.monotonic(),
        "state": state,
    }
    _runs[run_id] = run
    _active_run = run_id
    if idempotency_key:
        _idempotency[idempotency_key] = (run_id, request_hash)
    asyncio.create_task(_monitor(run_id))
    asyncio.create_task(_expire_run(run_id))
    return _public_run(run)


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    _cleanup_expired()
    return _public_run(_get_run(run_id))


@app.get("/api/runs/{run_id}/download")
async def download_run(run_id: str) -> Response:
    _cleanup_expired()
    run = _get_run(run_id)
    state = _read_state(run)
    if state["status"] == "running":
        raise HTTPException(status_code=409, detail="Wait for the run to finish before downloading.")
    project_dir = run["directory"] / "project"
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        for filename in state["files"]:
            file_path = (project_dir / filename).resolve()
            if not file_path.is_relative_to(project_dir.resolve()) or not file_path.is_file():
                logging.warning("Skipping unsafe or missing generated file in run %s", run_id)
                continue
            zipped.write(file_path, filename)
    if not archive.getbuffer().nbytes:
        raise HTTPException(status_code=404, detail="This run has no generated files to download.")
    return Response(
        content=archive.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="engineering-team-{run_id[:8]}.zip"'},
    )


HTML_PAGE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Engineering Team</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; background: #0b1020; color: #e8edf8; }
    * { box-sizing: border-box; }
    body { margin: 0; background: radial-gradient(ellipse at 80% 0%, #172747, #0b1020 55%); min-height: 100vh; }
    main { width: min(980px, calc(100% - 32px)); margin: 0 auto; padding: 56px 0 80px; }
    .eyebrow { color: #86a9ff; font-size: 12px; font-weight: 700; letter-spacing: .16em; text-transform: uppercase; }
    h1 { font-size: clamp(36px, 7vw, 62px); letter-spacing: -.05em; margin: 12px 0; }
    .intro { color: #aab5ca; max-width: 720px; line-height: 1.65; }
    .panel { margin-top: 28px; padding: 24px; border: 1px solid #293650; border-radius: 18px; background: #11192b; box-shadow: 0 20px 60px #0003; }
    label { display: block; font-weight: 700; margin-bottom: 12px; }
    textarea { width: 100%; min-height: 150px; resize: vertical; color: #e8edf8; background: #0b1020; border: 1px solid #34425e; border-radius: 10px; padding: 14px; font: inherit; line-height: 1.55; }
    button, .download { margin-top: 14px; display: inline-block; border: 0; border-radius: 9px; padding: 11px 17px; color: #071126; background: #90afff; font: inherit; font-weight: 750; cursor: pointer; text-decoration: none; }
    button:disabled { cursor: wait; opacity: .6; }
    .hint, .note { color: #91a0ba; font-size: 13px; line-height: 1.55; }
    #run { display: none; }
    .status { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
    .badge { border-radius: 999px; padding: 6px 10px; font-size: 12px; font-weight: 700; background: #293650; text-transform: uppercase; }
    .completed { color: #7be0ae; } .failed, .timed_out { color: #ff9098; } .partially_completed { color: #ffd27c; }
    .agents { display: grid; gap: 12px; margin-top: 20px; }
    article { border: 1px solid #293650; border-radius: 12px; overflow: hidden; background: #0d1424; }
    article header { display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 13px 15px; }
    article header strong { font-size: 14px; }
    article header span { color: #aab5ca; font-size: 12px; }
    pre { display: none; white-space: pre-wrap; overflow-wrap: anywhere; max-height: 420px; overflow: auto; margin: 0; padding: 15px; border-top: 1px solid #293650; color: #d3dcf0; font: 12px/1.6 ui-monospace, SFMono-Regular, Consolas, monospace; }
    .error { color: #ffabb0; margin-top: 12px; white-space: pre-wrap; }
    ul { color: #b9c5da; line-height: 1.8; }
    @media (max-width: 600px) { main { padding-top: 34px; } .panel { padding: 17px; } }
  </style>
</head>
<body>
<main>
  <div class="eyebrow">A sequential crewAI workflow</div>
  <h1>Engineering Team</h1>
  <p class="intro">Turn software requirements into a design, backend, demo UI, and unit tests. The engineering lead hands the design to the backend engineer; the frontend and test engineers then use the implementation as context.</p>
  <section class="panel">
    <form id="form">
      <label for="requirements">What should the team build?</label>
      <textarea id="requirements" maxlength="4000" minlength="20" required placeholder="Describe the software requirements (20–4000 characters)."></textarea>
      <div class="hint">The public demo generates code only. It does not execute generated code, run shell commands, or launch Docker.</div>
      <button id="submit" type="submit">Start engineering team</button>
    </form>
  </section>
  <section id="run" class="panel" aria-live="polite">
    <div class="status"><strong id="current">Starting…</strong><span id="badge" class="badge">Running</span></div>
    <div id="error" class="error"></div>
    <div id="agents" class="agents"></div>
    <div id="files"></div>
    <a id="download" class="download" hidden>Download generated project ZIP</a>
  </section>
  <section class="panel">
    <strong>Deployment demo limitations</strong>
    <ul>
      <li>Runs one workflow at a time and stops it after 10 minutes.</li>
      <li>Generated files are temporary and automatically removed after one hour.</li>
      <li>Run records use unguessable IDs in process memory; they are lost on restart. This is a hobby/demo service, not authenticated multi-tenant production hosting.</li>
      <li>Model-provider limits, access, and any charges depend on the API key owner. No provider call is made until a key is configured.</li>
    </ul>
  </section>
</main>
<script>
  const form = document.querySelector("#form");
  const submit = document.querySelector("#submit");
  const runPanel = document.querySelector("#run");
  const agents = document.querySelector("#agents");
  const terminal = new Set(["completed", "failed", "partially_completed", "timed_out"]);
  const escapeText = value => String(value ?? "");
  function render(data) {
    runPanel.style.display = "block";
    document.querySelector("#current").textContent = data.current || "Working…";
    const badge = document.querySelector("#badge");
    badge.textContent = data.status.replaceAll("_", " ");
    badge.className = "badge " + data.status;
    document.querySelector("#error").textContent = data.error || "";
    agents.replaceChildren();
    for (const item of data.agents) {
      const card = document.createElement("article");
      const header = document.createElement("header");
      const name = document.createElement("strong");
      name.textContent = item.name;
      const status = document.createElement("span");
      status.textContent = item.status;
      header.append(name, status);
      card.append(header);
      if (item.output) {
        const output = document.createElement("pre");
        output.style.display = "block";
        output.textContent = item.output;
        card.append(output);
      }
      agents.append(card);
    }
    const fileList = document.querySelector("#files");
    fileList.replaceChildren();
    if (data.files.length) {
      const title = document.createElement("p");
      title.textContent = "Generated files: " + data.files.join(", ");
      title.className = "note";
      fileList.append(title);
    }
    const download = document.querySelector("#download");
    download.hidden = !data.download_url;
    if (data.download_url) download.href = data.download_url;
    submit.disabled = !terminal.has(data.status);
    if (terminal.has(data.status)) submit.disabled = false;
  }
  async function poll(runId) {
    try {
      const response = await fetch("/api/runs/" + encodeURIComponent(runId));
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not retrieve run status.");
      render(data);
      if (!terminal.has(data.status)) setTimeout(() => poll(runId), 1200);
    } catch (error) {
      document.querySelector("#error").textContent = error.message;
      submit.disabled = false;
    }
  }
  form.addEventListener("submit", async event => {
    event.preventDefault();
    submit.disabled = true;
    document.querySelector("#error").textContent = "";
    runPanel.style.display = "block";
    try {
      const response = await fetch("/api/runs", {
        method: "POST",
        headers: {"Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID()},
        body: JSON.stringify({requirements: document.querySelector("#requirements").value})
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not start the team.");
      render(data);
      poll(data.id);
    } catch (error) {
      document.querySelector("#error").textContent = error.message;
      submit.disabled = false;
    }
  });
</script>
</body>
</html>
"""
