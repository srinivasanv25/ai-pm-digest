"""Grade eval traces locally with the metrics in eval_config.yaml.

`agents-cli eval grade` needs Google Cloud credentials (ADC) even for local
metrics. Without gcloud, run this on the traces from `agents-cli eval generate`:

    uv run python tests/eval/grade_local.py                 # newest trace file
    uv run python tests/eval/grade_local.py path/to/traces.json

Uses the same `evaluate(instance)` contract, so switching back to
`agents-cli eval grade` later needs no metric changes.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

EVAL_DIR = Path(__file__).resolve().parent
ROOT = EVAL_DIR.parent.parent


def load_metrics() -> dict:
    cfg = yaml.safe_load((EVAL_DIR / "eval_config.yaml").read_text())
    by_name = {m["name"]: m for m in cfg.get("custom_metrics", [])}
    metrics = {}
    for name in cfg["metrics_to_run"]:
        namespace: dict = {}
        exec(
            compile(
                (EVAL_DIR / by_name[name]["custom_function_file"]).read_text(),
                name,
                "exec",
            ),
            namespace,
        )
        metrics[name] = namespace["evaluate"]
    return metrics


def to_instance(case: dict) -> dict:
    responses = case.get("responses") or [{}]
    return {
        "prompt": case.get("prompt"),
        "response": responses[-1].get("response"),
        "agent_data": case.get("agent_data"),
        "reference": case.get("reference"),
    }


def main() -> int:
    load_dotenv(ROOT / ".env.secrets")
    load_dotenv(ROOT / ".env")
    traces = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else max((ROOT / "artifacts/traces").glob("*.json"))
    )
    cases = json.loads(traces.read_text())["eval_cases"]
    metrics = load_metrics()

    results = []
    for case in cases:
        row = {"eval_case_id": case.get("eval_case_id")}
        for name, fn in metrics.items():
            try:
                row[name] = fn(to_instance(case))
            except Exception as e:  # a crashing metric is a failing metric
                row[name] = {"score": 0, "explanation": f"metric error: {e!r}"}
        results.append(row)

    width = max(len(str(r["eval_case_id"])) for r in results)
    print(f"Traces: {traces}\n")
    print("case".ljust(width), *(n.ljust(22) for n in metrics))
    for r in results:
        print(
            str(r["eval_case_id"]).ljust(width),
            *(str(r[n]["score"]).ljust(22) for n in metrics),
        )
    print()
    for r in results:
        for n in metrics:
            print(f"[{r['eval_case_id']}] {n}: {r[n]['explanation']}")

    out_dir = ROOT / "artifacts/grade_results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"local_results_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps({"traces": str(traces), "results": results}, indent=1))
    print(f"\nSaved {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
