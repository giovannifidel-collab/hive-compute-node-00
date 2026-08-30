#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from hive_client import request_hive, observed

ALLOWED_WORKLOADS = {"selftest", "sha256-burn"}


def write(path, value):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def envelope_from_task(task):
    payload = task.get("payload") or {}
    if not isinstance(payload, dict):
        raise RuntimeError("claimed task payload is not an object")
    envelope = payload.get("envelope", payload)
    if not isinstance(envelope, dict):
        raise RuntimeError("claimed task envelope is not an object")
    if envelope.get("schema_version") != "1.0":
        raise RuntimeError("unsupported job envelope version")
    workload = envelope.get("workload") or {}
    name = workload.get("name")
    if name not in ALLOWED_WORKLOADS:
        raise RuntimeError(f"workload not allowed on CPU-00: {name}")
    if str(envelope.get("job_id")) != str(task.get("task_id")):
        raise RuntimeError("job envelope id does not match HIVE task id")
    return envelope


def main():
    parser = argparse.ArgumentParser(description="Claim and execute one HIVE CPU-00 task")
    parser.add_argument("--lease-seconds", type=int, default=600)
    parser.add_argument("--artifact-dir", default="artifacts")
    args = parser.parse_args()

    artifact_dir = Path(args.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    claim_response = request_hive("claim", {
        "lease_seconds": args.lease_seconds,
        "observed": observed(),
    })
    write(artifact_dir / "claim.json", claim_response)
    task = claim_response.get("task")
    if not task:
        state = {"ok": True, "state": "no-eligible-task", "node_id": "hive-compute-node-00"}
        write(artifact_dir / "no-work.json", state)
        print(json.dumps(state, sort_keys=True))
        return

    task_id = str(task["task_id"])
    try:
        envelope = envelope_from_task(task)
        workload = envelope["workload"]["name"]
        parameters = envelope.get("parameters") or {}
        result_path = artifact_dir / "result.json"
        shard = int((envelope.get("metadata") or {}).get("shard", 0))

        subprocess.run([
            sys.executable,
            str(Path(__file__).with_name("hive_worker.py")),
            "--task-type", workload,
            "--job-id", task_id,
            "--payload-json", json.dumps(parameters, separators=(",", ":")),
            "--shard", str(shard),
            "--output", str(result_path),
        ], check=True)

        result = json.loads(result_path.read_text())
        complete = request_hive("complete", {
            "task_id": task_id,
            "status": "done",
            "output": result.get("output", {}),
            "provenance": {
                **(result.get("provenance") or {}),
                "job_envelope": envelope,
                "input_sha256": result.get("input_sha256"),
                "output_sha256": result.get("output_sha256"),
                "result_sha256": result.get("result_sha256"),
            },
            "provider_job_ref": os.environ.get("GITHUB_RUN_ID"),
        })
        write(artifact_dir / "completion.json", complete)
        print(json.dumps({"ok": True, "task_id": task_id, "state": "completed"}, sort_keys=True))
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)[:2000]}
        write(artifact_dir / "worker-error.json", error)
        try:
            failed = request_hive("complete", {
                "task_id": task_id,
                "status": "failed",
                "output": {},
                "provenance": {
                    "github_run_id": os.environ.get("GITHUB_RUN_ID"),
                    "github_sha": os.environ.get("GITHUB_SHA"),
                },
                "provider_job_ref": os.environ.get("GITHUB_RUN_ID"),
                "error": error["message"],
            })
            write(artifact_dir / "failure-completion.json", failed)
        except Exception as report_exc:
            write(artifact_dir / "failure-report-error.json", {
                "type": type(report_exc).__name__,
                "message": str(report_exc)[:2000],
            })
        raise


if __name__ == "__main__":
    main()
