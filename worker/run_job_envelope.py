#!/usr/bin/env python3
import argparse
import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ALLOWED_WORKLOADS = {"selftest", "sha256-burn"}


def canonical_hash(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


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

    subprocess.run([
        sys.executable,
        str(Path(__file__).with_name("hive_worker.py")),
        "--task-type", workload,
        "--job-id", job_id,
        "--payload-json", json.dumps(parameters, separators=(",", ":")),
        "--shard", str(shard),
        "--output", str(out),
    ], check=True)

    result = json.loads(out.read_text())
    base_result_sha256 = result.pop("result_sha256", None)
    result["project_slug"] = envelope["project_slug"]
    result["hive_task_id"] = args.hive_task_id or None
    result["attempt_token"] = args.attempt_token or None
    result["job_envelope"] = envelope
    result["dispatch_mode"] = "stateless-artifact"
    result["base_result_sha256"] = base_result_sha256
    result["result_sha256"] = canonical_hash(result)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "ok": result.get("status") == "done",
        "hive_task_id": result.get("hive_task_id"),
        "attempt_token_present": bool(result.get("attempt_token")),
        "job_id": job_id,
        "project_slug": envelope["project_slug"],
        "dispatch_mode": result["dispatch_mode"],
        "result_sha256": result["result_sha256"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
