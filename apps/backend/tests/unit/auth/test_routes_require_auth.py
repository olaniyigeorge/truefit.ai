"""
Regression guard: every HTTP route except the explicit public ones must depend
on get_current_user, so a new router cannot ship unauthenticated by accident.
"""

import pytest
from fastapi.routing import APIRoute

from src.truefit_api.main import app
from src.truefit_infra.auth.middleware import get_current_user

pytestmark = pytest.mark.unit

PUBLIC = {
    ("GET", "/api/v1/health"),
    ("GET", "/api/v1/"),  # API root banner
    ("POST", "/api/v1/auth/oauth/token"),
}


def _depends_on_auth(dependant) -> bool:
    if dependant.call is get_current_user:
        return True
    return any(_depends_on_auth(d) for d in dependant.dependencies)


def _api_routes():
    return [
        r
        for r in app.routes
        if isinstance(r, APIRoute) and r.path.startswith("/api/v1")
    ]


def test_there_are_routes_to_check():
    assert len(_api_routes()) > 30


def test_every_non_public_route_requires_a_jwt():
    unprotected = []
    for route in _api_routes():
        for method in route.methods - {"HEAD", "OPTIONS"}:
            if (method, route.path) in PUBLIC:
                continue
            if not _depends_on_auth(route.dependant):
                unprotected.append(f"{method} {route.path}")
    assert unprotected == []


def test_the_public_list_only_names_routes_that_exist():
    existing = {
        (m, r.path) for r in _api_routes() for m in r.methods
    }
    assert PUBLIC <= existing
