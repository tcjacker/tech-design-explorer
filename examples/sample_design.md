# Hour Commit Decoupling

Status: Draft · Authors: Platform Team · Date: 2026-08-20

## Background

The simulation advances one in-world hour at a time. Today a single frontend
state machine owns both the player-facing progression *and* the durable commit
of an hour's results. When a commit fails halfway — a plugin hook raises, or the
database write times out — the frontend is already in the next hour and the two
views of the world diverge. Operators recover by hand-editing `session_cache`.

## Current state

Today `HourFSM` in `engine/fsm.py` owns both the player-visible hour and the durable
write. `ScenarioPlugin` hooks are compiled into the engine, and `session_cache` is
written without a version guard.

- A failed database write leaves the frontend an hour ahead of the stored state
- Operators recover by hand-editing `session_cache`
- Scenario rules cannot be changed without an engine release
- There is no metric that counts failed commits

## What changes in this design

| Component | Change | Why |
| --- | --- | --- |
| Backend FSM | New — owns the commit lifecycle | Gives partial failure an explicit state |
| Hour Commit Service | New — drafts, validates and persists | Separates execution from orchestration |
| Frontend FSM | Modified — keeps only player progression | The commit concern moves out |
| Session Store | Modified — CAS version column added | Makes concurrent writes detectable |
| Event Bus | New — publishes commit outcomes | Operators and metrics need a feed |
| Legacy commit path | Removed in phase 3 | Replaced by the Backend FSM |

## Goals

- Separate command orchestration from durable state commit
- Make retry and partial-failure handling explicit and observable
- Allow scenario plugins to hook the commit lifecycle without touching core code
- Keep the player-visible latency of a normal hour under 800ms

## Non-goals

- Do not redesign NPC memory or the prompt pipeline
- Do not change the public HTTP API shape in this phase
- No multi-region replication

## User stories

- As a player, I want an hour to advance without losing my chat log, so that a transient backend error is invisible to me.
- As an operator, I want a failed commit to be visible and retryable, so that I never hand-edit the database.
- As a scenario author, I want to run code before and after an hour commit, so that scenario rules stay out of the engine.

## Architecture

| Component | Responsibility |
| --- | --- |
| Web Client | Renders the hour, submits player commands |
| API Gateway | Auth, rate limiting, request routing |
| Frontend FSM | Owns player-visible progression state |
| Backend FSM | Owns the hour commit lifecycle |
| Hour Commit Service | Executes drafting, validation and persistence |
| Scenario Plugin | Scenario-specific hooks around the commit |
| Session Store | Postgres tables holding session and hour state |
| Event Bus | Publishes commit outcomes to observers |

## Runtime flow

1. Web Client -> API Gateway: submit hour command
2. API Gateway -> Frontend FSM: validate player state
3. Frontend FSM -> Backend FSM: request hour commit
4. Backend FSM -> Scenario Plugin: before_hour_tick()
5. Backend FSM -> Hour Commit Service: draft hour result
6. Hour Commit Service -> Session Store: persist draft with CAS version
7. Backend FSM -> Scenario Plugin: after_hour_tick()
8. Backend FSM -> Event Bus: publish commit outcome
9. Backend FSM -> Frontend FSM: commit acknowledged
10. Frontend FSM -> Web Client: render next hour

## State machine

The Backend FSM moves through IDLE, PREPARING, DRAFTING, COMMITTING and either
returns to IDLE or parks in FAILED.

- IDLE -> PREPARING: commit requested
- PREPARING -> DRAFTING: preconditions ok
- DRAFTING -> COMMITTING: draft ready
- COMMITTING -> IDLE: write acknowledged
- COMMITTING -> FAILED: write rejected
- PREPARING -> FAILED: precondition violated
- FAILED -> PREPARING: operator retry

## Data model

| Table | Description |
| --- | --- |
| session_cache | Hot per-session state, one row per session |
| hour_commit | One row per attempted hour commit |
| document | Narrative documents produced during an hour |
| document_version | Immutable versions of a document |

## Failure paths

- Backend FSM enters COMMITTING
- The CAS write is rejected because the version moved
- The FSM transitions to FAILED and publishes a failure event
- The retry policy decides whether to re-draft or park for an operator

## Rollout plan

### Phase 1: Scaffolding

- Introduce the Backend FSM behind a feature flag
- Mirror commits, compare outcomes, do not act on them

### Phase 2: Migration

- Move hour commit execution behind the Backend FSM
- Keep the legacy path as a fallback for one release

### Phase 3: Cleanup

- Delete the legacy commit path
- Remove the feature flag and the mirroring code

## Decisions

### Two state machines instead of one

Alternatives considered:

- Single FSM owning both concerns
- Two FSMs with an explicit boundary
- Event-sourced commit log with no FSM

## Risks

| Risk | Mitigation |
| --- | --- |
| State divergence between the two FSMs | CAS versioning plus a reconciliation job |
| Plugin hooks slow the commit path | Hook timeout budget of 200ms with a hard cancel |
| Migration doubles write load | Mirror phase runs at 10% sampling first |

## Open questions

- Should a FAILED commit auto-retry, or always wait for an operator?
- Where does the retry budget live — per session or global?

## Metrics

- p95 hour commit latency: under 800ms
- Failed commits requiring manual intervention: under 0.1%
