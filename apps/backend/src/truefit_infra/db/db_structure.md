# Database Structure
- Check out the [visualized database schema.](https://dbdiagram.io/d/69a419f4a3f0aa31e16e092f) 

## High-level entities

- **Organizations** (companies) → create Job Listings
- **Users** (both recruiters + candidates) → belong to org optionally
- **Candidates** (profile) → apply to jobs
- **Applications** → job ↔ candidate relationship + status
- **Interview Sessions** → one per application (or multiple rounds)
- **Interview Turns** → each message/utterance (candidate/agent/system)
- **Media Assets** → audio/video chunks, recordings, images, attachments
- **Transcripts** → derived text from audio + alignment
- **Evaluations** → scoring + recommendation + report output
- **Rubrics & Criteria** → job-specific scoring definition
- **Audit/Event Log** → important for debugging live sessions (interruptions, reconnects)

## Core tables (recommended)

### 1) orgs
Stores companies.

| Field | Type | Notes |
|-------|------|-------|
| id | uuid pk | Primary key |
| name | string | |
| slug | string | unique |
| created_at | timestamp | |
| updated_at | timestamp | |

### 2) users
Auth identity. Can represent recruiter or candidate account (or both).

| Field | Type | Notes |
|-------|------|-------|
| id | uuid pk | Primary key |
| org_id | uuid fk | → orgs.id, nullable (recruiters belong to org) |
| email | string | unique |
| display_name | string | |
| role | enum | recruiter \| admin \| candidate |
| auth_provider | string | e.g. firebase, custom |
| provider_subject | string | uid from provider |
| is_active | boolean | |
| created_at | timestamp | |
| updated_at | timestamp | |

> **Note:** If you prefer, keep candidates separate and allow users only for recruiters. But it's usually simpler to have one users table.

### 3) candidate_profiles
Candidate-specific details.

| Field | Type | Notes |
|-------|------|-------|
| id | uuid pk | Primary key |
| user_id | uuid fk | unique → users.id |
| headline | string | |
| bio | text | |
| location | string | |
| years_experience | int | |
| skills | text[] or jsonb | |
| resume_asset_id | uuid fk | → media_assets.id, nullable |
| created_at | timestamp | |
| updated_at | timestamp | |

### 4) job_listings
Job definitions and interview configuration.

| Field | Type | Notes |
|-------|------|-------|
| id | uuid pk | Primary key |
| org_id | uuid fk | → orgs.id |
| created_by | uuid fk | → users.id |
| title | string | |
| description | text | |
| requirements | jsonb | structured requirements |
| status | enum | draft \| open \| closed |
| interview_config | jsonb | question style, duration, rubric reference, etc. |
| created_at | timestamp | |
| updated_at | timestamp | |

### 5) rubrics
Reusable scoring rubric.

| Field | Type | Notes |
|-------|------|-------|
| id | uuid pk | Primary key |
| org_id | uuid fk | → orgs.id |
| name | string | |
| version | int | |
| notes | text | |
| created_at | timestamp | |
| updated_at | timestamp | |

### 6) rubric_criteria
Rubric criteria rows.

| Field | Type | Notes |
|-------|------|-------|
| id | uuid pk | Primary key |
| rubric_id | uuid fk | → rubrics.id |
| key | string | e.g. communication, problem_solving |
| label | string | |
| description | text | |
| weight | numeric | |
| max_score | int | |
| order_index | int | |
| created_at | timestamp | |
| updated_at | timestamp | |

### 7) applications
Candidate applying for a job (or invited).

| Field | Type | Notes |
|-------|------|-------|
| id | uuid pk | Primary key |
| job_id | uuid fk | → job_listings.id |
| candidate_id | uuid fk | → candidate_profiles.id |
| source | enum | applied \| invited |
| status | enum | new \| interviewing \| shortlisted \| rejected \| hired |
| meta | jsonb | extra fields, e.g. referral, tags |
| created_at | timestamp | |
| updated_at | timestamp | |

> **Constraint:** Unique (job_id, candidate_id) — prevents duplicate applications.

## Live interview tables

### 8) interview_sessions
Anchor for WebRTC + WebSocket control + agent context.

| Field | Type | Notes |
|-------|------|-------|
| id | uuid pk | Primary key |
| application_id | uuid fk | → applications.id |
| round | int | default 1 |
| status | enum | created \| active \| ended \| cancelled \| failed |
| started_at | timestamp | |
| ended_at | timestamp | |
| agent_version | string | helps reproducibility |
| context_snapshot | jsonb | job summary + rubric + candidate info used at start |
| realtime | jsonb | room id, signaling info, etc. |
| created_at | timestamp | |
| updated_at | timestamp | |

### 9) interview_participants
Tracks who joined the session and reconnections.

| Field | Type | Notes |
|-------|------|-------|
| id | uuid pk | Primary key |
| session_id | uuid fk | → interview_sessions.id |
| user_id | uuid fk | → users.id, nullable (agent could be null or system user) |
| participant_type | enum | candidate \| recruiter \| agent \| system |
| joined_at | timestamp | |
| left_at | timestamp | |
| connection_meta | jsonb | device, browser, ip hash |
| created_at | timestamp | |
| updated_at | timestamp | |

### 10) interview_turns
Every "turn" in the conversation (candidate utterance, agent response, system notices).

| Field | Type | Notes |
|-------|------|-------|
| id | uuid pk | Primary key |
| session_id | uuid fk | → interview_sessions.id |
| seq | int | strict ordering per session |
| speaker | enum | candidate \| agent \| system |
| modality | enum | text \| audio \| video \| mixed |
| text | text | nullable |
| payload | jsonb | tool calls, interrupt markers, etc. |
| started_at | timestamp | for latency analysis |
| ended_at | timestamp | for latency analysis |
| created_at | timestamp | |

> **Constraint:** Unique (session_id, seq).

### 11) media_assets
Stores references to uploaded/recorded chunks or files (GCS paths later).

| Field | Type | Notes |
|-------|------|-------|
| id | uuid pk | Primary key |
| owner_type | enum | candidate \| org \| session |
| owner_id | uuid | |
| session_id | uuid fk | → interview_sessions.id, nullable |
| turn_id | uuid fk | → interview_turns.id, nullable |
| kind | enum | audio_chunk \| video_chunk \| recording \| image \| resume \| report |
| storage_provider | enum | local \| gcs |
| uri | text | path or gs:// later |
| content_type | string | |
| size_bytes | bigint | |
| checksum | text | nullable |
| created_at | timestamp | |

### 12) transcripts
Speech-to-text results, kept separate for re-running or improvements.

| Field | Type | Notes |
|-------|------|-------|
| id | uuid pk | Primary key |
| session_id | uuid fk | → interview_sessions.id |
| turn_id | uuid fk | → interview_turns.id, nullable |
| source_asset_id | uuid fk | → media_assets.id |
| engine | string | gemini, whisper, etc. |
| language | string | |
| text | text | |
| segments | jsonb | word timings, diarization, etc. |
| created_at | timestamp | |

## Evaluation & reporting

### 13) evaluations
Final scoring output for an interview session (or per round).

| Field | Type | Notes |
|-------|------|-------|
| id | uuid pk | Primary key |
| session_id | uuid fk | unique → interview_sessions.id |
| rubric_id | uuid fk | → rubrics.id, nullable (or snapshot only) |
| overall_score | numeric | |
| recommendation | enum | strong_yes \| yes \| maybe \| no \| strong_no |
| summary | text | |
| strengths | text[] | |
| concerns | text[] | |
| evidence | jsonb | citations to turns, timestamps, snippets |
| report_asset_id | uuid fk | → media_assets.id, nullable (pdf/html) |
| created_at | timestamp | |
| updated_at | timestamp | |

### 14) evaluation_scores
Per-criterion score rows.

| Field | Type | Notes |
|-------|------|-------|
| id | uuid pk | Primary key |
| evaluation_id | uuid fk | → evaluations.id |
| criterion_id | uuid fk | → rubric_criteria.id |
| score | numeric | |
| notes | text | |
| evidence | jsonb | |
| created_at | timestamp | |

> **Constraint:** Unique (evaluation_id, criterion_id).

## Observability / interruptions / debugging

### 15) session_events
Useful for interruptions and real-time reliability.

| Field | Type | Notes |
|-------|------|-------|
| id | uuid pk | Primary key |
| session_id | uuid fk | → interview_sessions.id |
| type | enum | ws_connected, ws_disconnected, rtc_connected, rtc_disconnected, interrupt_detected, barge_in, agent_tool_call, candidate_muted, candidate_unmuted, error |
| at | timestamp | |
| meta | jsonb | reason, latency, etc. |

## Minimal MVP cut (hackathon)

If shipping only "live interview" for the hackathon, minimum tables:

- orgs
- users
- job_listings
- candidate_profiles
- applications
- interview_sessions
- interview_turns
- session_events

Then add `media_assets`, `transcripts`, `evaluations` when ready.

## Recommended indexes

```sql
CREATE UNIQUE INDEX idx_users_email ON users(email);
CREATE INDEX idx_job_listings_org_status ON job_listings(org_id, status);
CREATE UNIQUE INDEX idx_applications_job_candidate ON applications(job_id, candidate_id);
CREATE INDEX idx_applications_status ON applications(status);
CREATE INDEX idx_interview_sessions_application ON interview_sessions(application_id);
CREATE INDEX idx_interview_sessions_status ON interview_sessions(status);
CREATE UNIQUE INDEX idx_interview_turns_session_seq ON interview_turns(session_id, seq);
CREATE INDEX idx_session_events_session_at ON session_events(session_id, at);
-- GIN indexes for JSONB fields (if queried frequently):
CREATE INDEX idx_job_listings_interview_config ON job_listings USING GIN(interview_config);
CREATE INDEX idx_media_assets_meta ON media_assets USING GIN(meta);
```

