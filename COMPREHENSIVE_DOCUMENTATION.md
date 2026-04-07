# TrueFit.AI - Comprehensive Project Documentation

## Table of Contents

1. [Project Overview](#project-overview)
2. [Technology Stack](#technology-stack)
3. [Architecture](#architecture)
4. [System Components](#system-components)
5. [Setup & Installation](#setup--installation)
6. [API Documentation](#api-documentation)
7. [Real-time Communication](#real-time-communication)
8. [Database Schema](#database-schema)
9. [Deployment](#deployment)
10. [Development Best Practices](#development-best-practices)

---

## Project Overview

**TrueFit.AI** is a comprehensive AI-powered recruitment platform designed to automate and enhance the interview process. The platform leverages advanced AI agents powered by Google's Gemini Live API to conduct real-time interviews with candidates while managing the full recruitment workflow.

### Key Features

- **AI-Powered Interviews**: Automated candidate interviews using Gemini Live API
- **Real-time WebRTC Communication**: Peer-to-peer video/audio with candidates
- **WebSocket Live Streaming**: Real-time event streaming and orchestration
- **Multi-user Collaboration**: Recruiters can observe and manage interviews
- **Candidate Management**: Full candidate profile and application tracking
- **Job Management**: Create and manage job listings with AI-powered interview configuration
- **Evaluation & Scoring**: AI-generated evaluations with rubric-based scoring
- **Report Generation**: Automated interview reports and candidate recommendations

### Core Use Cases

1. **Candidate Interview**: AI agent conducts interview, captures responses, generates evaluations
2. **Interview Observation**: Recruiters observe live interviews via WebRTC/WebSocket
3. **Application Management**: Track candidates through the recruitment pipeline
4. **Evaluation Review**: Review AI-generated evaluations and recommendations

---

## Technology Stack

### Backend

```
FastAPI (Web Framework)
├── Python 3.14
├── Async/Await (asyncio)
├── SQLAlchemy 2.0 (ORM)
├── Alembic (Database Migrations)
├── Pydantic (Data Validation)
└── Dependencies:
    ├── PostgreSQL + asyncpg (Primary DB, Supabase)
    ├── Redis (Cache & Queue)
    ├── Google Gemini Live API
    ├── aiortc (WebRTC)
    ├── python-asyncio (Async tasks)
    ├── python-jose (JWT)
    ├── Firebase Admin SDK
    ├── python-multipart (File uploads)
    └── pytest (Testing)
```

### Frontend

```
React 19 + TypeScript
├── Vite (Build Tool)
├── TailwindCSS (Styling)
├── React Router (Navigation)
├── Shadcn/ui (Component Library)
└── Dependencies:
    ├── Firebase SDK (Auth)
    ├── WebRTC (peer-connection, video/audio)
    ├── Axios (HTTP Client)
    ├── React Context API (State Management)
    ├── Zustand (optional state management)
    └── Vitest (Testing)
```

### Infrastructure & Services

```
Cloud Services:
├── Supabase PostgreSQL (Primary Database)
├── Redis Cloud (Cache & Message Queue)
├── Firebase (Authentication & Realtime DB)
├── Google Cloud (Gemini API, Storage)
└── GCS (Media Storage)

Development:
├── Docker (Containerization)
├── Git (Version Control)
├── GitHub Actions (CI/CD)
└── VS Code (IDE)
```

---

## Architecture

### High-Level System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend (React)                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │ Landing  │  │   Auth   │  │Dashboard │  │Interview │    │
│  │   Page   │  │   Page   │  │   Page   │  │   Page   │    │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘    │
│       ↓              ↓              ↓              ↓         │
│  ┌──────────────────────────────────────────────────────┐   │
│  │           HTTP REST API (Axios)                      │   │
│  │  Auth│Jobs│Candidates│Applications│Interviews│Users │   │
│  └──────────────────────────────────────────────────────┘   │
│       ↓              ↓                                      │
│  ┌──────────────┐  ┌──────────────┐                       │
│  │ Firebase Auth│  │  WebSocket   │                       │
│  │              │  │  WebRTC      │                       │
│  └──────────────┘  └──────────────┘                       │
└─────────────────────────────────────────────────────────────┘
         ↓                        ↓
┌─────────────────────────────────────────────────────────────┐
│                    Backend (FastAPI)                         │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              HTTP Routers (REST API)                 │   │
│  │ ┌────────────┐┌─────────┐┌──────────┐┌────────────┐│   │
│  │ │Auth Router││Jobs┌───┬─┐│Interview││Applications││   │
│  │ │            ││    │Cand││Routers  ││Routers     ││   │
│  │ │ - OAuth   ││    │idates│         │
│  │ │ - JWT     ││    └───┴─┘│         │             ││   │
│  │ │ - Refresh││           │         │             ││   │
│  │ └────────────┘└─────────┘└──────────┘└────────────┘│   │
│  └──────────────────────────────────────────────────────┘   │
│                          ↓                                  │
│  ┌──────────────────────────────────────────────────────┐   │
│  │         WebSocket Router (Real-time)                │   │
│  │  ┌──────────────────────────────────────────────┐   │   │
│  │  │ Interview WebSocket Handler                 │   │   │
│  │  │ - Connection Management                     │   │   │
│  │  │ - Event Broadcasting                        │   │   │
│  │  │ - WebRTC Signaling                          │   │   │
│  │  └──────────────────────────────────────────────┘   │   │
│  └──────────────────────────────────────────────────────┘   │
│                          ↓                                  │
│  ┌──────────────────────────────────────────────────────┐   │
│  │        Core Business Logic Layer                    │   │
│  │  ┌──────────────────────────────────────────────┐   │   │
│  │  │ Interview Orchestration Service             │   │   │
│  │  │ - Interview Flow Management                 │   │   │
│  │  │ - AI Agent Coordination                     │   │   │
│  │  │ - Event Publishing                          │   │   │
│  │  └──────────────────────────────────────────────┘   │   │
│  │  ┌──────────────────────────────────────────────┐   │   │
│  │  │ Job Service / Candidate Service             │   │   │
│  │  │ - Business Rules                            │   │   │
│  │  │ - Data Validation                           │   │   │
│  │  │ - Application Flow                          │   │   │
│  │  └──────────────────────────────────────────────┘   │   │
│  └──────────────────────────────────────────────────────┘   │
│                          ↓                                  │
│  ┌──────────────────────────────────────────────────────┐   │
│  │     Real-time & AI Integration Layer               │   │
│  │  ┌──────────────┐┌──────────────┐┌──────────────┐  │   │
│  │  │ WebRTC       ││ Gemini Live  ││  Live        │  │   │
│  │  │ Client       ││ Agent        ││  Interview   │  │   │
│  │  │              ││              ││  Agent       │  │   │
│  │  └──────────────┘└──────────────┘└──────────────┘  │   │
│  │  ┌──────────────┐┌──────────────┐                  │   │
│  │  │ Redis Queue  ││ Cache Layer  │                  │   │
│  │  │              ││              │                  │   │
│  │  └──────────────┘└──────────────┘                  │   │
│  └──────────────────────────────────────────────────────┘   │
│                          ↓                                  │
│  ┌──────────────────────────────────────────────────────┐   │
│  │         Data Persistence Layer                      │   │
│  │  ┌────────────────────────────────────────────────┐ │   │
│  │  │ SQLAlchemy Repositories                       │ │   │
│  │  │ - UserRepository                             │ │   │
│  │  │ - JobListingRepository                       │ │   │
│  │  │ - CandidateRepository                        │ │   │
│  │  │ - ApplicationRepository                      │ │   │
│  │  │ - InterviewSessionRepository                 │ │   │
│  │  │ - EvaluationRepository                       │ │   │
│  │  └────────────────────────────────────────────────┘ │   │
│  └──────────────────────────────────────────────────────┘   │
│                          ↓                                  │
│  ┌──────────────────────────────────────────────────────┐   │
│  │           External Services                         │   │
│  │  ┌──────────────┐┌──────────────┐┌──────────────┐   │   │
│  │  │ PostgreSQL   ││ Redis        ││ Firebase     │   │   │
│  │  │ (Supabase)   ││ (Cloud)      ││              │   │   │
│  │  └──────────────┘└──────────────┘└──────────────┘   │   │
│  │  ┌──────────────┐┌──────────────┐                   │   │
│  │  │ Google       ││ Google Cloud │                   │   │
│  │  │ Gemini API   ││ Storage      │                   │   │
│  │  └──────────────┘└──────────────┘                   │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Layered Architecture

```
┌─────────────────────────────────┐
│   Presentation Layer            │
│  (FastAPI Routes, WebSocket)    │
└──────────────┬──────────────────┘
               │
┌──────────────┴──────────────────┐
│   Application Layer             │
│  (Services, Orchestration)      │
└──────────────┬──────────────────┘
               │
┌──────────────┴──────────────────┐
│   Domain Layer                  │
│  (Business Logic, Entities)     │
└──────────────┬──────────────────┘
               │
┌──────────────┴──────────────────┐
│   Infrastructure Layer          │
│  (DB, Cache, External APIs)     │
└─────────────────────────────────┘
```

### Directory Structure

```
backend/
├── src/
│   ├── truefit_api/              # REST API & WebSocket routers
│   │   ├── main.py              # FastAPI app entry point
│   │   ├── middlewares.py        # Error, logging, timing middleware
│   │   ├── dependencies.py       # Dependency injection
│   │   └── api/v1/
│   │       ├── http/            # REST API endpoints
│   │       │   ├── auth.py
│   │       │   ├── jobs.py
│   │       │   ├── candidates.py
│   │       │   ├── interviews.py
│   │       │   ├── applications.py
│   │       │   ├── users.py
│   │       │   ├── orgs.py
│   │       │   └── health.py
│   │       ├── ws/              # WebSocket handlers
│   │       │   └── interview_websocket.py
│   │       └── schemas/         # Pydantic request/response models
│   │
│   ├── truefit_core/            # Business logic & domain
│   │   ├── domain/              # Domain entities
│   │   │   ├── user.py
│   │   │   ├── org.py
│   │   │   ├── job.py
│   │   │   ├── candidate.py
│   │   │   ├── interview.py
│   │   │   ├── evaluation.py
│   │   │   └── application.py
│   │   ├── application/
│   │   │   ├── services/        # Business services
│   │   │   │   ├── user_service.py
│   │   │   │   ├── job_service.py
│   │   │   │   ├── candidate_service.py
│   │   │   │   ├── interview_orchestration.py
│   │   │   │   └── evaluation_service.py
│   │   │   ├── ports/           # Abstract interfaces
│   │   │   ├── commands/        # Commands
│   │   │   └── query/          # Queries
│   │   ├── agents/              # AI agent implementations
│   │   │   └── interviewer/    # Interview agent
│   │   └── common/
│   │       └── utils.py        # Logging, helpers
│   │
│   └── truefit_infra/          # Infrastructure & external services
│       ├── config.py           # Configuration
│       ├── container.py        # DI container
│       ├── auth/               # Authentication
│       │   ├── jwt.py
│       │   ├── middleware.py
│       │   └── oauth.py
│       ├── db/                 # Database
│       │   ├── database.py    # AsyncEngine, SessionFactory
│       │   ├── models.py      # SQLAlchemy models
│       │   └── repositories/  # Data access layer
│       ├── cache/              # Redis cache
│       │   └── redis_cache.py
│       ├── queue/              # Message queue
│       │   └── redis_queue.py
│       ├── realtime/           # WebRTC & real-time
│       │   ├── webrtc_client.py
│       │   ├── signaling.py
│       │   ├── data_channel.py
│       │   ├── audio_bridge.py
│       │   └── session_context.py
│       ├── llm/                # LLM integrations
│       │   └── gemini_live.py
│       ├── agent/
│       │   └── live_interview_agent.py
│       └── storage/            # File storage
│
└── tests/
    ├── unit/
    ├── integration/
    └── e2e/

frontend/
├── src/
│   ├── App.tsx                 # Main app component
│   ├── main.tsx               # Entry point
│   ├── vite-env.d.ts         # Vite environment types
│   ├── pages/                 # Route pages
│   │   ├── Landing.tsx
│   │   ├── Auth.tsx
│   │   ├── Dashboard.tsx
│   │   ├── InterviewPage.tsx
│   │   ├── ItvPage.tsx
│   │   ├── Jobs.tsx
│   │   ├── Candidates.tsx
│   │   ├── Applications.tsx
│   │   └── ...
│   ├── components/
│   │   ├── ProtectedRoute.tsx
│   │   ├── ProtectedLayout.tsx
│   │   ├── Header.tsx
│   │   ├── AppSidebar.tsx
│   │   ├── InterviewRoom.tsx   # WebRTC video room
│   │   ├── ItvRoom.tsx         # Interview interface
│   │   ├── CustomTrigger.tsx
│   │   └── ui/                # shadcn/ui components
│   ├── hooks/
│   │   ├── useAuth.tsx
│   │   ├── useAuthContext.tsx
│   │   └── use-mobile.ts
│   ├── context/
│   │   └── authContext.tsx    # Auth state
│   ├── helpers/
│   │   ├── api.ts             # Axios instance
│   │   ├── api.interceptors.ts # HTTP interceptors
│   │   ├── firebase.ts        # Firebase config
│   │   ├── utils.ts           # Utilities
│   │   ├── api/               # API services
│   │   └── validations/       # Form validations
│   ├── assets/                # Images, fonts
│   ├── index.css
│   ├── App.css
│   └── config.ts              # Frontend config
└── public/
```

---

## System Components

### 1. Authentication System

#### Flow: OAuth Login → JWT Token

```
Frontend                          Backend
   │                                │
   ├─ OAuth Login (Firebase) ──────→│
   │                                │
   │                         Verify Token
   │                                │
   │←─ User Data + JWT Token ────────│
   │                                │
   ├─ Store JWT (localStorage) ──────│
   │                                │
   ├─ Add JWT to Headers ───────────→│
   │  (All Requests)                │
   │                                 │Check JWT
   │                                 │Verify Signature
   │←─ Response ──────────────────────│
```

**Key Files:**
- Backend: `src/truefit_infra/auth/jwt.py`, `middleware.py`
- Frontend: `src/context/authContext.tsx`, `src/helpers/api.interceptors.ts`

### 2. Interview Session Flow

```
┌─────────────────────────────────────────────────────────────┐
│ Interview Flow Sequence                                     │
└─────────────────────────────────────────────────────────────┘

1. Application Created
   ├─ Job Posted
   ├─ Candidate Applies
   └─ Application created in DB

2. Interview Session Initiated
   ├─ Recruiter starts interview
   ├─ WebSocket connection established
   ├─ Interview session record created
   └─ AI Agent initialized

3. WebRTC Peer Connection Setup
   ├─ Offer/Answer Exchange via WebSocket
   ├─ ICE Candidates collected
   ├─ Peer connection established
   └─ Media streams active

4. Interview Execution
   ├─ AI Agent generates questions
   ├─ Candidate audio/video captured
   ├─ Real-time transcription
   ├─ Agent responses generated
   └─ Data logged in real-time

5. Interview Termination
   ├─ Close WebRTC connection
   ├─ Stop streams
   ├─ Terminate WebSocket
   └─ Process evaluation

6. Evaluation & Reporting
   ├─ AI generates evaluation
   ├─ Scoring based on rubric
   ├─ Report generated
   └─ Stored in database
```

### 3. WebRTC Architecture

```
┌──────────────────┐                    ┌──────────────────┐
│  Frontend Client │                    │  Backend Server  │
│  (Candidate)     │                    │  (AI Agent)      │
└────────┬─────────┘                    └────────┬─────────┘
         │                                       │
    LocalStream              WebSocket          │
    ┌────────────┐  Signaling Messages   ┌──────┴──────┐
    │ Audio      │  ◄──────────────────► │ WebRTC      │
    │ Video      │  (Offer/Answer/ICE)   │ Signaling   │
    │ Devices    │                       │ Handler     │
    └────────────┘                       └──────┬──────┘
         │                                       │
         │◄──────── DTLS/SRTP Encrypted ───────►│
         │            Media Stream               │
         │                                       │
    WebRTCPeerConnection              WebRTCPeerConnection
    └────────────────────────────────────────────┘
```

**Key Components:**
- `WebRTCClient`: Manages peer connection, local/remote streams
- `WebRTCSignaling`: Handles offer/answer/ICE candidate exchange
- `GeminiLiveAdapter`: Processes audio stream with AI
- Interview WebSocket: Orchestrates signaling messages

### 4. Real-time Data Flow (Interview Session)

```
Candidate Browser              WebSocket              Backend
        │                          │                      │
        ├─ Audio chunks ──────────→├─ Broadcast ────────→ AI Agent
        │                          │                      │
        │                          │                      ├─ Process
        │                          │                      ├─ Generate
        │                          │                      │  Response
        │                          │                      │
        │←─ Audio Response ────────┤←─ Emit ─────────────┤
        │                          │                      │
        │←─ Transcript ────────────┤←─ Broadcast ────────┤
        │                          │                      │
        │←─ Session Status ────────┤←─ Emit ─────────────┤
        │                          │                      │
```

### 5. Evaluation Pipeline

```
Interview Data
    ↓
AI Analysis
├─ Response quality
├─ Problem solving
├─ Communication skills
└─ Technical knowledge
    ↓
Rubric Scoring
├─ Score each criterion
├─ Calculate weights
└─ Generate recommendation
    ↓
Report Generation
├─ Summary
├─ Strengths
├─ Concerns
└─ Evidence
    ↓
Database Storage
├─ Evaluation record
├─ Scores
└─ Assets
```

---

## System Components (Detailed)

### Authentication (truefit_infra/auth/)

**JWT Service** (`jwt.py`):
- Token generation with exp, iss, sub claims
- Token verification and decoding
- Refresh token handling

**Middleware** (`middleware.py`):
- Extract JWT from Authorization header
- Validate token signature
- Inject current user into request context

**OAuth Service** (`oauth.py`):
- Firebase OAuth integration
- Social provider handling
- Token exchange

### Database (truefit_infra/db/)

**Models** (`models.py`):
```python
class User(Base)
class Org(Base)
class JobListing(Base)
class CandidateProfile(Base)
class Application(Base)
class InterviewSession(Base)
class InterviewTurn(Base)
class Evaluation(Base)
class EvaluationScore(Base)
class MediaAsset(Base)
class Transcript(Base)
class SessionEvent(Base)
```

**Repositories**:
- SQLAlchemyUserRepository
- SQLAlchemyJobRepository
- SQLAlchemyCandidateRepository
- SQLAlchemyApplicationRepository
- SQLAlchemyInterviewRepository
- SQLAlchemyEvaluationRepository

### Real-time (truefit_infra/realtime/)

**WebRTCClient** (`webrtc_client.py`):
- Peer connection management
- Local/remote stream handling
- DataChannel communication

**WebRTCSignaling** (`signaling.py`):
- Offer/Answer generation
- ICE candidate handling
- Connection state tracking

**GeminiLiveAdapter** (`llm/gemini_live.py`):
- Google Gemini Live API integration
- Audio stream processing
- Response generation

### Interview Orchestration (truefit_core/application/)

**InterviewOrchestrationService**:
- Coordinates interview flow
- Manages participant connections
- Publishes domain events
- Handles interrupts/timeouts

**LiveInterviewAgent**:
- AI agent for interview execution
- Turn-taking logic
- Context awareness
- Tool calling (if configured)

---

## API Documentation

### Authentication Endpoints

```
POST /api/v1/auth/login
- OAuth login endpoint
- Request: {provider, token}
- Response: {access_token, user}

POST /api/v1/auth/refresh
- Refresh JWT token
- Response: {access_token}

GET /api/v1/auth/me
- Get current user
- Response: User object
```

### Job Endpoints

```
POST /api/v1/jobs
- Create job listing
- Request: JobCreate {title, description, skills, experience_level}
- Response: JobListing

GET /api/v1/jobs
- List jobs for org
- Query: ?page=0&size=10&status=open
- Response: {items: JobListing[], total: int}

GET /api/v1/jobs/{job_id}
- Get job details
- Response: JobListing

PUT /api/v1/jobs/{job_id}
- Update job
- Response: JobListing

DELETE /api/v1/jobs/{job_id}
- Delete job
- Response: {deleted: true}
```

### Candidate Endpoints

```
POST /api/v1/candidates
- Create candidate profile
- Request: CandidateCreate
- Response: CandidateProfile

GET /api/v1/candidates
- List candidates
- Response: {items: CandidateProfile[], total: int}

GET /api/v1/candidates/{candidate_id}
- Get candidate details
- Response: CandidateProfile
```

### Interview Endpoints

```
POST /api/v1/interviews
- Start interview session
- Request: {application_id, job_id, candidate_id}
- Response: InterviewSession

GET /api/v1/interviews/{session_id}
- Get interview session
- Response: InterviewSession with details

GET /api/v1/interviews/{session_id}/turns
- Get interview turns/transcript
- Response: [InterviewTurn]

GET /api/v1/interviews/{session_id}/evaluation
- Get interview evaluation
- Response: Evaluation
```

### WebSocket Events

```
ws: /ws/interview/{session_id}

Client → Server Events:
- "join": {user_id, participant_type}
- "webrtc_offer": {data}
- "webrtc_answer": {data}
- "webrtc_ice_candidate": {data}
- "participant_muted": {muted}
- "request_interrupt": {}

Server → Client Events:
- "participant_joined": {participant}
- "webrtc_offer": {from_user, data}
- "webrtc_answer": {from_user, data}
- "webrtc_ice_candidate": {candidate}
- "transcript": {text, speaker}
- "agent_response": {text}
- "interview_status": {status}
- "evaluation_ready": {evaluation}
```

---

## Real-time Communication

### WebSocket Protocol

**Connection**:
```python
ws = new WebSocket('ws://localhost:8000/ws/interview/{session_id}')
```

**Message Format**:
```json
{
  "event": "join",
  "data": {
    "user_id": "uuid",
    "participant_type": "recruiter|candidate|agent"
  }
}
```

### WebRTC Signaling Flow

```
1. Client generates offer
   ├─ RTCPeerConnection.createOffer()
   └─ Send via WebSocket

2. Server receives offer
   ├─ Create peer connection
   ├─ Set remote description
   └─ Generate answer

3. Server sends answer
   └─ Send via WebSocket

4. Client receives answer
   └─ Set remote description

5. ICE Candidates Exchange
   ├─ Client collects ICE candidates
   ├─ Send via WebSocket
   ├─ Server receives and adds
   └─ Bidirectional
```

### Media Stream Processing

```
Candidate Audio
        ↓
    WebRTC
        ↓
    aiortc
        ↓
    Buffer (PCM)
        ↓
    Gemini Live API
        ↓
    AI Response
        ↓
    Audio Output
        ↓
    Candidate Hears Response
```

---

## Database Schema

### Core Tables

```sql
users
├── id (PK, UUID)
├── email (UK)
├── role (admin|recruiter|candidate)
├── fire base_id
└── created_at

orgs
├── id (PK, UUID)
├── created_by (FK users)
├── name
├── slug (UK)
├── contact (JSONB)
├── billing (JSONB)
└── created_at

job_listings
├── id (PK, UUID)
├── org_id (FK orgs)
├── created_by (FK users)
├── title
├── description
├── skills (JSONB array)
├── requirements (JSONB)
├── interview_config (JSONB)
├── status (draft|open|closed)
└── created_at

candidate_profiles
├── id (PK, UUID)
├── user_id (FK users)
├── first_name
├── last_name
├── email
├── phone
├── resume_url
├── skills (JSONB array)
├── experience_years
└── created_at

applications
├── id (PK, UUID)
├── job_id (FK job_listings)
├── candidate_id (FK candidate_profiles)
├── status (new|interviewing|shortlisted|rejected|hired)
├── source (applied|invited)
├── meta (JSONB)
└── created_at

interview_sessions
├── id (PK, UUID)
├── application_id (FK applications)
├── status (created|active|ended|cancelled)
├── round (int)
├── started_at
├── ended_at
├── context_snapshot (JSONB)
├── realtime (JSONB)
└── created_at

interview_turns
├── id (PK, UUID)
├── session_id (FK interview_sessions)
├── seq (int)
├── speaker (candidate|agent|system)
├── turn_text
├── payload (JSONB)
├── modality (text|audio|video|mixed)
└── created_at

evaluations
├── id (PK, UUID)
├── session_id (FK interview_sessions)
├── overall_score (float)
├── recommendation (strong_yes|yes|maybe|no|strong_no)
├── summary (text)
├── strengths (array)
├── concerns (array)
├── evidence (JSONB)
└── created_at

evaluation_scores
├── id (PK, UUID)
├── evaluation_id (FK evaluations)
├── criterion_id (FK rubric_criteria)
├── score (float)
├── notes
├── evidence (JSONB)
└── created_at

media_assets
├── id (PK, UUID)
├── owner_id
├── owner_type (candidate|org|session)
├── session_id (FK interview_sessions)
├── kind (audio|video|resume|report)
├── uri
├── storage_provider (local|gcs)
└── created_at

transcripts
├── id (PK, UUID)
├── session_id (FK interview_sessions)
├── turn_id (FK interview_turns)
├── engine (speech-to-text service)
├── transcript_text
├── segments (JSONB)
└── created_at

session_events
├── id (PK, UUID)
├── session_id (FK interview_sessions)
├── type (ws_connected|rtc_connected|interrupt|error)
├── at (datetime)
├── meta (JSONB)
└── created_at
```

---

## Setup & Installation

See [SETUP_GUIDE.md](./SETUP_GUIDE.md) for detailed setup instructions.

### Quick Start

**Backend**:
```bash
cd apps/backend
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
python run.py
```

**Frontend**:
```bash
cd apps/frontend
npm install
npm run dev
```

---

## Deployment

### Docker Deployment

```dockerfile
# Backend Dockerfile
FROM python:3.14
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "run.py"]
```

### Kubernetes Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: truefit-backend
spec:
  replicas: 3
  selector:
    matchLabels:
      app: truefit-backend
  template:
    metadata:
      labels:
        app: truefit-backend
    spec:
      containers:
      - name: truefit-api
        image: truefit:backend-latest
        ports:
        - containerPort: 8000
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: db-secret
              key: url
        - name: REDIS_URL
          valueFrom:
            configMapKeyRef:
              name: redis-config
              key: url
```

### CI/CD Pipeline

**GitHub Actions** (`.github/workflows/`):
1. Test Backend (pytest)
2. Test Frontend (vitest)
3. Build Docker images
4. Push to registry
5. Deploy to staging/production

---

## Development Best Practices

### Backend Code Style

```python
# Use type hints
def create_job(job_data: JobCreate, current_user: User) -> JobListing:
    pass

# Use async/await
async def get_interview_session(session_id: UUID) -> InterviewSession:
    async with db_manager.get_session() as session:
        return await session.get(InterviewSession, session_id)

# Use Pydantic for validation
class JobCreate(BaseModel):
    title: str = Field(min_length=5)
    description: str = Field(min_length=20)
    skills: List[str]

# Logging
logger.info("Interview started", extra={"session_id": session_id})
```

### Frontend Code Style

```typescript
// Use functional components
const InterviewPage: React.FC = () => {
  const [state, setState] = useState();
  return <div>Interview</div>;
};

// Use hooks for logic
const useInterview = (sessionId: string) => {
  const [session, setSession] = useState(null);
  useEffect(() => {
    fetchSession(sessionId).then(setSession);
  }, [sessionId]);
  return { session };
};

// Type everything
interface InterviewSession {
  id: string;
  status: "active" | "ended";
  evaluations: Evaluation[];
}
```

### Testing

**Backend**:
```python
@pytest.mark.asyncio
async def test_create_job(db_session):
    job = await job_service.create_job(JobCreate(...), user)
    assert job.id is not None
    assert job.status == "draft"
```

**Frontend**:
```typescript
describe("InterviewPage", () => {
  it("should render interview session", () => {
    render(<InterviewPage sessionId="123" />);
    expect(screen.getByText(/Interview/i)).toBeInTheDocument();
  });
});
```

---

## Troubleshooting

### Common Issues

**Backend Won't Start**:
1. Check `.env` DATABASE_URL
2. Verify Redis connection
3. Check firewall for ports 8000, 6379

**WebRTC Connection Fails**:
1. Check ICE candidates
2. Verify STUN/TURN servers
3. Check browser console for errors

**WebSocket Disconnects**:
1. Check network connectivity
2. Verify WebSocket URL
3. Check server logs for errors

---

## Additional Resources

- [API Documentation](./OAUTH_INTEGRATION_GUIDE.md)
- [Setup Guide](./SETUP_GUIDE.md)
- [Quick Reference](./QUICK_REFERENCE.md)
- [Test Report](./TEST_REPORT.md)

---

**Last Updated**: March 16, 2026
**Version**: 1.0
**Maintainers**: TrueFit.AI Development Team
