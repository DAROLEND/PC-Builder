from decimal import Decimal

import pytest
from django.core import mail
from django.db import IntegrityError, transaction

from apps.builds.models import Build, BuildComponent, Comment
from tests.factories import make_build

pytestmark = pytest.mark.django_db


def items(ids, **quantities):
    return [{"component": i, "quantity": quantities.get(str(i), 1)} for i in ids]


# --- create / validate ------------------------------------------------------------


def test_create_valid_build(auth_api, budget_gaming_ids, user):
    resp = auth_api.post(
        "/api/builds/",
        {"name": "My rig", "is_public": True, "items": items(budget_gaming_ids)},
    )
    assert resp.status_code == 201, resp.data
    assert resp.data["owner"] == user.username
    assert resp.data["compatibility"]["is_compatible"] is True
    assert resp.data["compatibility"]["is_complete"] is True
    assert Decimal(resp.data["total_price"]) == sum(
        BuildComponent.objects.get(build_id=resp.data["id"], component_id=i).component.price
        for i in budget_gaming_ids
    )


def test_anonymous_cannot_create(api, budget_gaming_ids):
    resp = api.post("/api/builds/", {"name": "x", "items": items(budget_gaming_ids)})
    assert resp.status_code == 401


def test_incompatible_build_is_rejected_with_report(auth_api, comp):
    ids = [comp("Ryzen 5 7600").id, comp("B450M Pro4").id]  # AM5 CPU on an AM4 board
    resp = auth_api.post("/api/builds/", {"name": "Broken", "items": items(ids)})
    assert resp.status_code == 400
    error_codes = {e["code"] for e in resp.data["compatibility"]["errors"]}
    assert "CPU_SOCKET_MISMATCH" in error_codes
    assert not Build.objects.filter(name="Broken").exists()


def test_incomplete_build_can_be_saved_as_draft(auth_api, comp):
    resp = auth_api.post(
        "/api/builds/", {"name": "Draft", "items": items([comp("Ryzen 5 7600").id])}
    )
    assert resp.status_code == 201
    assert resp.data["compatibility"]["is_complete"] is False
    assert "motherboard" in resp.data["compatibility"]["missing"]


def test_duplicate_component_rejected(auth_api, comp):
    cpu = comp("Ryzen 5 7600").id
    resp = auth_api.post("/api/builds/", {"name": "Dup", "items": items([cpu, cpu])})
    assert resp.status_code == 400
    assert "items" in resp.data


def test_quantity_bounds_validated(auth_api, comp):
    resp = auth_api.post(
        "/api/builds/",
        {"name": "Q", "items": [{"component": comp("P3 Plus 1TB").id, "quantity": 9}]},
    )
    assert resp.status_code == 400


def test_inactive_component_rejected(auth_api, comp):
    part = comp("Ryzen 5 7600")
    part.is_active = False
    part.save()
    resp = auth_api.post("/api/builds/", {"name": "Old", "items": items([part.id])})
    assert resp.status_code == 400


def test_duplicate_build_name_per_owner(auth_api, user):
    make_build(user, [], name="Same")
    resp = auth_api.post("/api/builds/", {"name": "Same"})
    assert resp.status_code == 400
    assert "name" in resp.data


def test_db_constraints_back_up_the_serializer(user, comp):
    build = make_build(user, [comp("Ryzen 5 7600")])
    with pytest.raises(IntegrityError), transaction.atomic():
        BuildComponent.objects.create(build=build, component=comp("Ryzen 5 7600"))
    with pytest.raises(IntegrityError), transaction.atomic():
        BuildComponent.objects.create(build=build, component=comp("P3 Plus 1TB"), quantity=0)


def test_update_replaces_items(auth_api, user, comp, budget_gaming_ids):
    build = make_build(user, [comp("Ryzen 5 7600")], name="Mine")
    resp = auth_api.patch(f"/api/builds/{build.id}/", {"items": items(budget_gaming_ids)})
    assert resp.status_code == 200, resp.data
    assert sorted(i["component"]["id"] for i in resp.data["items"]) == sorted(budget_gaming_ids)


def test_patch_without_items_keeps_items(auth_api, user, comp):
    build = make_build(user, [comp("Ryzen 5 7600")], name="Keep")
    resp = auth_api.patch(f"/api/builds/{build.id}/", {"description": "new"})
    assert resp.status_code == 200
    assert len(resp.data["items"]) == 1


# --- permissions / visibility -------------------------------------------------------


def test_private_build_is_invisible_to_others(api, other_user, user, comp):
    private = make_build(other_user, [comp("Ryzen 5 7600")], is_public=False)
    api.force_authenticate(user)
    assert api.get(f"/api/builds/{private.id}/").status_code == 404
    assert private.id not in [b["id"] for b in api.get("/api/builds/").data["results"]]


def test_owner_sees_own_private_build(auth_api, user, comp):
    private = make_build(user, [comp("Ryzen 5 7600")], is_public=False)
    assert auth_api.get(f"/api/builds/{private.id}/").status_code == 200


def test_non_owner_cannot_modify_public_build(auth_api, other_user, comp):
    public = make_build(other_user, [comp("Ryzen 5 7600")], is_public=True)
    assert auth_api.patch(f"/api/builds/{public.id}/", {"name": "hijack"}).status_code == 403
    assert auth_api.delete(f"/api/builds/{public.id}/").status_code == 403


