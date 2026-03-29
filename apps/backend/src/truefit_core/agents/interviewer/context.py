from dataclasses import dataclass
from typing import Optional
import uuid


@dataclass
class InterviewContext:
    """
    Everything the agent needs to know before the interview starts.
    Built by the WebSocket handler from the DB and injected once via
    send_client_content before audio streaming begins.
    """

    interview_id: uuid.UUID
    job_title: str
    job_description: str
    required_skills: list[str]
    experience_level: str
    max_questions: int
    max_duration_minutes: int
    topics: list[str]
    custom_instructions: Optional[str]
    candidate_name: str
    candidate_resume_text: Optional[str]  # pre-extracted text from resume PDF
