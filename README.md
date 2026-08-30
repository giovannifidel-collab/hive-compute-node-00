# HIVE Compute Node 00

Public CPU worker for the shared **HIVE Compute Fabric**.

Canonical authority chain:

`OWNER -> QUEEN -> HIVE -> HIVE Compute Fabric -> hive-compute-node-00`

This repository is an execution resource. It is **not** an orchestrator, not a project source of truth, and not a place for secrets.

## Current role

- Node ID: `hive-compute-node-00`
- Provider: GitHub Actions
- Class: CPU
- Role: primary canary
- State: canary implementation
- Secrets committed: none

## Worker model

The worker accepts only versioned/allow-listed task types. It never executes arbitrary remote shell commands. Every execution emits a machine-readable result envelope with runner provenance and SHA-256 evidence.

The default-branch canary workflow launches four independent GitHub-hosted runner shards. That proves real parallel execution before HIVE certifies the node.

## Activation policy

Presence of this repository or a successful workflow does not by itself authorize production scheduling. HIVE must separately register live heartbeat evidence and certify this node before managed tasks may be routed to it.
