# HIVE Compute Node 00

Public CPU worker for the shared **HIVE Compute Fabric**.

Canonical authority chain:

`OWNER -> QUEEN -> HIVE -> HIVE Compute Fabric -> hive-compute-node-00`

This repository is an execution resource. It is **not** an orchestrator, not a project source of truth, and not a place for plaintext secrets.

## Current role

- Node ID: `hive-compute-node-00`
- Provider: GitHub Actions
- Class: CPU
- Role: primary canary
- HIVE endpoint: `https://hive-alveare.pages.dev/api/compute-worker`
- Raw GitHub OIDC token persisted: no
- Database password required on worker: no

## Worker model

The worker accepts only versioned/allow-listed task types. It never executes arbitrary remote shell commands. Every execution emits a machine-readable result envelope with runner provenance and SHA-256 evidence.

The default-branch canary workflow launches four independent GitHub-hosted runner shards. That proves real parallel execution before HIVE certifies the node.

For managed work, CPU-00 operates as a pull worker after HIVE triggers the workflow: it authenticates, claims one eligible task from HIVE, validates the versioned job envelope, executes only an allow-listed workload and returns output plus provenance.

## Authentication

Two independent identities are required for managed HIVE work:

1. GitHub Actions issues a short-lived OIDC JWT with audience `hive-compute-fabric`. HIVE verifies its signature and exact repository/workflow claims.
2. Cloudflare Access admits the worker through HIVE's private perimeter. Its credentials belong only in GitHub Actions encrypted secrets:
   - `HIVE_CF_ACCESS_CLIENT_ID`
   - `HIVE_CF_ACCESS_CLIENT_SECRET`

No credential value belongs in this repository. Until those encrypted secrets are configured, canary runs explicitly record `access-service-token-pending` and remain useful for local CPU/OIDC certification.

## Activation policy

Presence of this repository or a successful workflow does not by itself authorize production scheduling. HIVE must separately register live heartbeat evidence and explicitly certify this node before managed tasks may be routed to it.
