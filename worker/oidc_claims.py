#!/usr/bin/env python3
import base64
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

AUDIENCE = "hive-compute-fabric"
EXPECTED_REPOSITORY = "giovannifidel-collab/hive-compute-node-00"
EXPECTED_OWNER_ID = "305755860"


def b64url_decode(value: str) -> bytes:
    value += "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value.encode("ascii"))


def main():
    request_url = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL")
    request_token = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN")
    output = Path(os.environ.get("OIDC_OUTPUT", "artifacts/oidc-claims.json"))
    if not request_url or not request_token:
        raise SystemExit("GitHub OIDC environment is unavailable; id-token: write is required")

    separator = "&" if "?" in request_url else "?"
    url = request_url + separator + urllib.parse.urlencode({"audience": AUDIENCE})
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {request_token}"})
    with urllib.request.urlopen(req, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))

    jwt_value = data.get("value")
    if not jwt_value:
        raise SystemExit("GitHub OIDC endpoint returned no token")
    parts = jwt_value.split(".")
    if len(parts) != 3:
        raise SystemExit("GitHub OIDC token is not a JWT")

    claims = json.loads(b64url_decode(parts[1]).decode("utf-8"))
    checks = {
        "issuer": claims.get("iss") == "https://token.actions.githubusercontent.com",
        "audience": claims.get("aud") == AUDIENCE,
        "repository": claims.get("repository") == EXPECTED_REPOSITORY,
        "repository_owner_id": str(claims.get("repository_owner_id")) == EXPECTED_OWNER_ID,
        "ref_main": claims.get("ref") == "refs/heads/main",
    }

    safe_claims = {
        key: claims.get(key)
        for key in (
            "iss", "aud", "sub", "repository", "repository_id", "repository_owner",
            "repository_owner_id", "workflow", "workflow_ref", "job_workflow_ref",
            "run_id", "run_number", "run_attempt", "ref", "sha", "event_name",
            "actor", "actor_id", "iat", "nbf", "exp"
        )
        if key in claims
    }
    result = {
        "schema_version": "1.0",
        "node_id": "hive-compute-node-00",
        "audience": AUDIENCE,
        "checks": checks,
        "verified_by_runner_request": all(checks.values()),
        "claims": safe_claims,
        "note": "The raw JWT is intentionally not persisted. HIVE will independently verify signature/JWKS when the edge handshake is enabled."
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"ok": all(checks.values()), "node_id": result["node_id"], "checks": checks}, sort_keys=True))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
