"""
ports.py — Application-layer interface contracts (ports in hexagonal architecture).

Rules:
- Every class here is abstract. Zero implementation lives here.
- The application layer imports ONLY from this file for external dependencies.
- truefit_infra provides the concrete adapters; they are injected at startup.
- All methods are async to keep the application layer non-blocking throughout.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Optional

from src.truefit_core.domain.candidate import Candidate
from src.truefit_core.domain.evaluation import Evaluation
from src.truefit_core.domain.interview import Interview
from src.truefit_core.domain.job import Job
from src.truefit_infra.db.models import Application, User
from src.truefit_core.domain.org import Org


# ─────────────────
# Repository ports
# ─────────────────

class UserRepository(ABC):
    @abstractmethod
    async def save(self, user: User) -> None: ...

    @abstractmethod
    async def get_by_id(self, user_id: uuid.UUID) -> Optional[User]: ...

    @abstractmethod
    async def get_by_email(self, email: str) -> Optional[User]: ...





# ── Abstract port ───

class OrgRepository(ABC):
    @abstractmethod
    async def save(self, org: Org) -> None: ...

    @abstractmethod
    async def get_by_id(self, org_id: uuid.UUID) -> Optional[Org]: ...

    @abstractmethod
    async def get_by_slug(self, slug: str) -> Optional[Org]: ...

    @abstractmethod
    async def list_all(self, *, limit: int = 50, offset: int = 0) -> list[Org]: ...

    @abstractmethod
    async def delete(self, org_id: uuid.UUID) -> None: ...



# class OrgRepository(ABC):
    
#     async def create_org(
#         self,
#         *,
#         created_by: uuid.UUID,
#         name: str,
#         slug: str,
#         contact: dict,
#         billing: dict,
#         description: str | None = None,
#         industry: str | None = None,
#         headcount: str | None = None,
#         logo_url: str | None = None,
#     ) -> dict: ...
#     async def get_by_slug(self, slug: str) -> Optional[dict]: ...

class CandidateProfileRepository(ABC):
    async def create_for_user(
        self,
        *,
        user_id: uuid.UUID,
        headline: str | None = None,
        bio: str | None = None,
        location: str | None = None,
        years_experience: int | None = None,
        skills: list[str] | None = None,
    ) -> dict: ...
    async def get_by_user_id(self, user_id: uuid.UUID) -> Optional[dict]: ...



class JobRepository(ABC):
    @abstractmethod
    async def save(self, job: Job) -> None: ...

    @abstractmethod
    async def get_by_id(self, job_id: uuid.UUID) -> Optional[Job]: ...

    @abstractmethod
    async def get_by_company(
        self, org_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> list[Job]: ...

    @abstractmethod
    async def delete(self, job_id: uuid.UUID) -> None: ...


class CandidateRepository(ABC):
    @abstractmethod
    async def save(self, candidate: Candidate) -> None: ...

    @abstractmethod
    async def get_by_id(self, candidate_id: uuid.UUID) -> Optional[Candidate]: ...

    @abstractmethod
    async def get_by_email(self, email: str) -> Optional[Candidate]: ...

    @abstractmethod
    async def delete(self, candidate_id: uuid.UUID) -> None: ...


class InterviewRepository(ABC):
    @abstractmethod
    async def save(self, interview: Interview) -> None: ...

    @abstractmethod
    async def get_by_id(self, interview_id: uuid.UUID) -> Optional[Interview]: ...

    @abstractmethod
    async def list_by_candidate(
        self, candidate_id: uuid.UUID, *, limit: int = 20, offset: int = 0
    ) -> list[Interview]: ...

    @abstractmethod
    async def list_by_job(
        self, job_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> list[Interview]: ...

    @abstractmethod
    async def get_active_for_job_and_candidate(
        self,
        *,
        job_id: uuid.UUID,
        candidate_id: uuid.UUID,
    ) -> Optional[Interview]:
        ...

    @abstractmethod
    async def close_dangling_questions(self, interview_id: uuid.UUID) -> int:
        """
        Load the interview, void any unanswered questions, persist it.
        Returns the number of questions voided.
        """
        ...

class EvaluationRepository(ABC):
    @abstractmethod
    async def save(self, evaluation: Evaluation) -> None: ...

    @abstractmethod
    async def get_by_id(self, evaluation_id: uuid.UUID) -> Optional[Evaluation]: ...

    @abstractmethod
    async def get_by_interview(self, interview_id: uuid.UUID) -> Optional[Evaluation]: ...

    @abstractmethod
    async def list_by_job(
        self, job_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> list[Evaluation]: ...

    @abstractmethod
    async def list_by_candidate(
        self, candidate_id: uuid.UUID, *, limit: int = 20, offset: int = 0
    ) -> list[Evaluation]: ...


# ─────────────────────────────────────────────────────────────────────────────
# LLM port
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class QuestionContext:
    """
    All context the LLM needs to produce the next adaptive question.
    Constructed by the InterviewOrchestrationService.
    """
    job_title: str
    job_description: str
    required_skills: list[str]
    experience_level: str
    custom_instructions: Optional[str]
    transcript: list[dict]             # Interview.transcript so far
    topics_remaining: list[str]        # guides topic coverage
    question_number: int
    total_questions: int


@dataclass
class GeneratedQuestion:
    text: str
    topic: Optional[str] = None
    is_follow_up: bool = False


@dataclass
class EvaluationRequest:
    """Everything the LLM needs to produce a structured evaluation."""
    job_title: str
    job_description: str
    required_skills: list[str]         # skill names, for score mapping
    experience_level: str
    transcript: list[dict]             # Interview.transcript
    custom_instructions: Optional[str] = None


@dataclass
class LLMEvaluationResult:
    """
    Raw structured output from the LLM evaluation call.
    The application layer maps this onto the Evaluation domain object.
    """
    recommendation: str                    # maps to HiringRecommendation
    overall_score: float                   # 0–10
    technical_score: float
    communication_score: float
    problem_solving_score: float
    culture_fit_score: float
    skill_scores: list[dict]               # [{skill_name, score, rationale}]
    summary: str
    strengths: list[str]
    weaknesses: list[str]
    model_version: Optional[str] = None


class LLMPort(ABC):
    """Interface to the underlying language model (e.g. Gemini via truefit_infra)."""

    @abstractmethod
    async def generate_question(self, context: QuestionContext) -> GeneratedQuestion:
        """
        Generate the next interview question given the current conversation context.
        Must be adaptive — prior answers should influence the question.
        """
        ...

    @abstractmethod
    async def evaluate_interview(self, request: EvaluationRequest) -> LLMEvaluationResult:
        """
        Produce a structured evaluation of the full interview transcript.
        """
        ...

    @abstractmethod
    async def is_healthy(self) -> bool:
        """Lightweight connectivity / availability check for health endpoints."""
        ...


# ─────────────────────────────────────────────────────────────────────────────
# Queue / event bus port
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class DomainEvent:
    """
    Base for all events published to the queue.
    Fields here are guaranteed on every event; concrete events add their own.
    """
    event_type: str
    payload: dict[str, Any]
    aggregate_id: str
    aggregate_type: str
    occurred_at: str         # ISO-8601 UTC string — keep it serialisable


class QueuePort(ABC):
    @abstractmethod
    async def publish(self, event: DomainEvent) -> None:
        """
        Publish an event to the message bus (e.g. Redis Streams, Pub/Sub, SQS).
        Fire-and-forget from the application layer's perspective;
        retries / DLQ are infra concerns.
        """
        ...

    @abstractmethod
    async def is_healthy(self) -> bool: ...


# ─────────────────────────────────────────────────────────────────────────────
# Storage port
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class StoredFile:
    key: str
    content_type: str
    size_bytes: int
    url: Optional[str] = None  # presigned URL if applicable


class StoragePort(ABC):
    @abstractmethod
    async def upload(
        self,
        *,
        key: str,
        data: bytes,
        content_type: str,
    ) -> StoredFile:
        """Upload raw bytes and return file metadata."""
        ...

    @abstractmethod
    async def download(self, key: str) -> bytes: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def get_presigned_url(self, key: str, *, expires_in_seconds: int = 3600) -> str:
        """Return a time-limited URL for direct client access."""
        ...

    @abstractmethod
    async def exists(self, key: str) -> bool: ...

    @abstractmethod
    async def is_healthy(self) -> bool: ...


# ─────────────────────────────────────────────────────────────────────────────
# Cache port
# ─────────────────────────────────────────────────────────────────────────────


class CachePort(ABC):
    """
    Thin abstraction over a key-value cache (e.g. Redis).
    Used for session state, rate-limiting, and short-lived locks.
    """

    @abstractmethod
    async def get(self, key: str) -> Optional[Any]: ...

    @abstractmethod
    async def set(self, key: str, value: Any, *, ttl_seconds: Optional[int] = None) -> None: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def exists(self, key: str) -> bool: ...

    @abstractmethod
    async def increment(self, key: str, *, ttl_seconds: Optional[int] = None) -> int:
        """Atomic increment — useful for rate limiting."""
        ...

    @abstractmethod
    async def is_healthy(self) -> bool: ...




class ApplicationRepository(ABC):

    @abstractmethod
    async def save(self, application: Application) -> None: ...

    @abstractmethod
    async def get_by_id(self, application_id: uuid.UUID) -> Optional[Application]: ...

    @abstractmethod
    async def get_by_job_and_candidate(
        self, job_id: uuid.UUID, candidate_id: uuid.UUID
    ) -> Optional[Application]: ...

    @abstractmethod
    async def list_by_job(
        self,
        job_id: uuid.UUID,
        *,
        status: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Application]: ...

    @abstractmethod
    async def list_by_candidate(
        self,
        candidate_id: uuid.UUID,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Application]: ...

    @abstractmethod
    async def delete(self, application_id: uuid.UUID) -> None: ...



class LiveSessionPort(ABC):
    """
    Abstraction over a real-time multimodal AI session.

    Implementations wrap a live AI API (e.g. Gemini Live) and expose a
    uniform interface for the agent layer. The agent never imports any
    AI SDK directly — all SDK types are confined to the adapter.

    Lifecycle
    ─────────
    All methods except open_session() require an active session.
    Sessions are opened and closed via the open_session() context manager:

        async with adapter.open_session(system_prompt, tools=tools) as session:
            await session.send_client_content(text="...")
            await session.send_audio(pcm_bytes)
            async for event_type, data in session.receive():
                ...

    Audio format contract
    ─────────────────────
    Implementations must accept 16kHz mono s16 PCM for send_audio().
    Callers must not assume a specific output sample rate — check the
    concrete adapter's docstring (Gemini Live returns 24kHz).
    """

    # ── Session lifecycle ─────────────────────────────────────────────────────

    @abstractmethod
    def open_session(
        self,
        system_prompt: str,
        tools: list | None = None,
    ) -> Any:
        """
        Return an async context manager that opens and closes the session.
        Must be used as: async with adapter.open_session(...) as session.
        The yielded value is the adapter itself with an active session.
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Tear down the active session. Called automatically by open_session()."""
        ...

    # ── Sending ───────────────────────────────────────────────────────────────

    @abstractmethod
    async def send_audio(self, pcm_bytes: bytes) -> None:
        """
        Stream a raw PCM audio chunk into the session.
        Expected format: 16kHz mono s16 (320 bytes per 20ms chunk).
        """
        ...

    @abstractmethod
    async def send_image(self, jpeg_bytes: bytes, source: str = "camera") -> None:
        """
        Send a JPEG frame into the session for visual context.
        source: "camera" | "screen" — used for logging/context only.
        """
        ...

    @abstractmethod
    async def send_client_content(self, text: str) -> None:
        """
        Inject a one-time structured text message into the session.
        Used before audio begins to pre-load context (job, candidate data).
        Not for conversational turns — use send_audio() for those.
        """
        ...

    @abstractmethod
    async def send_tool_response(
        self,
        *,
        call_id: str,
        name: str,
        result: dict,
    ) -> None:
        """
        Respond to a tool_call event from receive().
        Must be called for every tool_call received — the session blocks
        until a response is provided.
        """
        ...

    # ── Receiving ─────────────────────────────────────────────────────────────

    @abstractmethod
    async def receive(self) -> AsyncGenerator[tuple[str, Any], None]:
        """
        Async generator yielding normalised events from the model.

        Event types:
          ("audio",         bytes)  — PCM audio to play to the candidate
          ("text",          str)    — agent output transcript
          ("input_text",    str)    — candidate speech transcript
          ("tool_call",     dict)   — {"id": str, "name": str, "args": dict}
          ("turn_complete", None)   — agent finished its speaking turn
          ("interrupted",   None)   — agent was interrupted mid-speech
          ("go_away",       None)   — server is closing the connection

        Implementations must not raise on end-of-stream — simply stop yielding.
        """
        ...

    # ── Health ────────────────────────────────────────────────────────────────

    @abstractmethod
    async def is_healthy(self) -> bool:
        """Return True if there is an active open session."""
        ...