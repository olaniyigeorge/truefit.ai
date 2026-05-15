# TrueFit.AI - API Reference & Developer Guide

## Table of Contents

1. [API Overview](#api-overview)
2. [Authentication](#authentication)
3. [REST Endpoints](#rest-endpoints)
4. [WebSocket Events](#websocket-events)
5. [Error Responses](#error-responses)
6. [Data Models](#data-models)
7. [Development Workflow](#development-workflow)
8. [Code Examples](#code-examples)

---

## API Overview

### Base URL

```
Development:  http://localhost:8000
Production:   https://api.truefit.ai
API Version:  v1
```

### API Structure

```
/api/v1/
├── /auth                 # Authentication endpoints
├── /users               # User management
├── /orgs                # Organization management
├── /jobs                # Job listings
├── /candidates          # Candidate profiles
├── /applications        # Job applications
├── /interviews          # Interview sessions
├── /evaluations         # Interview evaluations
├── /health              # Health check
└── /ws/interview/{id}   # WebSocket endpoint
```

---

## Authentication

### JWT Token Flow

```
1. User logs in → Firebase OAuth
2. Firebase returns ID token
3. Frontend sends token to backend
4. Backend verifies and issues JWT
5. Frontend stores JWT in localStorage
6. All requests include Authorization header
```

### Login Endpoint

**POST** `/api/v1/auth/login`

```typescript
// Request
{
  "provider": "firebase",
  "id_token": "eyJhbGciOiJSUzI1NiIsImtpZCI6IjE..."
}

// Response
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 1800,
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "john@example.com",
    "role": "recruiter",
    "name": "John Doe"
  }
}

// Error
{
  "detail": "Invalid token"
}
```

### Refresh Token

**POST** `/api/v1/auth/refresh`

```typescript
// Request
{ }

// Response
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "expires_in": 1800
}
```

### Get Current User

**GET** `/api/v1/auth/me`

```typescript
// Headers
Authorization: Bearer {access_token}

// Response
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "john@example.com",
  "role": "recruiter",
  "name": "John Doe",
  "org_id": "660e8400-e29b-41d4-a716-446655440000",
  "created_at": "2024-01-15T10:30:00Z"
}
```

### Common Headers

```
Authorization: Bearer {jwt_token}
Content-Type: application/json
X-Request-ID: {unique_request_id}  # Optional, for tracing
```

---

## REST Endpoints

### Users

#### List Users in Organization

**GET** `/api/v1/users`

```typescript
// Query Parameters
?page=0&size=10&role=recruiter

// Response
{
  "items": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "email": "recruiter1@company.com",
      "role": "recruiter",
      "name": "Alice Smith",
      "created_at": "2024-01-10T08:00:00Z"
    }
  ],
  "total": 25,
  "page": 0,
  "size": 10
}
```

#### Create User

**POST** `/api/v1/users`

```typescript
// Request
{
  "email": "newuser@company.com",
  "name": "Bob Johnson",
  "role": "recruiter"
}

// Response (201 Created)
{
  "id": "770e8400-e29b-41d4-a716-446655440000",
  "email": "newuser@company.com",
  "name": "Bob Johnson",
  "role": "recruiter",
  "created_at": "2024-03-16T14:30:00Z"
}
```

### Organizations

#### Create Organization

**POST** `/api/v1/orgs`

```typescript
// Request
{
  "name": "TechCorp Inc",
  "slug": "techcorp",
  "industry": "Software",
  "headcount": "100-500",
  "contact": {
    "website": "https://techcorp.com",
    "phone": "+1-555-0123"
  }
}

// Response
{
  "id": "660e8400-e29b-41d4-a716-446655440000",
  "name": "TechCorp Inc",
  "slug": "techcorp",
  "status": "active",
  "created_at": "2024-03-16T14:35:00Z"
}
```

#### Get Organization

**GET** `/api/v1/orgs/{org_id}`

```typescript
// Response
{
  "id": "660e8400-e29b-41d4-a716-446655440000",
  "name": "TechCorp Inc",
  "slug": "techcorp",
  "contact": {...},
  "members_count": 5,
  "created_at": "2024-03-16T14:35:00Z"
}
```

### Jobs

#### Create Job

**POST** `/api/v1/jobs`

```typescript
// Request
{
  "title": "Senior Python Engineer",
  "description": "Looking for experienced Python developer...",
  "experience_level": "senior",
  "skills": [
    {"name": "Python", "required": true, "weight": 1.0, "min_years": 3},
    {"name": "FastAPI", "required": true, "weight": 0.8, "min_years": 2},
    {"name": "PostgreSQL", "required": false, "weight": 0.6, "min_years": 2}
  ],
  "requirements": {
    "location": "Remote",
    "min_salary": 120000,
    "max_salary": 180000,
    "equity": "0.1-0.2%"
  },
  "interview_config": {
    "rounds": 2,
    "round_type": "ai_interview",
    "duration_minutes": 45,
    "questions_count": 5
  }
}

// Response (201 Created)
{
  "id": "880e8400-e29b-41d4-a716-446655440000",
  "org_id": "660e8400-e29b-41d4-a716-446655440000",
  "title": "Senior Python Engineer",
  "status": "draft",
  "created_by": "550e8400-e29b-41d4-a716-446655440000",
  "created_at": "2024-03-16T14:40:00Z"
}
```

#### List Jobs

**GET** `/api/v1/jobs`

```typescript
// Query Parameters
?page=0&size=20&status=open&org_id=660e8400-e29b-41d4-a716-446655440000

// Response
{
  "items": [...],
  "total": 45,
  "page": 0,
  "size": 20
}
```

#### Update Job

**PUT** `/api/v1/jobs/{job_id}`

```typescript
// Request (partial update)
{
  "status": "open",
  "interview_config": {
    "rounds": 3
  }
}

// Response
{
  "id": "880e8400-e29b-41d4-a716-446655440000",
  "title": "Senior Python Engineer",
  "status": "open",
  ...
}
```

#### Delete Job

**DELETE** `/api/v1/jobs/{job_id}`

```typescript
// Response (204 No Content)
```

### Candidates

#### Create Candidate Profile

**POST** `/api/v1/candidates`

```typescript
// Request
{
  "first_name": "Jane",
  "last_name": "Doe",
  "email": "jane@example.com",
  "phone": "+1-555-0456",
  "resume_url": "https://storage.example.com/resume.pdf",
  "skills": ["Python", "JavaScript", "React"],
  "experience_years": 5
}

// Response
{
  "id": "990e8400-e29b-41d4-a716-446655440000",
  "user_id": "550e8400-e29b-41d4-a716-446655440001",
  "first_name": "Jane",
  "last_name": "Doe",
  "created_at": "2024-03-16T14:45:00Z"
}
```

#### List Candidates

**GET** `/api/v1/candidates`

```typescript
// Query Parameters
?page=0&size=20&search=python

// Response
{
  "items": [...],
  "total": 156,
  "page": 0,
  "size": 20
}
```

### Applications

#### Create Application

**POST** `/api/v1/applications`

```typescript
// Request
{
  "job_id": "880e8400-e29b-41d4-a716-446655440000",
  "candidate_id": "990e8400-e29b-41d4-a716-446655440000",
  "source": "applied"  // or "invited"
}

// Response
{
  "id": "aa0e8400-e29b-41d4-a716-446655440000",
  "job_id": "880e8400-e29b-41d4-a716-446655440000",
  "candidate_id": "990e8400-e29b-41d4-a716-446655440000",
  "status": "new",
  "created_at": "2024-03-16T14:50:00Z"
}
```

#### List Applications

**GET** `/api/v1/applications`

```typescript
// Query Parameters
?page=0&size=20&job_id=880e8400&status=interviewing

// Response
{
  "items": [...],
  "total": 89,
  "page": 0,
  "size": 20
}
```

#### Update Application Status

**PUT** `/api/v1/applications/{application_id}`

```typescript
// Request
{
  "status": "interviewing"
}

// Response
{
  "id": "aa0e8400-e29b-41d4-a716-446655440000",
  "status": "interviewing",
  ...
}
```

### Interviews

#### Start Interview Session

**POST** `/api/v1/interviews`

```typescript
// Request
{
  "application_id": "aa0e8400-e29b-41d4-a716-446655440000",
  "job_id": "880e8400-e29b-41d4-a716-446655440000",
  "candidate_id": "990e8400-e29b-41d4-a716-446655440000",
  "round": 1
}

// Response
{
  "id": "bb0e8400-e29b-41d4-a716-446655440000",
  "application_id": "aa0e8400-e29b-41d4-a716-446655440000",
  "status": "created",
  "round": 1,
  "created_at": "2024-03-16T14:55:00Z"
}
```

#### Get Interview Session

**GET** `/api/v1/interviews/{session_id}`

```typescript
// Response
{
  "id": "bb0e8400-e29b-41d4-a716-446655440000",
  "application_id": "aa0e8400-e29b-41d4-a716-446655440000",
  "status": "active",
  "started_at": "2024-03-16T14:55:30Z",
  "participants": [
    {
      "id": "cc0e8400-e29b-41d4-a716-446655440000",
      "participant_type": "candidate",
      "joined_at": "2024-03-16T14:55:35Z"
    },
    {
      "id": "dd0e8400-e29b-41d4-a716-446655440000",
      "participant_type": "recruiter",
      "joined_at": "2024-03-16T14:55:40Z"
    }
  ]
}
```

#### Get Interview Transcript

**GET** `/api/v1/interviews/{session_id}/turns`

```typescript
// Query Parameters
?page=0&size=50

// Response
{
  "items": [
    {
      "seq": 1,
      "speaker": "agent",
      "turn_text": "Hello! Thank you for joining the interview...",
      "modality": "text",
      "started_at": "2024-03-16T14:55:40Z"
    },
    {
      "seq": 2,
      "speaker": "candidate",
      "turn_text": "Hi! Thanks for having me.",
      "modality": "text",
      "started_at": "2024-03-16T14:56:00Z"
    }
  ],
  "total": 24
}
```

#### Get Evaluation

**GET** `/api/v1/interviews/{session_id}/evaluation`

```typescript
// Response
{
  "id": "ee0e8400-e29b-41d4-a716-446655440000",
  "session_id": "bb0e8400-e29b-41d4-a716-446655440000",
  "overall_score": 8.2,
  "recommendation": "yes",
  "summary": "Strong technical knowledge with good communication skills...",
  "strengths": [
    "Excellent problem-solving approach",
    "Clear explanation of solutions",
    "Good follow-up questions"
  ],
  "concerns": [
    "Slightly nervous at the start",
    "Could improve on edge cases"
  ],
  "scores": [
    {
      "criterion": "technical_knowledge",
      "score": 9,
      "weight": 1.0
    },
    {
      "criterion": "communication",
      "score": 8,
      "weight": 0.8
    },
    {
      "criterion": "problem_solving",
      "score": 8.5,
      "weight": 1.0
    }
  ],
  "created_at": "2024-03-16T15:20:00Z"
}
```

### Health Check

**GET** `/api/v1/health`

```typescript
// Response
{
  "status": "healthy",
  "database": "connected",
  "redis": "connected",
  "timestamp": "2024-03-16T15:00:00Z"
}
```

---

## WebSocket Events

### Client → Server Events

#### Join Session

```json
{
  "event": "join",
  "data": {
    "user_id": "550e8400-e29b-41d4-a716-446655440000",
    "participant_type": "recruiter"
  }
}
```

#### WebRTC Offer

```json
{
  "event": "webrtc_offer",
  "data": {
    "type": "offer",
    "sdp": "v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\ns=-\r\n..."
  }
}
```

#### WebRTC Answer

```json
{
  "event": "webrtc_answer",
  "data": {
    "type": "answer",
    "sdp": "v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\ns=-\r\n..."
  }
}
```

#### ICE Candidate

```json
{
  "event": "webrtc_ice_candidate",
  "data": {
    "candidate": "candidate:842163049 1 udp 1686052607 192.168.1.100 54321 typ srflx raddr 192.168.1.100 rport 54321 generation 0 ufrag L+N9 network-cost 999",
    "sdpMLineIndex": 0,
    "sdpMid": "0"
  }
}
```

#### Participant Muted

```json
{
  "event": "participant_muted",
  "data": {
    "muted": true,
    "audio": true,
    "video": false
  }
}
```

#### Request Interrupt

```json
{
  "event": "request_interrupt",
  "data": {
    "reason": "candidate_needs_clarification"
  }
}
```

### Server → Client Events

#### Participant Joined

```json
{
  "event": "participant_joined",
  "data": {
    "participant_id": "550e8400-e29b-41d4-a716-446655440000",
    "participant_type": "recruiter",
    "joined_at": "2024-03-16T14:55:40Z"
  }
}
```

#### Participant Left

```json
{
  "event": "participant_left",
  "data": {
    "participant_id": "550e8400-e29b-41d4-a716-446655440000"
  }
}
```

#### Interview Status

```json
{
  "event": "interview_status",
  "data": {
    "status": "active",
    "round": 1,
    "elapsed_seconds": 125
  }
}
```

#### Transcript

```json
{
  "event": "transcript",
  "data": {
    "text": "What is your experience with database design?",
    "speaker": "agent",
    "language": "en",
    "confidence": 0.98,
    "timestamp": 1710662400000
  }
}
```

#### Agent Response

```json
{
  "event": "agent_response",
  "data": {
    "text": "Thank you for that answer...",
    "thinking": "The candidate showed good understanding of normalization...",
    "timestamp": 1710662410000
  }
}
```

#### Evaluation Ready

```json
{
  "event": "evaluation_ready",
  "data": {
    "evaluation_id": "ee0e8400-e29b-41d4-a716-446655440000",
    "overall_score": 8.2,
    "recommendation": "yes"
  }
}
```

#### Error

```json
{
  "event": "error",
  "data": {
    "code": 1000,
    "message": "Internal server error",
    "details": "Failed to process audio stream"
  }
}
```

---

## Error Responses

### Error Format

```json
{
  "detail": "Error message or list of validation errors",
  "status_code": 400
}
```

### Common Status Codes

| Code | Description |
|------|-------------|
| 200 | OK |
| 201 | Created |
| 204 | No Content |
| 400 | Bad Request (Validation error) |
| 401 | Unauthorized (Missing/invalid token) |
| 403 | Forbidden (No permission) |
| 404 | Not Found |
| 409 | Conflict (Duplicate, state error) |
| 422 | Unprocessable Entity (Invalid data) |
| 429 | Too Many Requests |
| 500 | Internal Server Error |
| 503 | Service Unavailable |

### Validation Error Example

```json
{
  "detail": [
    {
      "loc": ["body", "title"],
      "msg": "field required",
      "type": "value_error.missing"
    },
    {
      "loc": ["body", "experience_level"],
      "msg": "value is not a valid enumeration member; permitted: 'junior', 'mid', 'senior'",
      "type": "type_error.enum"
    }
  ]
}
```

---

## Data Models

### User

```typescript
interface User {
  id: string;                    // UUID
  email: string;
  name: string;
  role: "admin" | "recruiter" | "candidate";
  org_id?: string;              // nullable for candidates
  firebase_id?: string;
  profile_picture_url?: string;
  created_at: string;           // ISO 8601
  updated_at: string;
}
```

### Job Listing

```typescript
interface JobListing {
  id: string;                   // UUID
  org_id: string;
  created_by: string;           // user_id
  title: string;
  description: string;
  experience_level: "junior" | "mid" | "senior";
  skills: Skill[];
  requirements: {
    location?: string;
    min_salary?: number;
    max_salary?: number;
    education?: string;
  };
  interview_config: {
    rounds: number;
    duration_minutes: number;
    questions_count: number;
  };
  status: "draft" | "open" | "closed";
  created_at: string;
  updated_at: string;
}

interface Skill {
  name: string;
  required: boolean;
  weight: number;               // 0.0-1.0
  min_years: number;
}
```

### Interview Session

```typescript
interface InterviewSession {
  id: string;
  application_id: string;
  status: "created" | "active" | "ended" | "cancelled" | "failed";
  round: number;
  started_at?: string;
  ended_at?: string;
  agent_version?: string;
  context_snapshot: Record<string, any>;
  realtime: Record<string, any>;
  participants: InterviewParticipant[];
  turns?: InterviewTurn[];
  evaluation?: Evaluation;
  created_at: string;
  updated_at: string;
}
```

### Evaluation

```typescript
interface Evaluation {
  id: string;
  session_id: string;
  overall_score: number;        // 0-10
  recommendation: "strong_yes" | "yes" | "maybe" | "no" | "strong_no";
  summary: string;
  strengths: string[];
  concerns: string[];
  evidence: Record<string, any>;
  scores: EvaluationScore[];
  created_at: string;
  updated_at: string;
}

interface EvaluationScore {
  criterion: string;
  score: number;
  weight: number;
  notes?: string;
}
```

---

## Development Workflow

### 1. Local Development

```bash
# Backend
cd apps/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py

# Frontend (new terminal)
cd apps/frontend
npm install
npm run dev
```

### 2. Testing

```bash
# Backend unit tests
pytest tests/unit/

# Backend integration tests
pytest tests/integration/

# Backend e2e tests
pytest tests/e2e/

# Frontend tests
npm run test
```

### 3. Debugging

**Backend (VSCode)**:
```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "FastAPI",
      "type": "python",
      "request": "launch",
      "program": "${workspaceFolder}/apps/backend/run.py",
      "console": "integratedTerminal",
      "justMyCode": true
    }
  ]
}
```

**Frontend (Browser DevTools)**:
- Open Chrome DevTools (F12)
- Sources → Set breakpoints
- Console → Inspect network/WS

### 4. Code Quality

```bash
# Lint backend
flake8 src/

# Format backend
black src/

# Type check
mypy src/

# Lint frontend
npm run lint

# Format frontend
npm run format
```

---

## Code Examples

### Backend Example: Create Custom Service

```python
# src/truefit_core/application/services/custom_service.py

from typing import List
from uuid import UUID
from src.truefit_core.domain.job import Job
from src.truefit_core.application.ports import JobRepository
from src.truefit_core.common.utils import logger


class CustomJobService:
    """Custom business logic for jobs"""
    
    def __init__(self, job_repo: JobRepository):
        self.job_repo = job_repo
    
    async def get_jobs_by_skill(self, org_id: UUID, skill: str) -> List[Job]:
        """Get all jobs requiring a specific skill"""
        all_jobs = await self.job_repo.find_by_org(org_id)
        
        # Filter jobs that require the skill
        matching_jobs = [
            job for job in all_jobs
            if any(s['name'] == skill for s in job.skills)
        ]
        
        logger.info(f"Found {len(matching_jobs)} jobs requiring {skill}")
        return matching_jobs
```

### Frontend Example: WebSocket Hook

```typescript
// src/hooks/useInterview.ts

import { useEffect, useState, useCallback } from 'react';
import { InterviewWebSocket } from '@/helpers/websocket';

export const useInterview = (sessionId: string) => {
  const [connected, setConnected] = useState(false);
  const [transcript, setTranscript] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const ws = new InterviewWebSocket();

  useEffect(() => {
    const connect = async () => {
      try {
        await ws.connect(sessionId);
        setConnected(true);

        // Set up event handlers
        ws.on('transcript', (data) => {
          setTranscript(prev => [...prev, data.text]);
        });

        ws.on('error', (data) => {
          setError(data.message);
        });

      } catch (err) {
        setError(err instanceof Error ? err.message : 'Connection failed');
      }
    };

    connect();

    return () => {
      ws.close();
    };
  }, [sessionId]);

  return { connected, transcript, error, ws };
};
```

### Frontend Example: Interview Component

```typescript
// src/components/InterviewRoom.tsx

import React, { useEffect, useRef } from 'react';
import { useInterview } from '@/hooks/useInterview';

interface InterviewRoomProps {
  sessionId: string;
}

export const InterviewRoom: React.FC<InterviewRoomProps> = ({ sessionId }) => {
  const videoRef = useRef<HTMLVideoElement>(null);
  const { connected, transcript, error, ws } = useInterview(sessionId);

  useEffect(() => {
    if (connected) {
      // Start WebRTC
      setupWebRTC();
    }
  }, [connected]);

  const setupWebRTC = async () => {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: true,
      video: true
    });

    if (videoRef.current) {
      videoRef.current.srcObject = stream;
    }

    // Create peer connection and send offer
    const pc = new RTCPeerConnection();
    stream.getTracks().forEach(track => {
      pc.addTrack(track, stream);
    });

    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);

    ws.send('webrtc_offer', {
      type: 'offer',
      sdp: pc.localDescription?.sdp
    });
  };

  if (error) {
    return <div className="text-red-500">Error: {error}</div>;
  }

  return (
    <div className="space-y-4">
      <video
        ref={videoRef}
        autoPlay
        muted
        className="w-full rounded-lg"
      />
      
      <div className="bg-gray-100 rounded-lg p-4 max-h-64 overflow-y-auto">
        <h3 className="font-bold mb-2">Transcript</h3>
        {transcript.map((line, i) => (
          <p key={i} className="text-sm mb-2">{line}</p>
        ))}
      </div>
    </div>
  );
};
```

---

**Last Updated**: March 16, 2026
**Version**: 1.0
