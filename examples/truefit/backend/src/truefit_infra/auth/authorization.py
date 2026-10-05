"""
Authorization helpers: who may do what, on top of authentication.

Authentication (a valid JWT) is enforced for whole routers in main.py. These
helpers answer the next question, whether the authenticated user may act on a
particular resource. Roles come from the JWT `role` claim, which is fixed when
the token is issued (POST /auth/refresh picks up changes).

    @router.post("/{job_id}/close")
    async def close_job(job_id: UUID, user: TokenPayload = Depends(get_current_user)):
        job = await svc.get(job_id)
        ensure_org_member(user, job.org_id)   # admin, or a recruiter in that org
"""

from __future__ import annotations

import uuid
from typing import Callable, Optional

from fastapi import Depends, HTTPException, status

from src.truefit_infra.auth.middleware import TokenPayload, get_current_user

ADMIN = "admin"
RECRUITER = "recruiter"
CANDIDATE = "candidate"


def _forbidden(detail: str = "You do not have permission to perform this action") -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _same(a: object, b: object) -> bool:
    """Compare ids that may arrive as UUID or str."""
    return a is not None and b is not None and str(a) == str(b)


def is_admin(user: TokenPayload) -> bool:
    return user.role == ADMIN


def require_roles(*roles: str) -> Callable[..., TokenPayload]:
    """Dependency factory: the caller must hold one of `roles` (admin always passes)."""

    async def dependency(user: TokenPayload = Depends(get_current_user)) -> TokenPayload:
        if user.role != ADMIN and user.role not in roles:
            raise _forbidden()
        return user

    return dependency


def ensure_self(user: TokenPayload, user_id: object) -> None:
    """The caller is `user_id`, or an admin."""
    if not (is_admin(user) or _same(user.user_id, user_id)):
        raise _forbidden()


def ensure_org_member(user: TokenPayload, org_id: Optional[object]) -> None:
    """The caller is an admin, or a recruiter who belongs to `org_id`."""
    if is_admin(user):
        return
    if user.role == RECRUITER and _same(user.org_id, org_id):
        return
    raise _forbidden()


def can_view_as_org_member(user: TokenPayload, org_id: Optional[object]) -> bool:
    """Non-raising form of ensure_org_member, for filtering lists."""
    return is_admin(user) or (user.role == RECRUITER and _same(user.org_id, org_id))


def ensure_self_or_org_member(
    user: TokenPayload, owner_user_id: object, org_id: Optional[object]
) -> None:
    """The caller owns the resource (owner_user_id), or is an admin or recruiter of `org_id`."""
    if _same(user.user_id, owner_user_id) or can_view_as_org_member(user, org_id):
        return
    raise _forbidden()
