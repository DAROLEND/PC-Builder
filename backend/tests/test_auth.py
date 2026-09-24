import pytest

pytestmark = pytest.mark.django_db


def test_register_login_me(api):
    resp = api.post(
        "/api/auth/register/",
        {"username": "newbie", "email": "New@Example.com", "password": "Very-long-pass-42"},
    )
    assert resp.status_code == 201, resp.data
    assert "password" not in resp.data

    tokens = api.post("/api/auth/token/", {"username": "newbie", "password": "Very-long-pass-42"})
    assert tokens.status_code == 200
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens.data['access']}")

    me = api.get("/api/auth/me/")
    assert me.data["username"] == "newbie"
    assert me.data["email"] == "new@example.com"


def test_weak_or_duplicate_registration_rejected(api, user):
    weak = api.post("/api/auth/register/", {"username": "x", "email": "x@x.com", "password": "123"})
    assert weak.status_code == 400
    dup = api.post(
        "/api/auth/register/",
        {"username": "other", "email": user.email.upper(), "password": "Very-long-pass-42"},
    )
    assert dup.status_code == 400
    assert "email" in dup.data


def test_me_requires_auth(api):
    assert api.get("/api/auth/me/").status_code == 401
