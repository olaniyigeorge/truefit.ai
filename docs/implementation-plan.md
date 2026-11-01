# TrueFit.ai / Soro Implementation Plan

## Goal

Finish TrueFit.ai as a reusable Soro voice-agent platform with:

1. A stable published SDK.
2. A working local/free pipeline.
3. Two non-interview example applications.
4. A hosted API and client SDKs.
5. Reliable CI, evaluations, and documentation.

## Backlog audit — 2026-11-01

The GitHub backlog was reviewed against the current `main` branch and the Soro pivot.
All six open issues are operationally stale: issues #6, #7, #8, #9 and #12 were last
updated in May 2026, and PR #15 was last updated on 2026-09-30. They should remain
visible as product context, but the old issue wording must not drive implementation
without being refreshed.

### Keep, but reframe for the current architecture

- [#7 Structured outputs for evaluation results](https://github.com/olaniyigeorge/truefit.ai/issues/7)
  remains a valid interview-app requirement. The current app already has typed domain
  objects and a Pydantic-backed Gemini JSON helper, but the LLM evaluation contract,
  malformed-output fallback, and frontend/API contract still need an explicit test
  gate. Fold this into **Phase 0**, before publishing Soro or adding new product
  features.
- [#9 Add LLM call observability](https://github.com/olaniyigeorge/truefit.ai/issues/9)
  remains aligned with Soro's platform direction. Implement provider-neutral structured
  logs, session/correlation IDs, token usage where providers expose it, and latency
  metrics for STT, LLM, TTS, tools, and time to first audio. This belongs in **Phase 2**
  and **Phase 7**, with the SDK metrics kept separate from product analytics.
- [#12 Add Async Evaluation Worker Orchestration](https://github.com/olaniyigeorge/truefit.ai/issues/12)
  remains useful for the TrueFit reference consumer, but it is not a prerequisite for
  the Soro SDK. The current worker files are still placeholders and the architecture
  notes that `interview.completed` is not yet published. Schedule it after the
  evaluation contract is stable, as a product-side implementation of **Phase 0** and
  the production-hardening work in **Phase 7**.

### Keep as a later product capability, not core Soro scope

- [#6 RAG pipeline for resume + JD analysis](https://github.com/olaniyigeorge/truefit.ai/issues/6)
  is still relevant to interview quality, but it is an application feature. Build it
  behind replaceable repository/embedding ports after the evaluation contract and
  async worker are stable. Do not add resume-specific retrieval concepts to Soro.
- [#8 Role fit compliance checker](https://github.com/olaniyigeorge/truefit.ai/issues/8)
  is still aligned with TrueFit's hiring product, but it overlaps with #6 and should
  be merged into one candidate/job evidence analysis track. Its output should reuse
  the structured evaluation schema from #7 rather than introduce a second scoring
  format. Place it after #6 in the product backlog, before any hosted API work that
  depends on a stable consumer.

### PR #15 — do not merge as-is

- [PR #15: check candidate's resume against the job description](https://github.com/olaniyigeorge/truefit.ai/pull/15)
  has the right product intent and is a useful prototype for #6/#8, but it is stale
  and currently unmergeable: GitHub reports a dirty merge state; the branch is based
  on the old `apps/backend` layout while `main` now uses `examples/truefit` and Soro;
  it hard-wires Gemini into the WebSocket path; and the reviewed diff contains the
  known `_get_resume_summary` scoping bug plus root-level debug/test scripts. It also
  changes dependency pins and deployment files unrelated to the feature.

  Treat it as a design reference only. Re-implement the smallest useful slice in the
  current reference app after #7: a provider-independent resume-analysis port, a
  validated result schema, non-blocking/fail-open interview startup behavior, tests
  with fake providers, and no changes to Soro's provider-neutral runtime. Close or
  supersede the PR once that replacement work is planned; do not revive the branch.

### Updated product/platform order

```text
Phase 0: setup + evaluation contract (#7) + baseline verification
        ↓
Phase 1: publish Soro 0.1
        ↓
Phase 2: SDK hardening + observability (#9)
        ↓
TrueFit consumer: async evaluation orchestration (#12)
        ↓
TrueFit consumer: resume/JD evidence analysis (#6 + #8; PR #15 replacement)
        ↓
Personal OS assistant → meeting copilot
        ↓
Hosted API and client SDKs
        ↓
Production hardening
```

This keeps the strategic direction intact: Soro stays reusable infrastructure, while
resume matching, compliance, and interview evaluation remain capabilities of the
TrueFit reference consumer.

### GitHub cleanup

After this audit, the old GitHub records can be closed without losing the decisions:
the links and dispositions above are the durable record in this plan. PR #15 should
be closed as superseded. Issues #6, #7, #8, #9, and #12 can also be closed as stale
and re-opened later as smaller implementation issues when each workstream starts.

## Phase 0 — Close the current work

1. Run `scripts/setup-local-composed.sh`.
2. Verify PostgreSQL and Redis startup, Ollama model download, Whisper and Piper initialization, Alembic migrations, and `make dev`.
3. Run all unit and integration tests.
4. Fix setup or CI failures.
5. Update the top-level README so it no longer says the composed pipeline is planned.
6. Replace the old freeform evaluation expectation with one validated application
   contract: typed result schema, malformed-output fallback, API serialization, and
   frontend consumption. This is the implementation of #7.
7. Commit the staged setup changes.

**Deliverable:** reproducible local development on a clean macOS machine.

**Progress (2026-11-01):** The local setup now reports OS/architecture, supports
macOS and Linux from Bash, and has a native Windows PowerShell entry point. The
composed dependencies, fresh-database migrations, existing-database stamping path,
backend suite, Soro suite, frontend build, and Ruff checks have been verified. Issue
#7's validated evaluation contract and provider fallback are implemented. Remaining
Phase 0 work is wiring the evaluation generation into the async worker path and
finishing the clean-README/setup commit before Phase 1.

## Phase 1 — Publish Soro 0.1

1. Add final package metadata and versioning.
2. Build the wheel and source distribution.
3. Run `make soro-test`, `make soro-smoke`, and `twine check dist/*`.
4. Upload to TestPyPI.
5. Install Soro from a clean virtual environment and run the smoke test.
6. Document installation from PyPI and TestPyPI.
7. Add release CI that builds the package and runs package-only tests.

**Deliverable:** installable `soro==0.1.0`.

## Phase 2 — Harden the SDK

1. Add the composed adapter to the shared adapter contract suite.
2. Add tests for barge-in during TTS, Whisper silence/noise rejection, streaming LLM tool calls, tool-call ordering, session shutdown, cancellation, provider fallback, and session recovery.
3. Define stable public APIs and mark experimental APIs.
4. Add structured logging and session IDs.
5. Add latency metrics for time to first audio, STT, LLM, TTS, and tool calls.
6. Improve error messages for missing models, services, and optional dependencies.

**Deliverable:** a dependable SDK suitable for outside consumers.

## Phase 3 — Build the personal OS assistant

Create `examples/personal-os/` as the first non-interview Soro consumer.

Initial capabilities:

- Notes and knowledge-base search.
- Calendar lookup and event creation.
- Reminders and task management.
- Confirmation before destructive actions.
- Background execution for slow searches.
- Spoken summaries of tool results.

Implementation order:

1. Define the domain-neutral assistant prompt.
2. Add sample function tools.
3. Add an OpenAPI connector example.
4. Add an MCP connector example.
5. Add confirmation policies.
6. Add scripted evaluation scenarios.
7. Add a CLI/text harness before voice.
8. Add voice support through Soro.
9. Add persistence behind replaceable repositories.

**Deliverable:** a working assistant demonstrating that Soro is useful outside interviews.

## Phase 4 — Build the meeting copilot

Create `examples/meeting-copilot/`.

Initial capabilities:

- Receive a meeting audio stream.
- Transcribe speech.
- Track speakers where possible.
- Extract decisions, action items, and unresolved questions.
- Answer spoken questions such as “What did we decide about pricing?”
- Save meeting summaries and tasks.
- Avoid taking external actions without confirmation.

Implementation order:

1. Build transcript ingestion independently of voice output.
2. Add meeting state and rolling summaries.
3. Add action-item extraction.
4. Add knowledge-base retrieval.
5. Add spoken query handling through Soro.
6. Add Markdown and JSON export.
7. Add evaluation fixtures with expected decisions and action items.
8. Add a simple web UI after the core flow works.

**Deliverable:** a useful meeting assistant built on the same runtime and connector model.

## Phase 5 — Add the hosted API

Build this only after the SDK and one external-style consumer are stable.

Suggested endpoints:

```text
POST /v1/sessions
POST /v1/sessions/{id}/token
GET  /v1/sessions/{id}
WS   /v1/sessions/{id}/audio
POST /v1/tools
GET  /v1/health
```

Architecture:

- The hosted API manages sessions and authentication.
- Soro remains responsible for runtime, adapters, tools, and provider selection.
- Customer applications own their third-party credentials.
- Browser and mobile clients receive short-lived session tokens.
- Server-to-server clients use tenant API keys.

Build order:

1. Session model and lifecycle.
2. Tenant and API-key authentication.
3. Short-lived browser session tokens.
4. WebSocket audio transport.
5. Provider configuration per session.
6. Tool registration and connector lifecycle.
7. Usage and latency metrics.
8. Rate limiting and quotas.
9. Audit logs.
10. Cleanup of expired sessions and background tasks.

**Deliverable:** a minimal hosted voice-session API without taking custody of users’ external credentials.

## Phase 6 — Build client SDKs

Start with TypeScript, then add Python.

### TypeScript SDK

- Create a session.
- Obtain an ephemeral token.
- Connect microphone and speaker.
- Receive transcript and status events.
- Handle reconnects.
- Expose tool and session errors.

### Python SDK

- Create server-to-server sessions.
- Stream audio.
- Register tools.
- Consume session and transcript events.
- Manage the async session lifecycle with a context manager.

**Deliverable:** browser, Node, and Python consumers can use the hosted API without manually handling the WebSocket protocol.

## Phase 7 — Production readiness

1. Add migrations for tenants, keys, sessions, usage, and audit events.
2. Add Redis-backed session state.
3. Add background workers for cleanup and evaluation jobs.
4. Add provider health checks.
5. Add request tracing and structured logs.
6. Add security tests for tenant isolation, expired tokens, tool authorization, WebSocket authentication, and replay protection.
7. Add load tests for concurrent sessions.
8. Add deployment documentation and rollback procedures.
9. Add billing hooks, even if billing is initially disabled.

**Deliverable:** a deployable alpha service with clear operational boundaries.

## Phase 8 — Documentation and product cleanup

Update:

- `README.md`
- `docs/architecture.md`
- `docs/api.md`
- `docs/build-plan.md`
- `packages/soro/README.md`

Add documentation for:

- Local composed-mode setup.
- Gemini and OpenAI setup.
- Building a first Soro agent.
- Connectors.
- The hosted API.
- Provider comparison.
- Hardware requirements for local models.
- Limitations of composed speech-to-text-to-speech.
- Versioning and compatibility.

## Recommended sequence

```text
Current setup verification
        ↓
Soro 0.1 publication
        ↓
SDK hardening
        ↓
Personal OS assistant
        ↓
Meeting copilot
        ↓
Hosted API
        ↓
TypeScript/Python client SDKs
        ↓
Production hardening
```

The hosted API should wait until Soro has a stable public contract and at least one non-interview consumer. This prevents freezing APIs that are still changing.
