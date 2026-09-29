# TrueFit.ai — 6-Day MVP Implementation Plan

**Goal:** Ship a working, demonstrable MVP where both recruiter and candidate journeys are functional end-to-end: create job → candidate applies → live AI interview → evaluation generated → recruiter views report.

**Timeline:** 6 days (Sep 28 – Oct 3, 2026)  
**Source:** Ground-truth audit in [`doc.md`](file:///c:/Users/HomePC/dev/truefit.ai/doc.md)  
**Codebase:** Monorepo at [`apps/`](file:///c:/Users/HomePC/dev/truefit.ai/apps) — FastAPI backend + Vite/React frontend

---

## What "MVP-Done" Means

By end of Day 6, these user journeys must work end-to-end:

| Journey | Steps |
|---------|-------|
| **Recruiter** | Sign in → onboard (create org) → create job → view candidates → view evaluations |
| **Candidate** | Sign in → onboard → create profile → browse jobs → apply → start interview → live voice interview with Gemini → interview completes → evaluation generated |
| **System** | Interview completion → event consumed → LLM evaluation → scorecard stored in DB → visible to recruiter |

What's explicitly **deferred past MVP**: OpenAI fallback polish, PDF report rendering, video/screen-share to LLM, TLS in deploy script, production-grade monitoring.

---

## Codebase Status Summary

| Subsystem | Status | Key Files |
|-----------|--------|-----------|
| Auth (Firebase + JWT) | ✅ Working | [`auth.py`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_api/api/v1/http/auth.py), [`authContext.tsx`](file:///c:/Users/HomePC/dev/truefit.ai/apps/frontend/src/context/authContext.tsx) |
| Onboarding | ✅ Working | [`Onboarding.tsx`](file:///c:/Users/HomePC/dev/truefit.ai/apps/frontend/src/pages/Onboarding.tsx) |
| Recruiter CRUD (Jobs/Org/Candidates) | ✅ Working | [`Jobs.tsx`](file:///c:/Users/HomePC/dev/truefit.ai/apps/frontend/src/pages/Jobs.tsx), [`jobs.py`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_api/api/v1/http/jobs.py) |
| API layer (REST) | ✅ Working (1 bug) | [`interviews.py`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_api/api/v1/http/interviews.py) has `company_id` TypeError |
| Interview WS/WebRTC client | ✅ Working | [`useInterviewSession.ts`](file:///c:/Users/HomePC/dev/truefit.ai/apps/frontend/src/hooks/useInterviewSession.ts) |
| Interview WS handler (backend) | ✅ Working | [`interview_websocket.py`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_api/api/v1/ws/interview_websocket.py) |
| Gemini Live adapter | ✅ Working | [`gemini_live.py`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_infra/llm/gemini_live.py) |
| Interview agent + tools | ✅ Working (Gemini path) | [`live_interview_agent.py`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_core/agents/interviewer/live_interview_agent.py), [`tools.py`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_core/agents/interviewer/tools.py) |
| AudioBridge | ✅ Working (minor races) | [`audio_bridge.py`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_infra/realtime/audio_bridge.py) |
| **Candidate profile creation** | ❌ **Missing** | [`Profile.tsx`](file:///c:/Users/HomePC/dev/truefit.ai/apps/frontend/src/pages/Profile.tsx) — no create path |
| **Evaluation pipeline** | ❌ **Empty stubs** | [`evaluation_worker.py`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_workers/jobs/evaluation_worker.py), [`evaluator.py`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_core/agents/evaluator/evaluator.py) |
| **Backend startup** | ❌ **Crashes** (OPENAI_API_KEY) | [`factory.py`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_infra/llm/factory.py) |
| OpenAI Realtime adapter | ⚠️ Partial/Broken | [`openai_realtime.py`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_infra/llm/openai_realtime.py) — turn loop + tool registration bugs |
| Firebase verification | ⚠️ Empty file | [`firebase.py`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_infra/auth/firebase.py) — 0 bytes |

---

## All Items (24 total)

### P0 — Blocks startup or candidate journey

#### 1. Backend Startup Crash — OPENAI_API_KEY / Fallback Config
**Severity:** 🔴 App won't boot  
**Problem:** Default `LLM_FALLBACK_PROVIDER="openai"` with `OPENAI_API_KEY=None` crashes app startup. `OpenAIRealtimeAdapter.__init__` raises `RuntimeError`, and `factory.py` eagerly constructs both adapters at startup. `main.py` lifespan calls `get_orchestration() → get_live_adapter()`, so the whole app fails to boot.

**Files:**
- [`factory.py`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_infra/llm/factory.py) — eager dual construction at L99, L108
- [`config.py`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_infra/config.py) — L38-40 defaults
- [`openai_realtime.py`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_infra/llm/openai_realtime.py) — `__init__` raises on missing key

**Fix:**
- In `factory.py`, wrap `_make_adapter(fallback_name)` in a try/except; if the adapter raises on missing credentials, log a warning and fall back to "no fallback" mode.
- Change `config.py` default to `LLM_FALLBACK_PROVIDER: str = "none"` for safe out-of-box startup.
- Add a startup log message: "⚠️ OpenAI fallback disabled — set OPENAI_API_KEY to enable."

**Estimate:** 1 hour

---

#### 2. Candidate Profile Creation Gap (frontend)
**Severity:** 🔴 Entire candidate journey blocked  
**Problem:** `candidatesApi.register` exists but is called by zero components. `Profile.tsx` and `JobListings.tsx` both do `list().find(user_id === backendUser.id)` and, finding nothing, show "No candidate profile found" with no create path. This blocks: browse-apply, profile, candidate dashboard, candidate applications, and candidate-initiated interviews.

**Files:**
- [`Profile.tsx`](file:///c:/Users/HomePC/dev/truefit.ai/apps/frontend/src/pages/Profile.tsx) — needs "Create Profile" UI
- [`JobListings.tsx`](file:///c:/Users/HomePC/dev/truefit.ai/apps/frontend/src/pages/JobListings.tsx) — applied-check uses `backendUser.id` instead of candidate profile id
- [`candidates.api.ts`](file:///c:/Users/HomePC/dev/truefit.ai/apps/frontend/src/helpers/api/candidates.api.ts) — already has `register` method

**Fix:**
- Add a "Create Profile" button/modal on `Profile.tsx` (or auto-create on first visit for candidates).
- Call `candidatesApi.register` with the current user's id, name, email.
- After registration, re-fetch and navigate to the populated Profile.
- Wire `ProfileEditForm.tsx` to POST updates via `candidatesApi.update`.
- Fix `JobListings.tsx` applied-check: use the **candidate profile id**, not the user id. Store `candidateProfileId` in auth context or fetch from the candidate record.

**Estimate:** 2-3 hours

---

#### 3. REST Interview Route — company_id vs org_id TypeError
**Severity:** 🔴 POST /interviews crashes  
**Problem:** [`interviews.py`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_api/api/v1/http/interviews.py) L135-145 constructs `Interview(company_id=job.org_id, ...)` but the `Interview` domain constructor only accepts `org_id`. The WS path uses `org_id` correctly — only this REST route is broken.

**Files:**
- [`interviews.py`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_api/api/v1/http/interviews.py) L135-145

**Fix:**
- Change `company_id=job.org_id` → `org_id=job.org_id`.
- Grep for any other `company_id` references and fix.

**Estimate:** 15 minutes

---

### P1 — Breaks core interview flow

#### 4. Interview Start Requires Pre-Existing Application
**Severity:** 🟠 Cold-start interview fails  
**Problem:** `SQLAlchemyInterviewRepository.save` raises `ValueError` if no Application exists for the job+candidate ([`interview_repository.py`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_infra/db/repositories/interview_repository.py) L52-56). Nothing in the WS flow creates one, so a candidate who hasn't applied through the UI cannot start an interview.

**Fix:**
- In the WS `start_interview` path, if no Application exists, auto-create one with status "interviewing" before creating the Interview.
- Coordinate with item 2 so the frontend apply flow also creates an Application.

**Estimate:** 1 hour

---

#### 5. max_questions / max_duration_minutes Not Persisted
**Severity:** 🟠 Interview limits silently revert to defaults on reload  
**Problem:** `save()` never writes the realtime JSONB column, but `_to_domain` reads from it ([`interview_repository.py`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_infra/db/repositories/interview_repository.py) L353-362). Any reload reverts to 10 questions / 30 minutes.

**Fix:**
- In `save()`, persist `max_questions` and `max_duration_minutes` into the realtime JSONB column.
- Verify round-trip read-back in `_to_domain`.

**Estimate:** 1 hour

---

#### 6. ApplicationRow — Start Interview Guard + Route
**Severity:** 🟠 Button renders for everyone, navigates to wrong route  
**Problem:** [`ApplicationRow.tsx`](file:///c:/Users/HomePC/dev/truefit.ai/apps/frontend/src/components/ApplicationRow.tsx) L53-64 — `canStartInterview` guard is commented out. Button shows for every application including recruiter view. For recruiters, `candidateProfileId` is undefined → `/itv/{jobId}/undefined`. Also points at `/itv` (public dev route) not `/interview` (protected).

**Fix:**
- Re-enable the `canStartInterview` guard.
- Point button at `/interview/{jobId}/{candidateId}` (protected route).
- Hide button for recruiter view.

**Estimate:** 1 hour

---

#### 7. Resume Upload — Missing Auth Header
**Severity:** 🟠 Resume uploads 401  
**Problem:** [`Profile.tsx`](file:///c:/Users/HomePC/dev/truefit.ai/apps/frontend/src/pages/Profile.tsx) L131-147 uses raw `fetch` with no `Authorization` header, bypassing the axios interceptor.

**Fix:**
- Use the axios instance from `helpers/api.ts` instead of raw fetch, OR add the `Authorization: Bearer <jwt>` header manually.

**Estimate:** 30 minutes

---

#### 8. Candidate Resume Text Hardcoded to None
**Severity:** 🟡 Interview quality degraded  
**Problem:** `candidate_resume_text=None` hardcoded in [`interview_websocket.py`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_api/api/v1/ws/interview_websocket.py) L875. The agent doesn't get resume context.

**Fix:**
- Load the candidate's resume text from DB/storage and inject into agent context.

**Estimate:** 2 hours

---

### P1-HEAVY — Evaluation Pipeline (largest item)

#### 9. Evaluation / Report Pipeline — COMPLETELY MISSING
**Severity:** 🔴 Core product feature non-existent  
**Problem:** After an interview ends, `interview.completed` is published to Redis and the chain dead-ends. Nothing consumes it. The evaluator, workers, storage adapter, evaluation repo, and LLM evaluation method are all missing or empty.

**What's empty/missing:**
- [`evaluation_worker.py`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_workers/jobs/evaluation_worker.py) — 1 comment line
- [`report_worker.py`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_workers/jobs/report_worker.py) — 1 comment line  
- [`evaluator.py`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_core/agents/evaluator/evaluator.py) — 0 bytes
- No `StoragePort` implementation
- No `SQLAlchemyEvaluationRepository`
- [`GeminiLLMAdapter`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_infra/llm/gemini_llm.py) missing `generate_question` and `evaluate_interview` abstract methods
- [`RedisQueueAdapter`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_infra/queue/redis_queue.py) — publish-only, no consumer
- No worker process entrypoint; `WORKERS_ENABLED` config exists but never read

**What already exists and is usable:**
- [`EvaluationService`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_core/application/services/evaluation_service.py) — 281 lines of real logic, fully implemented but never invoked
- [`Evaluation` domain model](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_core/domain/evaluation.py) — complete with scores, recommendation, etc.
- [`EvaluationRepository` port](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_core/application/ports.py) L139-159 — abstract interface defined
- [`LLMPort`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_core/application/ports.py) L224-247 — abstract interface with `evaluate_interview` defined
- [`EvaluationRequest` / `LLMEvaluationResult`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_core/application/ports.py) L193-221 — data classes defined
- DB models in [`models.py`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_infra/db/models.py) — likely has evaluation table

**Files to create/implement:**

| # | File | What |
|---|------|------|
| A | `truefit_infra/db/repositories/evaluation_repository.py` | `SQLAlchemyEvaluationRepository` implementing `EvaluationRepository` port |
| B | `truefit_infra/llm/gemini_llm.py` | Add `generate_question()` and `evaluate_interview()` to `GeminiLLMAdapter` |
| C | `truefit_infra/storage/local_storage.py` | `LocalStorageAdapter` implementing `StoragePort` (filesystem-based for MVP) |
| D | `truefit_infra/queue/redis_queue.py` | Add `consume()` method with `xreadgroup`/`xread` |
| E | `truefit_workers/jobs/evaluation_worker.py` | Real worker: consume `interview.completed` → call `EvaluationService.generate_evaluation()` |
| F | `truefit_workers/run.py` | Worker process entrypoint CLI |
| G | Wire into `main.py` lifespan | If `WORKERS_ENABLED=true`, start worker as background task |

**MVP simplification:**
- Skip PDF report rendering — JSON evaluation stored in DB is sufficient.
- Skip `report_worker.py` — `EvaluationService` already handles report upload inline.
- Use local filesystem storage (`LocalStorageAdapter`) instead of S3/GCS.
- Run the worker as a background task in `main.py` lifespan rather than a separate process.

**Estimate:** 8-12 hours (spread across Days 2-4)

---

### P2 — Bugs and quality

#### 10. OpenAI Realtime Turn-Loop Bug
**Severity:** 🟡 OpenAI fallback hangs after candidate speaks  
**Problem:** With `turn_detection=None`, OpenAI doesn't auto-generate a response on `input_audio_buffer.commit` — you must send `response.create`. But `send_activity_end` and `send_audio_stream_end` only commit — no `response.create`.

**Files:** [`openai_realtime.py`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_infra/llm/openai_realtime.py) L215, L587

**Fix:** After `input_audio_buffer.commit`, send `response.create`.

**Estimate:** 1-2 hours  
**MVP note:** Can defer if only using Gemini as primary with no fallback.

---

#### 11. OpenAI Tool Registration — Gemini Wrapper Not Unwrapped
**Severity:** 🟡 Zero tools register on OpenAI path  
**Problem:** Tool converter doesn't unwrap Gemini's `{"function_declarations": [...]}` wrapper.

**Files:** [`openai_realtime.py`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_infra/llm/openai_realtime.py) L638-656

**Fix:** Detect and unwrap the Gemini-shaped wrapper before processing.

**Estimate:** 1 hour  
**MVP note:** Can defer if only using Gemini.

---

#### 12. Duplicate Interview Pages
**Severity:** 🟡 Maintenance risk  
**Problem:** [`InterviewPage.tsx`](file:///c:/Users/HomePC/dev/truefit.ai/apps/frontend/src/pages/InterviewPage.tsx) and [`ItvPage.tsx`](file:///c:/Users/HomePC/dev/truefit.ai/apps/frontend/src/pages/ItvPage.tsx) are duplicates.

**Fix:** Consolidate into one component. Have `InterviewPage.tsx` re-export or wrap with the protected guard.

**Estimate:** 30 minutes

---

#### 13. Dual Interrupt Mechanisms Race
**Severity:** 🟡 Audio can un-suppress prematurely  
**Problem:** Two independent interrupt mechanisms race on `_suppress_audio` flag in [`interview_websocket.py`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_api/api/v1/ws/interview_websocket.py).

**Fix:** Use a reference-counted suppress flag.

**Estimate:** 1 hour

---

#### 14. ICE Trickle Race + DataChannel No-Op
**Severity:** 🟡 Edge case  
**Problem:** `_forward_ice` attached after `setLocalDescription`; DataChannel inbound is no-op.

**Fix:** Attach `_forward_ice` before `setLocalDescription`.

**Estimate:** 1 hour

---

#### 15. Dead VAD Timeout Helpers
**Severity:** 🟡 Can cause dead air after greeting  
**Problem:** `_schedule_vad_unlock_timeout`/`_arm_vad_unlock_timeout` in [`audio_bridge.py`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_infra/realtime/audio_bridge.py) are never called.

**Fix:** Wire VAD unlock into the greeting flow.

**Estimate:** 30 minutes

---

#### 16. FrameSampler — Orphaned / Dead-Ended
**Severity:** 🟢 Dead code  
**Problem:** [`frame_sampler.py`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_infra/realtime/frame_sampler.py) samples JPEGs but nothing consumes them.

**Fix:** Disable FrameSampler entirely with a TODO. Video-to-LLM is aspirational, not MVP.

**Estimate:** 30 minutes (or skip)

---

### P3 — Cosmetic and deploy

#### 17. Firebase.py — Empty (0 bytes)
**Problem:** [`firebase.py`](file:///c:/Users/HomePC/dev/truefit.ai/apps/backend/src/truefit_infra/auth/firebase.py) is 0 bytes. Backend must verify Firebase tokens somehow.

**Fix:** Implement `verify_firebase_token()` using Firebase Admin SDK or JWT verification against Google's public certs. OR verify if auth already works via a different path and document it.

**Estimate:** 2 hours

---

#### 18. env.example — Wrong WS URL + Trailing Comma
**Problem:** [`env.example`](file:///c:/Users/HomePC/dev/truefit.ai/apps/frontend/env.example) has wrong `VITE_PUBLIC_WS_URL`.

**Fix:** Fix URL and trailing comma.

**Estimate:** 5 minutes

---

#### 19. Vite Proxy — Misconfigured but Inert
**Problem:** [`vite.config.ts`](file:///c:/Users/HomePC/dev/truefit.ai/apps/frontend/vite.config.ts) proxies to `https://127.0.0.1:8000` but axios uses absolute URLs.

**Fix:** Fix to `http://` or remove the proxy config.

**Estimate:** 15 minutes

---

#### 20. Cosmetic Type Errors
**Problem:** Typos in [`orgs.api.ts`](file:///c:/Users/HomePC/dev/truefit.ai/apps/frontend/src/helpers/api/orgs.api.ts) (`statu?`), [`jobs.api.ts`](file:///c:/Users/HomePC/dev/truefit.ai/apps/frontend/src/helpers/api/jobs.api.ts) (`hyybrid`), [`turn.api.ts`](file:///c:/Users/HomePC/dev/truefit.ai/apps/frontend/src/helpers/api/turn.api.ts) (no leading `/`).

**Fix:** Correct all typos.

**Estimate:** 15 minutes

---

#### 21. Dashboard Stats Hardcoded to 0
**Problem:** [`Dashboard.tsx`](file:///c:/Users/HomePC/dev/truefit.ai/apps/frontend/src/pages/Dashboard.tsx) `totalCandidates`/`totalInterviews` hardcoded to 0; apps not org-scoped.

**Fix:** Compute from actual data; scope by `org_id`.

**Estimate:** 1 hour

---

#### 22. crypto.randomUUID Polyfill — Non-Unique
**Problem:** [`main.tsx`](file:///c:/Users/HomePC/dev/truefit.ai/apps/frontend/src/main.tsx) polyfill produces near-constant values.

**Fix:** Use `crypto.getRandomValues`-based UUID v4 polyfill.

**Estimate:** 30 minutes

---

#### 23. No TLS / HTTPS in Deploy
**Problem:** [`deploy.sh`](file:///c:/Users/HomePC/dev/truefit.ai/scripts/deploy.sh) sets up nginx HTTP :80 only. Browser mic requires HTTPS.

**Fix:** Add certbot/Let's Encrypt or document TLS requirement.

**Estimate:** 2-3 hours (or document as deploy-platform responsibility)

---

#### 24. Dead Stubs — Listings.tsx, Listing.tsx, Header.tsx
**Problem:** [`Listings.tsx`](file:///c:/Users/HomePC/dev/truefit.ai/apps/frontend/src/pages/Listings.tsx), [`Listing.tsx`](file:///c:/Users/HomePC/dev/truefit.ai/apps/frontend/src/components/Listing.tsx), [`Header.tsx`](file:///c:/Users/HomePC/dev/truefit.ai/apps/frontend/src/components/Header.tsx) — dead stubs.

**Fix:** Delete with TODO or implement if needed.

**Estimate:** 30 minutes

---

## 6-Day Schedule

### Day 1 (Sep 28) — Unblock Startup + Candidate Journey

> **Goal:** App boots. A candidate can create a profile and apply for a job.

| Block | Items | Est. | Details |
|-------|-------|------|---------|
| **Morning** | **#1** Backend startup crash | 1h | Fix `factory.py` fallback construction; change config default to `none` |
| | **#3** REST interview `company_id` TypeError | 15m | One-line fix in `interviews.py` |
| | **#18** env.example + trailing comma | 5m | Quick fix |
| | **#20** Cosmetic type typos | 15m | Quick wins |
| **Afternoon** | **#2** Candidate profile creation gap | 2-3h | Build "Create Profile" UI in `Profile.tsx`; wire `candidatesApi.register`; fix `JobListings.tsx` applied-check |
| **EOD** | Verify: App boots → Auth works → Recruiter creates job → Candidate creates profile → Candidate applies |

**Day 1 total:** ~4-5 hours of work

---

### Day 2 (Sep 29) — Interview Flow Fixes + Start Evaluation Pipeline

> **Goal:** A candidate can start and complete a live interview. Evaluation pipeline skeleton is in place.

| Block | Items | Est. | Details |
|-------|-------|------|---------|
| **Morning** | **#4** Interview requires pre-existing Application | 1h | Auto-create Application in WS start path |
| | **#5** max_questions/max_duration not persisted | 1h | Fix `save()` in interview_repository |
| | **#6** ApplicationRow guard + route fix | 1h | Re-enable guard, fix route to `/interview` |
| | **#7** Resume upload auth header | 30m | Switch to axios or add header |
| **Afternoon** | **#9a** Evaluation pipeline — infrastructure | 4h | Implement `SQLAlchemyEvaluationRepository`, `LocalStorageAdapter`, add `consume()` to `RedisQueueAdapter` |
| **EOD** | Verify: Candidate can start interview from application → Interview runs on Gemini path → Interview completes + event published |

**Day 2 total:** ~8-9 hours of work

---

### Day 3 (Sep 30) — Complete Evaluation Pipeline

> **Goal:** Interview completion triggers evaluation generation. Scorecard stored in DB.

| Block | Items | Est. | Details |
|-------|-------|------|---------|
| **Morning** | **#9b** `GeminiLLMAdapter.evaluate_interview()` | 3h | Implement the method: build prompt from `EvaluationRequest`, call Gemini with structured output, return `LLMEvaluationResult` |
| **Afternoon** | **#9c** Worker + wiring | 3h | Implement `evaluation_worker.py` consumer loop, wire into `main.py` lifespan as background task, connect `EvaluationService` to real dependencies |
| | **#9d** Frontend: evaluation display | 2h | Add evaluation view to recruiter's `CandidateDetail` or `JobDetail` page — show scores, recommendation, strengths/weaknesses |
| **EOD** | Verify: Complete interview → `interview.completed` consumed → Evaluation generated → Stored in DB → Visible in recruiter UI |

**Day 3 total:** ~8 hours of work

---

### Day 4 (Oct 1) — Interview Quality + Bugs

> **Goal:** Interview experience is polished. Resume context injected. Key bugs fixed.

| Block | Items | Est. | Details |
|-------|-------|------|---------|
| **Morning** | **#8** Resume text injection | 2h | Load candidate resume text, inject into agent context |
| | **#12** Duplicate pages consolidation | 30m | Merge `InterviewPage.tsx` / `ItvPage.tsx` |
| | **#15** Dead VAD timeout helpers | 30m | Wire into greeting flow |
| **Afternoon** | **#13** Dual interrupt race | 1h | Ref-counted suppress flag |
| | **#14** ICE trickle race | 1h | Attach `_forward_ice` before `setLocalDescription` |
| | **#16** FrameSampler — disable | 30m | Stop sampling, add TODO |
| | **#21** Dashboard stats | 1h | Compute from real data |
| **EOD** | Full flow test: Apply → Interview → Evaluation → Recruiter views report |

**Day 4 total:** ~7 hours of work

---

### Day 5 (Oct 2) — Auth Hardening + OpenAI Fallback + Polish

> **Goal:** Firebase verification confirmed working. OpenAI fallback functional (if time permits). UI polish.

| Block | Items | Est. | Details |
|-------|-------|------|---------|
| **Morning** | **#17** Firebase.py verification | 2h | Implement or verify existing auth path works |
| | **#10** OpenAI turn-loop bug | 1-2h | Add `response.create` after commit (defer if Gemini-only is sufficient for MVP) |
| | **#11** OpenAI tool registration | 1h | Unwrap Gemini format (defer if Gemini-only) |
| **Afternoon** | **#19** Vite proxy fix | 15m | |
| | **#22** crypto.randomUUID polyfill | 30m | |
| | **#24** Dead stubs cleanup | 30m | |
| **EOD** | Verify: Auth flow hardened. If OpenAI fallback touched: test interview on OpenAI path. |

**Day 5 total:** ~5-7 hours of work

---

### Day 6 (Oct 3) — Integration Testing + Deploy Readiness

> **Goal:** Full end-to-end smoke test passes. Deployment script works (at least HTTP). Documentation updated.

| Block | Items | Est. | Details |
|-------|-------|------|---------|
| **Morning** | End-to-end smoke test | 2h | Recruiter journey + Candidate journey + Evaluation pipeline |
| | Fix any bugs found in smoke test | 2h | Buffer time |
| **Afternoon** | **#23** TLS/HTTPS in deploy | 2h | Add certbot or document requirement |
| | Update README + deployment runbook | 1h | Document env vars, required services, startup sequence |
| | Final regression test | 1h | |
| **EOD** | ✅ MVP deployed or deployable |

**Day 6 total:** ~6-8 hours of work

---

## Prioritization Summary

### P0 — Blocks startup or candidate journey (Day 1)
| # | Item | Est. |
|---|------|------|
| 1 | Backend startup crash (OPENAI_API_KEY) | 1h |
| 2 | Candidate profile creation gap | 2-3h |
| 3 | REST interview route TypeError | 15m |

### P1 — Breaks core interview/evaluation flow (Days 2-3)
| # | Item | Est. |
|---|------|------|
| 4 | Interview requires pre-existing Application | 1h |
| 5 | max_questions/max_duration not persisted | 1h |
| 6 | ApplicationRow guard + route | 1h |
| 7 | Resume upload auth header | 30m |
| 8 | Resume text hardcoded None | 2h |
| 9 | **Evaluation pipeline (HEAVIEST)** | **8-12h** |

### P2 — Bugs and quality (Day 4)
| # | Item | Est. |
|---|------|------|
| 10 | OpenAI turn-loop bug | 1-2h |
| 11 | OpenAI tool registration | 1h |
| 12 | Duplicate interview pages | 30m |
| 13 | Dual interrupt race | 1h |
| 14 | ICE trickle race + DataChannel | 1h |
| 15 | Dead VAD timeout helpers | 30m |
| 16 | FrameSampler orphaned | 30m |

### P3 — Cosmetic and deploy (Days 5-6)
| # | Item | Est. |
|---|------|------|
| 17 | Firebase.py empty | 2h |
| 18 | env.example wrong WS URL | 5m |
| 19 | Vite proxy misconfigured | 15m |
| 20 | Cosmetic type typos | 15m |
| 21 | Dashboard stats hardcoded | 1h |
| 22 | crypto.randomUUID polyfill | 30m |
| 23 | No TLS in deploy | 2-3h |
| 24 | Dead stubs | 30m |

**Total estimated work:** ~45-55 hours across 6 days

---

## Risk Items

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Evaluation pipeline (#9) is ~12h of work** | If it slips, core product feature is missing | Start Day 2 afternoon, dedicate all of Day 3. Ship with evaluation even if OpenAI fallback is deferred. |
| **Firebase.py (#17) may block auth** | If Firebase token verification doesn't work at all, no user can log in | Verify early on Day 1 during smoke test — if auth works today, this is just a documentation gap |
| **OpenAI fallback (#10, #11) may not be needed for MVP** | If only Gemini is available, these are wasted effort | Defer OpenAI items to Day 5. MVP ships Gemini-only if needed. |
| **No TLS (#23) blocks production mic access** | Browsers require HTTPS for `getUserMedia` | Can demo on localhost. For real deploy, add certbot or use a TLS-terminating load balancer. |

---

## External Dependencies (must be provisioned)

| Dependency | Status | Notes |
|------------|--------|-------|
| PostgreSQL | Required | Run `alembic upgrade head` (3 migration versions exist) |
| Redis | Required | For WS pub/sub, interrupt flags, and evaluation queue |
| Gemini API key | Required | Primary LLM — set `GEMINI_API_KEY` in `.env` |
| OpenAI API key | Optional | Only if using fallback — set `OPENAI_API_KEY` |
| Firebase project | Configured | Keys already in `.env` (project: truefit-b6989) |
| TLS-enabled deploy target | Required for prod | Or certbot in `deploy.sh` |
