#!/usr/bin/env python3
import argparse
import json
import os
import platform
import urllib.parse
import urllib.request
from pathlib import Path

AUDIENCE = "hive-compute-fabric"
DEFAULT_ENDPOINT = "https://hive-alveare.pages.dev/api/compute-worker"
NODE_ID = "hive-compute-node-00"


def mem_total_gb():
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return round(int(line.split()[1]) / 1024 / 1024, 3)
    except Exception:
        pass
    return None


def github_oidc_token():
    url = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL")
    bearer = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN")
    if not url or not bearer:
        raise RuntimeError("GitHub OIDC environment unavailable; workflow needs id-token: write")
    sep = "&" if "?" in url else "?"
    target = url + sep + urllib.parse.urlencode({"audience": AUDIENCE})
    req = urllib.request.Request(target, headers={"Authorization": f"Bearer {bearer}"})
    with urllib.request.urlopen(req, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))
    token = data.get("value")
    if not token:
        raise RuntimeError("GitHub OIDC endpoint returned no token")
    return token


def access_credentials():
    return (
        os.environ.get("CF_ACCESS_CLIENT_ID", "").strip(),
        os.environ.get("CF_ACCESS_CLIENT_SECRET", "").strip(),
    )


def request_hive(action, body=None, timeout=30):
    endpoint = os.environ.get("HIVE_WORKER_ENDPOINT", DEFAULT_ENDPOINT).strip() or DEFAULT_ENDPOINT
    client_id, client_secret = access_credentials()
    if not client_id or not client_secret:
        raise RuntimeError("Cloudflare Access service-token credentials are not configured")
    oidc = github_oidc_token()
    payload = {"action": action, **(body or {})}
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=raw,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "CF-Access-Client-Id": client_id,
            "CF-Access-Client-Secret": client_secret,
            "X-Hive-Github-Oidc": oidc,
            "User-Agent": f"HIVE-Compute/{NODE_ID}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HIVE worker API HTTP {exc.code}: {detail[:1000]}") from exc
    if not data.get("ok"):
        raise RuntimeError(f"HIVE worker API rejected request: {data}")
    return data


def observed():
    return {
        "vcpu": os.cpu_count() or 1,
        "ram_gb": mem_total_gb(),
        "runner_os": os.environ.get("RUNNER_OS") or platform.system(),
        "runner_arch": os.environ.get("RUNNER_ARCH") or platform.machine(),
    }


def write_status(path, value):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main():
    parser = argparse.ArgumentParser(description="CPU-00 client for HIVE Compute Fabric")
    parser.add_argument("action", choices=["identity", "heartbeat", "claim", "task-heartbeat", "complete"])
    parser.add_argument("--task-id")
    parser.add_argument("--lease-seconds", type=int, default=300)
    parser.add_argument("--status", default="done")
    parser.add_argument("--result-json")
    parser.add_argument("--output", default="artifacts/hive-control.json")
    parser.add_argument("--optional", action="store_true", help="Record pending state instead of failing when Access credentials are absent")
    args = parser.parse_args()

    client_id, client_secret = access_credentials()
    if (not client_id or not client_secret) and args.optional:
        pending = {
            "ok": False,
            "node_id": NODE_ID,
            "state": "access-service-token-pending",
            "endpoint": os.environ.get("HIVE_WORKER_ENDPOINT", DEFAULT_ENDPOINT),
            "database_password_required_on_worker": False,
            "github_oidc_ready": bool(os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL")),
        }
        write_status(args.output, pending)
        print(json.dumps(pending, sort_keys=True))
        return

    body = {}
    if args.action in {"heartbeat", "claim"}:
        body["observed"] = observed()
    if args.action in {"claim", "task-heartbeat"}:
        body["lease_seconds"] = args.lease_seconds
    if args.action in {"task-heartbeat", "complete"}:
        if not args.task_id:
            raise SystemExit("--task-id is required for this action")
        body["task_id"] = args.task_id
    if args.action == "complete":
        body["status"] = args.status
        result = {}
        if args.result_json:
            result = json.loads(Path(args.result_json).read_text())
        body["output"] = result.get("output", result)
        body["provenance"] = result.get("provenance", {})
        body["provider_job_ref"] = os.environ.get("GITHUB_RUN_ID")
        if args.status != "done":
            body["error"] = result.get("error") or f"worker finished with status {args.status}"

    data = request_hive(args.action, body)
    sanitized = dict(data)
    write_status(args.output, sanitized)
    print(json.dumps({
        "ok": True,
        "node_id": NODE_ID,
        "action": args.action,
        "task_present": bool(data.get("task")),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
