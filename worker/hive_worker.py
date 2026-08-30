#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import platform
import sys
import time
from pathlib import Path

NODE_ID = "hive-compute-node-00"
PROVIDER = "github-actions"
ALLOWED_TASKS = {"selftest", "sha256-burn"}
MAX_ROUNDS = 2_000_000


def mem_total_gb():
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                kib = int(line.split()[1])
                return round(kib / 1024 / 1024, 3)
    except Exception:
        pass
    return None


def sha256_burn(seed: str, rounds: int):
    rounds = max(1, min(int(rounds), MAX_ROUNDS))
    value = seed.encode("utf-8")
    started = time.perf_counter()
    for i in range(rounds):
        value = hashlib.sha256(value + i.to_bytes(8, "little", signed=False)).digest()
    elapsed = time.perf_counter() - started
    return {
        "rounds": rounds,
        "elapsed_seconds": round(elapsed, 6),
        "digest_sha256": value.hex(),
        "rounds_per_second": round(rounds / elapsed, 2) if elapsed > 0 else None,
    }


def canonical_hash(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def runner_provenance():
    return {
        "node_id": NODE_ID,
        "provider": PROVIDER,
        "repository": os.getenv("GITHUB_REPOSITORY"),
        "repository_id": os.getenv("GITHUB_REPOSITORY_ID"),
        "repository_owner_id": os.getenv("GITHUB_REPOSITORY_OWNER_ID"),
        "workflow": os.getenv("GITHUB_WORKFLOW"),
        "workflow_ref": os.getenv("GITHUB_WORKFLOW_REF"),
        "run_id": os.getenv("GITHUB_RUN_ID"),
        "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"),
        "run_number": os.getenv("GITHUB_RUN_NUMBER"),
        "sha": os.getenv("GITHUB_SHA"),
        "ref": os.getenv("GITHUB_REF"),
        "event_name": os.getenv("GITHUB_EVENT_NAME"),
        "runner_name": os.getenv("RUNNER_NAME"),
        "runner_os": os.getenv("RUNNER_OS"),
        "runner_arch": os.getenv("RUNNER_ARCH"),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "kernel": platform.release(),
        "logical_cpu_count": os.cpu_count(),
        "memory_total_gb": mem_total_gb(),
    }


def main():
    parser = argparse.ArgumentParser(description="HIVE Compute Fabric CPU worker")
    parser.add_argument("--task-type", default="selftest")
    parser.add_argument("--job-id", default="canary")
    parser.add_argument("--payload-json", default="{}")
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    if args.task_type not in ALLOWED_TASKS:
        raise SystemExit(f"task type not allowed: {args.task_type}")

    try:
        payload = json.loads(args.payload_json or "{}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid payload JSON: {exc}")
    if not isinstance(payload, dict):
        raise SystemExit("payload must be a JSON object")

    started_at = time.time()
    seed = f"{args.job_id}:{args.shard}:{canonical_hash(payload)}"

    if args.task_type == "selftest":
        rounds = int(payload.get("rounds", 250_000))
        computation = sha256_burn(seed, rounds)
        checks = {
            "python_supported": sys.version_info >= (3, 10),
            "cpu_visible": (os.cpu_count() or 0) >= 1,
            "github_repository_matches": os.getenv("GITHUB_REPOSITORY") in (None, "giovannifidel-collab/hive-compute-node-00"),
            "node_identity_fixed": NODE_ID == "hive-compute-node-00",
        }
        status = "done" if all(checks.values()) else "failed"
        output = {"checks": checks, "computation": computation}
    else:
        rounds = int(payload.get("rounds", 1_000_000))
        computation = sha256_burn(seed, rounds)
        status = "done"
        output = {"computation": computation}

    finished_at = time.time()
    provenance = runner_provenance()
    result = {
        "schema_version": "1.0",
        "job_id": args.job_id,
        "node_id": NODE_ID,
        "provider": PROVIDER,
        "task_type": args.task_type,
        "shard": args.shard,
        "status": status,
        "started_unix": started_at,
        "finished_unix": finished_at,
        "duration_seconds": round(finished_at - started_at, 6),
        "input_sha256": canonical_hash(payload),
        "output": output,
        "output_sha256": canonical_hash(output),
        "provenance": provenance,
    }
    result["result_sha256"] = canonical_hash(result)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "ok": status == "done",
        "node_id": NODE_ID,
        "job_id": args.job_id,
        "shard": args.shard,
        "result_sha256": result["result_sha256"],
        "logical_cpu_count": provenance["logical_cpu_count"],
        "memory_total_gb": provenance["memory_total_gb"],
        "duration_seconds": result["duration_seconds"],
    }, sort_keys=True))

    if status != "done":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
