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
- Primary managed mode: stateless Job Envelope -> artifact
- Optional callback endpoint: `https://hive-alveare.pages.dev/api/compute-worker`
- Raw GitHub OIDC token persisted: no
- Database password required on worker: no

## Worker model

The worker accepts only versioned/allow-listed task types. It never executes arbitrary remote shell commands. Every execution emits a machine-readable result envelope with runner provenance and SHA-256 evidence.

The default-branch canary workflow launches four independent GitHub-hosted runner shards and exercises both direct deterministic execution and the same Job Envelope path used by HIVE.

### Primary managed path: stateless artifact dispatch

HIVE sends a versioned Job Envelope through GitHub `workflow_dispatch`. CPU-00 validates the envelope and capabilities, executes the allow-listed workload, and uploads the result/provenance as a GitHub Actions artifact. HIVE retrieves run state and evidence from GitHub and commits the result to its own task state.

This path requires **no HIVE credential, database password, or Cloudflare secret on the public worker**.

### Optional callback path

For workloads that later need active lease heartbeats or direct completion callbacks, CPU-00 also supports an authenticated HIVE client. That path uses short-lived GitHub OIDC plus Cloudflare Access and remains optional.

The optional encrypted repository secrets are:
- `HIVE_CF_ACCESS_CLIENT_ID`
- `HIVE_CF_ACCESS_CLIENT_SECRET`

No credential value belongs in this repository.

## Activation policy

Presence of this repository or a successful workflow does not by itself authorize production scheduling. HIVE must separately register evidence and explicitly certify this node before it becomes a production dispatch target.