def test_clone_public_build(auth_api, user, other_user, comp):
    source = make_build(other_user, [comp("Ryzen 5 7600"), comp("P3 Plus 1TB")], name="Cool")
    resp = auth_api.post(f"/api/builds/{source.id}/clone/")
    assert resp.status_code == 201
    assert resp.data["name"] == "Copy of Cool"
    assert resp.data["owner"] == user.username
    assert resp.data["is_public"] is False
    second = auth_api.post(f"/api/builds/{source.id}/clone/")
    assert second.data["name"] == "Copy of Cool (2)"


# --- list: annotations and N+1 --------------------------------------------------------


def test_list_annotations(auth_api, user, comp):
    cpu, ssd = comp("Ryzen 5 7600"), comp("P3 Plus 1TB")
    build = make_build(user, [cpu, ssd], quantities={ssd.id: 2})
    Comment.objects.create(build=build, author=user, text="a")
    Comment.objects.create(build=build, author=user, text="b")
    Comment.objects.create(build=build, author=user, text="c")

    row = next(b for b in auth_api.get("/api/builds/").data["results"] if b["id"] == build.id)
    # Comments must not multiply the SUM over components.
    assert Decimal(row["total_price"]) == cpu.price + 2 * ssd.price
    assert row["parts_count"] == 3
    assert row["comments_count"] == 3


def test_total_price_not_affected_by_component_filter(api, user, comp):
    cpu, gpu = comp("Ryzen 5 7600"), comp("PULSE Radeon RX 7600 8GB")
    build = make_build(user, [cpu, gpu])
    rows = api.get(f"/api/builds/?component={gpu.id}").data["results"]
    assert [r["id"] for r in rows] == [build.id]
    assert Decimal(rows[0]["total_price"]) == cpu.price + gpu.price


def test_order_by_total_price(api, user, comp):
    cheap = make_build(user, [comp("Ryzen 5 5600")])
    pricey = make_build(user, [comp("Ryzen 9 9950X")])
    ids = [r["id"] for r in api.get("/api/builds/?ordering=-total_price").data["results"]]
    assert ids.index(pricey.id) < ids.index(cheap.id)


def test_list_query_count_does_not_grow_with_builds(api, user, comp, django_assert_max_num_queries):
    parts = [comp("Ryzen 5 7600"), comp("P3 Plus 1TB"), comp("AK400")]
    for _ in range(3):
        make_build(user, parts)
    with django_assert_max_num_queries(3):  # count + page (+ savepoint slack)
        api.get("/api/builds/")


def test_detail_query_count_is_constant(
    api, user, budget_gaming_ids, django_assert_max_num_queries
):
    from apps.catalog.models import Component

    build = make_build(user, list(Component.objects.filter(id__in=budget_gaming_ids)))
    # build + lines with component/category/manufacturer + listings + photos;
    # the same for 8 parts or 80.
    with django_assert_max_num_queries(4):
        resp = api.get(f"/api/builds/{build.id}/")
    assert len(resp.data["items"]) == 8


# --- comments ---------------------------------------------------------------------------


def test_comment_notifies_owner(api, user, other_user, comp, django_capture_on_commit_callbacks):
    build = make_build(other_user, [comp("Ryzen 5 7600")])
    api.force_authenticate(user)
    with django_capture_on_commit_callbacks(execute=True):
        resp = api.post(f"/api/builds/{build.id}/comments/", {"text": "Nice build!"})
    assert resp.status_code == 201
    assert len(mail.outbox) == 1
    assert other_user.email in mail.outbox[0].to


def test_commenting_own_build_sends_no_email(
    auth_api, user, comp, django_capture_on_commit_callbacks
):
    build = make_build(user, [comp("Ryzen 5 7600")])
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        auth_api.post(f"/api/builds/{build.id}/comments/", {"text": "note to self"})
    assert callbacks == []
    assert mail.outbox == []


def test_cannot_comment_on_hidden_build(auth_api, other_user, comp):
    private = make_build(other_user, [comp("Ryzen 5 7600")], is_public=False)
    assert auth_api.post(f"/api/builds/{private.id}/comments/", {"text": "hi"}).status_code == 404


def test_comment_moderation(api, user, other_user, comp):
    build = make_build(user, [comp("Ryzen 5 7600")])
    comment = Comment.objects.create(build=build, author=other_user, text="spam")

    api.force_authenticate(user)  # build owner
    assert api.patch(f"/api/comments/{comment.id}/", {"text": "edited"}).status_code == 403
    assert api.delete(f"/api/comments/{comment.id}/").status_code == 204


# --- stateless check ----------------------------------------------------------------------


def test_stateless_compatibility_check(api, comp):
    resp = api.post(
        "/api/compatibility/check/",
        {"items": items([comp("TUF Gaming GeForce RTX 5070 Ti 16GB").id, comp("CH370").id])},
    )
    assert resp.status_code == 200
    assert {e["code"] for e in resp.data["errors"]} == {"GPU_TOO_LONG"}
    assert resp.data["estimated_wattage"] > 300


def test_money_is_a_decimal_string_everywhere(api, user, comp):
    """Contract test on the rendered JSON: the frontend types rely on it."""
    build = make_build(user, [comp("Ryzen 5 7600")])
    detail = api.get(f"/api/builds/{build.id}/").json()
    listing = api.get("/api/builds/").json()["results"][0]
    assert isinstance(detail["total_price"], str)
    assert isinstance(detail["items"][0]["line_total"], str)
    assert isinstance(listing["total_price"], str)
