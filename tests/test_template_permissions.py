"""Template creation, global collaboration, and ownership remain independent."""

import pytest
from test_access_security import accounts as account_fixture
from test_auth import change

accounts = account_fixture


def grants(admin, *permissions):
    change(
        admin,
        "roles",
        "PUT",
        {
            "name": "Alice template access",
            "permissions": [
                {"kind": "destination", "destination_id": "main", "level": "request"},
                *({"kind": "application", "permission": value} for value in permissions),
            ],
        },
        "alice-access",
    )
    change(admin, "users", "PUT", {"disabled": False, "role_ids": ["alice-access"]}, "alice")


def template(client, name, scope="personal", **extra):
    document = client.get("/api/templates/text").json()["document"]
    return client.post(
        "/api/templates", json={"name": name, "scope": scope, "document": document, **extra}
    )


@pytest.mark.parametrize(
    "personal,global_", [(False, False), (True, False), (False, True), (True, True)]
)
def test_template_creation_requires_its_own_scope_permission(accounts, personal, global_):
    admin, alice, _ = accounts
    permissions = []
    if personal:
        permissions.append("templates.create_personal")
    if global_:
        permissions.append("templates.create_global")
    grants(admin, *permissions)
    for scope, allowed in (("personal", personal), ("global", global_)):
        response = template(alice, f"Alice {scope}", scope)
        assert response.status_code == (201 if allowed else 403), response.text
        if allowed:
            assert response.json()["owner_id"] == "alice"
    group = change(
        admin, "groups", "POST", {"name": "View only", "members": [{"user_id": "alice"}]}
    ).json()
    assert template(alice, "No group creation", "group", group_id=group["id"]).status_code == 403


@pytest.mark.parametrize(
    "edit,delete", [(False, False), (True, False), (False, True), (True, True)]
)
def test_global_edit_and_delete_permissions_are_independent(accounts, edit, delete):
    admin, alice, _ = accounts
    permissions = []
    if edit:
        permissions.append("templates.edit_global")
    if delete:
        permissions.append("templates.delete_global")
    grants(admin, *permissions)
    shared = template(admin, "Shared global", "global").json()
    removable = template(admin, "Removable global", "global").json()
    private = template(admin, "Private original").json()
    visible = alice.get(f"/api/templates/{shared['id']}").json()
    assert visible["can_edit"] is edit
    assert visible["can_delete"] is delete
    response = alice.put(
        f"/api/templates/{shared['id']}",
        json={
            "name": "Edited global",
            "scope": "global",
            "document": shared["document"],
            "expected_revision": shared["revision"],
        },
    )
    assert response.status_code == (200 if edit else 403), response.text
    assert alice.delete(f"/api/templates/{shared['id']}").status_code == (200 if delete else 403)
    assert alice.delete(f"/api/templates/{removable['id']}/permanent").status_code == (
        200 if delete else 403
    )
    assert template(alice, "Cannot create global", "global").status_code == 403
    assert template(alice, "Cannot create personal").status_code == 403
    assert alice.get(f"/api/templates/{private['id']}").status_code == 403
    assert (
        alice.put(
            f"/api/templates/{private['id']}",
            json={
                "name": "Cannot edit private",
                "scope": "personal",
                "document": private["document"],
                "expected_revision": private["revision"],
            },
        ).status_code
        == 403
    )
    assert alice.delete(f"/api/templates/{private['id']}/permanent").status_code == 403


def test_global_edit_permission_cannot_change_another_owners_sharing(accounts):
    admin, alice, _ = accounts
    grants(admin, "templates.edit_global", "templates.create_personal")
    shared = template(admin, "Shared global", "global").json()
    response = alice.put(
        f"/api/templates/{shared['id']}",
        json={
            "name": "Cannot take private",
            "scope": "personal",
            "document": shared["document"],
            "expected_revision": shared["revision"],
        },
    )
    assert response.status_code == 403
    assert admin.get(f"/api/templates/{shared['id']}").json()["scope"] == "global"
    grants(admin)
    assert alice.get(f"/api/templates/{shared['id']}").json()["can_edit"] is False


def test_owners_keep_editing_existing_templates_after_creation_access_is_revoked(accounts):
    admin, alice, _ = accounts
    grants(admin, "templates.create_personal", "templates.create_global")
    personal = template(alice, "Own personal").json()
    global_ = template(alice, "Own global", "global").json()
    grants(admin)
    for saved in (personal, global_):
        response = alice.put(
            f"/api/templates/{saved['id']}",
            json={
                "name": "Still editable",
                "scope": saved["scope"],
                "document": saved["document"],
                "expected_revision": saved["revision"],
            },
        )
        assert response.status_code == 200, response.text
        assert alice.delete(f"/api/templates/{saved['id']}").status_code == 200
    assert template(alice, "New personal").status_code == 403
    assert template(alice, "New global", "global").status_code == 403
