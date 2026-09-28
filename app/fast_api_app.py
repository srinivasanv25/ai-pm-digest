# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncIterator

from a2a.server.tasks import InMemoryTaskStore
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from google.adk.cli.fast_api import get_fast_api_app
from google.adk.runners import Runner

from app.app_utils import services
from app.app_utils.a2a import attach_a2a_routes

load_dotenv(".env.secrets")  # local only; git- and deploy-ignored
load_dotenv()

# Unattended daily job: surface our step logs and Gemini retry/backoff messages in
# Cloud Logging (Python's default only prints warnings).
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
for _name in ("app", "google_genai._api_client"):
    logging.getLogger(_name).setLevel(logging.INFO)
allow_origins = (
    os.getenv("ALLOW_ORIGINS", "").split(",") if os.getenv("ALLOW_ORIGINS") else None
)
# Cloud telemetry needs GCP credentials; locally (AI Studio key, no gcloud) skip it.
otel_to_cloud = bool(os.getenv("GOOGLE_CLOUD_PROJECT"))

AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from app.agent import app as adk_app
    from app.agent import root_agent

    runner = Runner(
        app=adk_app,
        session_service=services.get_session_service(),
        artifact_service=services.get_artifact_service(),
        auto_create_session=True,
    )
    app.state.runner = runner
    app.state.agent_app_name = adk_app.name
    await attach_a2a_routes(
        app,
        agent=root_agent,
        runner=runner,
        task_store=InMemoryTaskStore(),
        rpc_path=f"/a2a/{adk_app.name}",
    )
    yield


app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    web=True,
    artifact_service_uri=services.ARTIFACT_SERVICE_URI,
    allow_origins=allow_origins,
    session_service_uri=services.SESSION_SERVICE_URI,
    otel_to_cloud=otel_to_cloud,
    lifespan=lifespan,
)
app.title = "ai-pm-digest"
app.description = "API for interacting with the Agent ai-pm-digest"

_digest_lock = asyncio.Lock()


@app.post("/digest/send")
async def digest_send(force: bool = False, dry_run: bool = False) -> dict:
    """Daily trigger for Cloud Scheduler: build the digest and email it.

    Protected by Cloud Run IAM (the service is deployed without public access;
    only the scheduler's service account gets run.invoker). Sends at most once
    per day unless force=true, so scheduler retries can't double-send.
    """
    from app.daily import run_daily

    if _digest_lock.locked():
        raise HTTPException(
            status_code=409, detail="a digest run is already in progress"
        )
    async with _digest_lock:
        result = await run_daily(send=not dry_run, force=force)
    result.pop("html", None)
    if result["status"] == "failed":
        raise HTTPException(status_code=500, detail=result)
    return result


# Main execution
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
