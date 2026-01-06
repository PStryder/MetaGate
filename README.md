MetaGate

MetaGate is the first flame in a LegiVellum system.

It is a non-blocking, describe-only bootstrap service that provides authoritative environment truth to components before they participate in a distributed system.

MetaGate is intentionally boring, synchronous, and limited—because bootstrap must be reliable even when everything else is broken.

What MetaGate Does

On bootstrap, MetaGate:

Authenticates the caller

Resolves principal → binding → profile → manifest

Verifies that the requested component is permitted

Returns a Welcome Packet describing the environment

Issues an OPEN startup receipt as a witness of instantiation

Immediately exits the interaction

MetaGate does not wait for readiness.
MetaGate does not check health.
MetaGate does not care if anything else is running.

What MetaGate Never Does

MetaGate never:

assigns work

provisions infrastructure

orchestrates execution

distributes task payloads

blocks on health checks

waits on other services

coordinates system behavior

If MetaGate is doing more than answering questions and recording facts, it is doing too much.

MetaGate v0 Specification

Core Concepts
Principal

Who is speaking.
Derived from authentication subject (sub), mapped to a stable principal_key.

Component

What is being instantiated.
Every bootstrap requires a component_key.

Profile

Defines what kind of thing this component is:

capabilities

policy constraints

startup SLA defaults

secret handling rules

Manifest

Describes the world:

services

endpoints

memory usage

polling locations (pointers only)

schema references

Binding

A binding ties a principal to a profile and manifest.
Exactly one active binding per principal in v0.

Non-Blocking Doctrine (Hard Invariant)

All MetaGate request handling must be:

synchronous

bounded

database-only

side-effect minimal

MetaGate may fail fast, but must never wait.

Receipt logging, mirroring, and cleanup are best-effort and must never block /bootstrap.

MetaGate v0 Specification

Startup Receipts (Witness, Not Control)

Bootstrap is a moment in time.

MetaGate records that moment by creating a startup session:

OPEN — issued by MetaGate when the Welcome Packet is returned

READY — issued later by the component when initialized

FAILED — issued by the component if startup aborts

Absence of READY past SLA is meaningful state.

MetaGate is a witness of birth, not a babysitter.

Secrets Model (v0)

Secrets are references only

Default reference kind: environment variables

MetaGate never stores secret values

Inline secrets are explicitly deferred

API Overview

GET /.well-known/metagate.json — discovery

POST /v1/bootstrap — issue Welcome Packet + OPEN receipt

POST /v1/startup/ready — component self-reports readiness

POST /v1/startup/failed — component self-reports failure

Bootstrap responses may return 304 Not Modified when packet state is unchanged.

Design Invariants (Non-Negotiable)

MetaGate must never block on other services

MetaGate must never assign work

Every bootstrap creates exactly one OPEN receipt

Every component must self-report READY or FAILED

Secrets are references, not values

principal_key and component_key are always required

MetaGate is truth, not control
