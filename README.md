# AI PM Digest

A daily AI-news email for product managers who build with AI. Feeds (`app/feeds.yaml`) and an optional Google Search scout feed a Gemini editor. Code checks every link, and the digest goes to Gmail. The design is in `.agents-cli-spec.md`.

## Production (Cloud Run, live)

The digest runs in Google Cloud: **Cloud Scheduler** (`ai-pm-digest-daily`, 07:00 America/Los_Angeles) calls `POST /digest/send` on the private **Cloud Run** service `ai-pm-digest` (project `YOUR_PROJECT_ID`, region `us-west1`) with an OIDC token.

- **Secrets:** Secret Manager (`gemini-api-key`, `gmail-app-password`). Non-secret settings come from `.env` (copied by `agents-cli deploy`).
- **Sent history:** `gs://YOUR_PROJECT_ID-ai-pm-digest/state/`. Sends at most once per day; `?force=true` overrides.
- **Service accounts:** `ai-pm-digest-app` reads those 2 secrets and writes that bucket. `ai-pm-digest-scheduler` can only invoke the service.

```bash
# Redeploy after code changes
agents-cli deploy --project YOUR_PROJECT_ID --region us-west1 \
  --service-account ai-pm-digest-app@YOUR_PROJECT_ID.iam.gserviceaccount.com \
  --secrets "GOOGLE_API_KEY=gemini-api-key,GMAIL_APP_PASSWORD=gmail-app-password" \
  --update-env-vars "DIGEST_STATE_URI=gs://YOUR_PROJECT_ID-ai-pm-digest/state,DIGEST_TIMEZONE=America/Los_Angeles" \
  --timeout 900 --max-instances 1 --min-instances 0 --concurrency 4 --memory 2Gi

# Cloud dry run (builds, doesn't email)
curl -X POST -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  "YOUR_SERVICE_URL/digest/send?dry_run=true"

# Trigger the schedule now / pause / resume
gcloud scheduler jobs run ai-pm-digest-daily --location us-west1
gcloud scheduler jobs pause ai-pm-digest-daily --location us-west1
gcloud scheduler jobs resume ai-pm-digest-daily --location us-west1

# Logs (step timings, Gemini retries)
gcloud logging read 'resource.labels.service_name="ai-pm-digest"' --limit 50
```

Don't also run the Mac schedule (`scripts/install_schedule.sh`). Local runs use local `data/`, not the bucket, so they can't see what the cloud already sent.

## Local development

Copy `.env.example` → `.env` and `.env.secrets.example` → `.env.secrets`, then fill them in. `.env.secrets` is git- and deploy-ignored.

```bash
uv run python run_digest.py --dry-run          # build today's digest → out/digest-<date>.html
uv run python run_digest.py --fixture slow-day # offline run on a saved snapshot
agents-cli playground                          # chat UI; "Build today's digest." (never emails)
```

**Evals:** `agents-cli eval generate --concurrency 1` then `uv run python tests/eval/grade_local.py`.
`agents-cli eval grade` works once `gcloud auth application-default login` is set up.

---

# ai-pm-digest

Simple ReAct agent
Agent generated with `agents-cli` version `1.7.0`

## Project Structure

```
ai-pm-digest/
├── app/         # Core agent code
│   ├── agent.py               # Main agent logic
│   ├── fast_api_app.py        # FastAPI Backend server
│   └── app_utils/             # App utilities and helpers
├── tests/                     # Unit, integration, and load tests
├── GEMINI.md                  # AI-assisted development guide
└── pyproject.toml             # Project dependencies
```

> 💡 **Tip:** Use [Antigravity CLI](https://antigravity.google/) for AI-assisted development - project context is pre-configured in `GEMINI.md`.

## Requirements

Before you begin, ensure you have:
- **uv**: Python package manager (used for all dependency management in this project) - [Install](https://docs.astral.sh/uv/getting-started/installation/) ([add packages](https://docs.astral.sh/uv/concepts/dependencies/) with `uv add <package>`)
- **agents-cli**: Agents CLI - Install with `uv tool install google-agents-cli`
- **Google Cloud SDK**: For GCP services - [Install](https://cloud.google.com/sdk/docs/install)


## Quick Start

Install `agents-cli` and its skills if not already installed:

```bash
uvx google-agents-cli setup
```

Install required packages:

```bash
agents-cli install
```

Test the agent with a local web server:

```bash
agents-cli playground
```

You can also use features from the [ADK](https://adk.dev/) CLI with `uv run adk`.

## Commands

| Command              | Description                                                                                 |
| -------------------- | ------------------------------------------------------------------------------------------- |
| `agents-cli install` | Install dependencies using uv                                                         |
| `agents-cli playground` | Launch local development environment                                                  |
| `agents-cli lint`    | Run code quality checks                                                               |
| `agents-cli eval`    | Evaluate agent behavior (generate, grade, analyze, and more — see `agents-cli eval --help`) |
| `uv run pytest tests/unit tests/integration` | Run unit and integration tests                                                        || [A2A Inspector](https://github.com/a2aproject/a2a-inspector) | Launch A2A Protocol Inspector                                                        |

## 🛠️ Project Management

| Command | What It Does |
|---------|--------------|
| `agents-cli scaffold enhance` | Add CI/CD pipelines and Terraform infrastructure |
| `agents-cli infra cicd` | One-command setup of entire CI/CD pipeline + infrastructure |
| `agents-cli scaffold upgrade` | Auto-upgrade to latest version while preserving customizations |

---

## Development

Edit your agent logic in `app/agent.py` and test with `agents-cli playground` - it auto-reloads on save.

## Deployment

```bash
gcloud config set project <your-project-id>
agents-cli deploy
```

To add CI/CD and Terraform, run `agents-cli scaffold enhance`.
To set up your production infrastructure, run `agents-cli infra cicd`.

## Observability

Built-in telemetry exports to Cloud Trace, BigQuery, and Cloud Logging.

## A2A Inspector

This agent supports the [A2A Protocol](https://a2a-protocol.org/). Use the [A2A Inspector](https://github.com/a2aproject/a2a-inspector) to test interoperability.
See the [A2A Inspector docs](https://github.com/a2aproject/a2a-inspector) for details.
