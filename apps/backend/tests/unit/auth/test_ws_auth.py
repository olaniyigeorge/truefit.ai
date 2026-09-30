import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest

from src.truefit_api.api.v1.ws.auth import (
    WS_FORBIDDEN,
    WS_UNAUTHORIZED,
    authenticate_interview_socket,
)
from src.truefit_infra.auth.jwt import JWTService

pytestmark = pytest.mark.unit

jwt_service = JWTService(secret_key="x" * 40, algorithm="HS256", access_token_expire_minutes=30)


class FakeSocket:
    def __init__(self, token=None):
        self.query_params = {"token": token} if token else {}
        self.closed_with = None

    async def close(self, code=1000, reason=None):
        self.closed_with = code


class FakeCandidates:
    def __init__(self, candidate):
        self._candidate = candidate

    async def get_by_id(self, candidate_id):
        return self._candidate


def token_for(user_id, role="candidate", **kw):
    return jwt_service.create_access_token(
        subject=str(user_id), user_email="u@example.com", user_role=role, **kw
    )


async def connect(socket, candidate, candidate_id=None):
    return await authenticate_interview_socket(
        socket,
        candidate_id=candidate_id or uuid.uuid4(),
        candidate_repo=FakeCandidates(candidate),
        jwt_service=jwt_service,
    )


async def test_missing_token_is_rejected_with_4401():
    socket = FakeSocket()
    assert await connect(socket, None) is None
    assert socket.closed_with == WS_UNAUTHORIZED


async def test_garbage_token_is_rejected_with_4401():
    socket = FakeSocket("not.a.jwt")
    assert await connect(socket, None) is None
    assert socket.closed_with == WS_UNAUTHORIZED


async def test_expired_token_is_rejected_with_4401():
    uid = uuid.uuid4()
    socket = FakeSocket(token_for(uid, expires_delta=timedelta(seconds=-5)))
    assert await connect(socket, SimpleNamespace(user_id=uid)) is None
    assert socket.closed_with == WS_UNAUTHORIZED


async def test_candidate_may_join_their_own_interview():
    uid = uuid.uuid4()
    socket = FakeSocket(token_for(uid))
    user = await connect(socket, SimpleNamespace(user_id=uid))
    assert user is not None and user.user_id == str(uid)
    assert socket.closed_with is None


async def test_candidate_may_not_join_someone_elses_interview():
    socket = FakeSocket(token_for(uuid.uuid4()))
    assert await connect(socket, SimpleNamespace(user_id=uuid.uuid4())) is None
    assert socket.closed_with == WS_FORBIDDEN


async def test_unknown_candidate_looks_the_same_as_forbidden():
    socket = FakeSocket(token_for(uuid.uuid4()))
    assert await connect(socket, None) is None
    assert socket.closed_with == WS_FORBIDDEN


async def test_recruiter_may_not_join_a_candidates_interview():
    socket = FakeSocket(token_for(uuid.uuid4(), role="recruiter"))
    assert await connect(socket, SimpleNamespace(user_id=uuid.uuid4())) is None
    assert socket.closed_with == WS_FORBIDDEN


async def test_admin_may_join_any_interview():
    socket = FakeSocket(token_for(uuid.uuid4(), role="admin"))
    assert await connect(socket, SimpleNamespace(user_id=uuid.uuid4())) is not None
    assert socket.closed_with is None
