# Engineering Team

A small crewAI engineering workflow with a web interface. It turns a software
requirement into a design, backend implementation, generated frontend/demo,
and unit tests. The demo only generates and packages files; it never executes
visitor-generated code.

## How the agents collaborate

The existing four-agent, sequential workflow is preserved:

1. **Engineering Lead** turns the requirement into a Python design.
2. **Backend Engineer** implements that design. Its task receives the lead's
   design as context.
3. **Frontend Engineer** builds a demo UI using the backend output as context.
4. **Test Engineer** writes unit tests using the backend output as context.

The UI shows each task's real CrewAI output as the task finishes. The
orchestrator adds a README, then offers all generated files in a ZIP. The
generated files are not necessarily correct or safe to run; review them first.

## Model and credentials

The repository previously hard-coded
`huggingface/meta-llama/Meta-Llama-3-8B-Instruct`. The Hugging Face model card
marks that model as manually gated, and Hugging Face currently documents no
included Inference Provider credits for free accounts. This is not a dependable
free deployment default.

The app defaults to `groq/llama-3.3-70b-versatile`, which appears in Groq's
official quickstart. Access and quotas depend on the provider account. The app
checks the configured key against Groq's authenticated model-list API before
starting a crew. Check current account pricing, model access, and rate limits
before adding a key. Groq documents base rate limits and a paid Developer plan
for higher limits, but that does not establish that a free quota or this model
is available to every account. The app does not fall back to a different or
paid provider.

Before authentication, the service trims surrounding whitespace and matching
outer quotes, and removes a mistakenly copied `Bearer ` prefix. The web
process passes its environment to the isolated worker; the worker explicitly
loads `.env` without overriding variables supplied by Render. The same
normalized key, `groq/<model-id>`, and canonical Groq API base are passed to
CrewAI/LiteLLM.

### Diagnose Groq from Render

In the deployed service's Shell, run this first. It makes only the authenticated
model-list request, not model inference, and never prints credentials:

```powershell
python -m engineering_team.diagnostics
```

It distinguishes HTTP 401 authentication, HTTP 403 permission, HTTP 404
resource/model, HTTP 429 rate/quota, and network failures. It prints the
provider error code/message and request ID when available, plus whether the
credential needed whitespace/quote/`Bearer ` normalization. Never post the
secret itself.

If the authenticated catalog lists the configured model, optionally compare a
minimal direct request with the CrewAI/LiteLLM path:

```powershell
python -m engineering_team.diagnostics --test-inference
```

This sends two small chat-completion requests and may count against the
provider account's quota or billing. Run it only if that is acceptable. If the
configured model is not listed, choose an available chat-completion model and
set Render's `ENGINEERING_TEAM_MODEL` to `groq/<exact-model-id>`. The app does
not silently change providers/models or enable paid services.

Copy `.env.example` to `.env` for local work and set `GROQ_API_KEY`, or set it
as a secret in Render. `ENGINEERING_TEAM_MODEL` can select another
CrewAI/LiteLLM-compatible model, but configure the matching provider key and
check its billing terms first. Never commit `.env` or put a real key in
`render.yaml`.

References:

- [Hugging Face Inference Providers pricing](https://huggingface.co/docs/inference-providers/pricing)
- [Meta Llama 3 8B Instruct model card](https://huggingface.co/meta-llama/Meta-Llama-3-8B-Instruct)
- [Groq model quickstart](https://console.groq.com/docs/quickstart)
- [Groq model catalog](https://console.groq.com/docs/models)
- [Groq rate limits](https://console.groq.com/docs/rate-limits)

## Run locally

Requires Python 3.10–3.13 and `uv`.

```powershell
uv sync --frozen
Copy-Item .env.example .env
# Edit .env and set GROQ_API_KEY to a key with a tier you have checked.
python app.py
```

Open `http://localhost:8000`. You can also run the CLI workflow with:

```powershell
uv run engineering_team "Describe the software you want built."
```

The CLI writes its outputs to `output/`. Web runs use a unique temporary
directory and do not share or overwrite CLI outputs.

## Deploy on Render Free

The root [`render.yaml`](./render.yaml) is a Blueprint for a Free Python web
service. It sets a compatible Python version, `0.0.0.0`/Render `PORT` binding,
the `/health` health check, and `plan: free`. In the Render dashboard, create a
Blueprint instance for this repository and branch `main`, review the Free
compute selection, and provide `GROQ_API_KEY` as a secret. Do not put the key
in source control.

Manual Web Service settings:

| Setting | Value |
| --- | --- |
| Service type | Web Service |
| Repository and branch | `prasanna14200/Engineering_teamproject`, `main` |
| Runtime | Python |
| Root Directory | Leave blank (repository root) |
| Build Command | `uv sync --frozen --no-dev` |
| Start Command | `python app.py` |
| Required environment variable | `GROQ_API_KEY` (secret); `ENGINEERING_TEAM_MODEL` defaults to `groq/llama-3.3-70b-versatile` |
| Health-check path | `/health` |
| Instance selection | Free |

After changing `render.yaml`, sync the Blueprint and verify the deployed Git
commit before starting a new workflow.

Render Free web services currently have 512 MB RAM, 0.1 CPU, ephemeral
filesystem, and spin down after inactivity. This app limits itself to one
workflow at a time, loads the CrewAI worker in a separate process only when a
run is requested, limits a workflow to ten minutes, and retains outputs for
one hour. No Docker daemon or generated-code execution is required. These
limits make it suitable as a hobby/demo service, not a production or
authenticated multi-tenant service. Free-instance performance and provider
quotas can make agent runs slow or cause them to fail.

Run status and files are held in memory and temporary storage. A Render restart
or spin-down loses active runs and their downloads. Run IDs are random and
unguessable, but the app has no sign-in or durable per-user account system;
keep the demo private if that level of isolation is insufficient.

## Tests

```powershell
uv run python -m unittest discover -s tests
```

The web app and worker never execute generated Python, unit tests, shell
commands, or Docker. Review and run downloaded files only in an isolated
environment you control.
