#!/usr/bin/env python3
import argparse
import base64
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ALLOWED_WORKLOADS = {"selftest", "sha256-burn"}


def canonical_hash(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def iso_utc(unix_value):
    return datetime.fromtimestamp(float(unix_value), tz=timezone.utc).isoformat().replace("+00:00", "Z")


def decode_envelope(raw_b64: str):
    try:
        padded = raw_b64 + "=" * (-len(raw_b64) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        envelope = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"invalid base64 job envelope: {exc}") from exc
    if not isinstance(envelope, dict):
        raise RuntimeError("job envelope must be an object")
    if envelope.get("schema_version") != "1.0":
        raise RuntimeError("unsupported job envelope version")
    job_id = str(envelope.get("job_id") or "").strip()
    if not job_id:
        raise RuntimeError("job_id is required")
    project_slug = str(envelope.get("project_slug") or "").strip()
    if not project_slug:
        raise RuntimeError("project_slug is required")
    workload = envelope.get("workload") or {}
    if not isinstance(workload, dict):
        raise RuntimeError("workload must be an object")
    name = str(workload.get("name") or "").strip()
    version = str(workload.get("version") or "").strip()
    if name not in ALLOWED_WORKLOADS:
        raise RuntimeError(f"workload not allowed on CPU-00: {name}")
    if not version:
        raise RuntimeError("workload version is required")
    requirements = envelope.get("requirements") or {}
    if not isinstance(requirements, dict):
        raise RuntimeError("requirements must be an object")
    if requirements.get("class") not in (None, "cpu"):
        raise RuntimeError("CPU-00 only accepts cpu-class jobs")
    required = set(requirements.get("required_capabilities") or [])
    available = {"linux", "cpu", "github-actions", "parallel-shards", "oidc"}
    if not required.issubset(available):
        missing = sorted(required - available)
        raise RuntimeError(f"missing CPU-00 capabilities: {missing}")
    parameters = envelope.get("parameters") or {}
    if not isinstance(parameters, dict):
        raise RuntimeError("parameters must be an object")
    return envelope


def input_hashes(envelope, base):
    hashes = {"parameters": base["input_sha256"]}
    for item in envelope.get("inputs") or []:
        if isinstance(item, dict) and item.get("name") and item.get("sha256"):
            hashes[str(item["name"])] = str(item["sha256"]).removeprefix("sha256:")
    return hashes


def canonical_result(envelope, base, hive_task_id, attempt_token):
    prov = base.get("provenance") or {}
    source = envelope.get("source") or {}
    status = "completed" if base.get("status") == "done" else "failed"
    result = {
        "schema_version": "1.0",
        "job_id": str(envelope["job_id"]),
        "node": {
            "node_id": str(base.get("node_id") or "hive-compute-node-00"),
            "provider": str(base.get("provider") or "github-actions"),
            "provider_run_ref": str(prov.get("run_id") or "unknown"),
        },
        "workload": {
            "name": str(envelope["workload"]["name"]),
            "version": str(envelope["workload"]["version"]),
        },
        "status": status,
        "exit_code": 0 if status == "completed" else 1,
        "started_at": iso_utc(base["started_unix"]),
        "ended_at": iso_utc(base["finished_unix"]),
        "provenance": {
            "source_commit_or_version": str(source.get("commit_or_version") or prov.get("sha") or "unknown"),
            "source_sha256": source.get("sha256"),
            "input_hashes": input_hashes(envelope, base),
            "software": {
                "worker": "hive-compute-cpu-worker",
                "worker_protocol": "1.0",
                "python": prov.get("python"),
                "task_type": base.get("task_type"),
            },
            "hardware": {
                "logical_cpu_count": prov.get("logical_cpu_count"),
                "memory_total_gb": prov.get("memory_total_gb"),
                "runner_os": prov.get("runner_os"),
                "runner_arch": prov.get("runner_arch"),
            },
            "environment": {
                "repository": prov.get("repository"),
                "repository_id": prov.get("repository_id"),
                "repository_owner_id": prov.get("repository_owner_id"),
                "workflow": prov.get("workflow"),
                "workflow_ref": prov.get("workflow_ref"),
                "run_id": prov.get("run_id"),
                "run_attempt": prov.get("run_attempt"),
                "run_number": prov.get("run_number"),
                "sha": prov.get("sha"),
                "ref": prov.get("ref"),
                "event_name": prov.get("event_name"),
                "runner_name": prov.get("runner_name"),
                "platform": prov.get("platform"),
                "kernel": prov.get("kernel"),
            },
        },
        "artifacts": [],
        "metrics": {
            "duration_seconds": base.get("duration_seconds"),
            "input_sha256": base.get("input_sha256"),
            "output_sha256": base.get("output_sha256"),
            "base_result_sha256": base.get("result_sha256"),
        },
        "output": base.get("output") or {},
        "warnings": [],
        "error": None if status == "completed" else "worker reported failure",
        "metadata": {
            "project_slug": envelope["project_slug"],
            "hive_task_id": hive_task_id or None,
            "attempt_token": attempt_token or None,
            "dispatch_mode": "stateless-artifact",
            "shard": int(base.get("shard") or 0),
            "job_envelope": envelope,
            "seal": "sha256-canonical-json-v1",
        },
    }
    result["result_sha256"] = canonical_hash(result)
    return result


def main():
    parser = argparse.ArgumentParser(description="Execute a HIVE Job Envelope v1 without worker secrets")
    parser.add_argument("--envelope-b64", required=True)
    parser.add_argument("--hive-task-id", default="")
    parser.add_argument("--attempt-token", default="")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    envelope = decode_envelope(args.envelope_b64)
    job_id = str(envelope["job_id"])
    workload = envelope["workload"]["name"]
    parameters = envelope.get("parameters") or {}
    shard = int((envelope.get("metadata") or {}).get("shard", 0))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    raw_path = out.with_suffix(".raw.json")

    subprocess.run([
        sys.executable,
        str(Path(__file__).with_name("hive_worker.py")),
        "--task-type", workload,
        "--job-id", job_id,
        "--payload-json", json.dumps(parameters, separators=(",", ":")),
        "--shard", str(shard),
        "--output", str(raw_path),
    ], check=True)

    base = json.loads(raw_path.read_text())
    result = canonical_result(envelope, base, args.hive_task_id, args.attempt_token)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    raw_path.unlink(missing_ok=True)
    print(json.dumps({
        "ok": result["status"] == "completed",
        "hive_task_id": result["metadata"]["hive_task_id"],
        "attempt_token_present": bool(result["metadata"]["attempt_token"]),
        "job_id": result["job_id"],
        "project_slug": result["metadata"]["project_slug"],
        "dispatch_mode": result["metadata"]["dispatch_mode"],
        "result_sha256": result["result_sha256"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
