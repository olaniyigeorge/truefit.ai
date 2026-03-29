import uuid


class SessionContext:
    """Immutable session metadata passed to every infra component."""

    __slots__ = ("session_id", "job_id", "candidate_id")

    def __init__(self, session_id: str, job_id: uuid.UUID, candidate_id: uuid.UUID):
        self.session_id = session_id
        self.job_id = job_id
        self.candidate_id = candidate_id
