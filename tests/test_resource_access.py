import pytest
from sqlalchemy.exc import IntegrityError

from app.models import (
    Cartridge,
    Location,
    PrinterDevice,
    PrinterGroup,
    ResourceGrant,
    Role,
    TapeProfile,
    User,
)
from app.resource_access import (
    CARTRIDGE_PERMISSIONS,
    GROUP_PERMISSIONS,
    PRINTER_PERMISSIONS,
    legacy_permissions,
    location_ancestors,
    resolve_resource_access,
    validate_grant,
    validate_location_parent,
)


def seed(session):
    session.add_all(
        [
            Role(id="staff", name="Staff", permissions=[]),
            Role(id="administrator", name="Administrator", permissions=[], protected=True),
            User(id="owner", username="owner", password_hash="unused", role_ids=[]),
            User(
                id="staff-user", username="staff-user", password_hash="unused", role_ids=["staff"]
            ),
            User(id="admin", username="admin", password_hash="unused", role_ids=["administrator"]),
            Location(id="home", name="Home"),
            Location(id="other", name="Other"),
            TapeProfile(
                id="tape", name="Tape", width_mm=24, background="#ffffff", foreground="#000000"
            ),
        ]
    )
    session.flush()
    session.add(Location(id="room", name="Room", parent_id="home"))
    session.flush()
    session.add_all(
        [
            PrinterDevice(
                id="p",
                name="Printer",
                driver="mock",
                config={},
                location_id="room",
                owner_id="owner",
            ),
            PrinterDevice(
                id="q", name="Other printer", driver="mock", config={}, location_id="other"
            ),
            PrinterGroup(id="g", name="Group", printer_ids=["p", "q"]),
            Cartridge(
                id="c",
                name="Tape",
                profile_id="tape",
                nominal_length_mm=8000,
                remaining_mm=8000,
                location_id="room",
                owner_id="owner",
            ),
        ]
    )
    session.flush()
    return session.get(User, "staff-user")


def grant(
    session,
    permission,
    scope_kind="printer",
    scope_id="p",
    principal_kind="user",
    principal_id="staff-user",
):
    value = ResourceGrant(
        principal_kind=principal_kind,
        principal_id=principal_id,
        scope_kind=scope_kind,
        scope_id=scope_id,
        permission=permission,
    )
    validate_grant(session, value)
    session.add(value)
    session.flush()
    return value


def test_independent_grants_do_not_turn_into_a_legacy_level(foundation_session):
    session = foundation_session
    user = seed(session)
    grant(session, "printer.swap_cartridges")
    grant(session, "printer.hold_resume", principal_kind="role", principal_id="staff")
    rights = resolve_resource_access(session, user)
    assert rights.can("printer", "p", "printer.swap_cartridges")
    assert rights.can("printer", "p", "printer.hold_resume")
    assert not rights.can("printer", "p", "printer.configure")
    assert not rights.can("printer", "p", "printer.emergency_stop")
    assert not rights.can("cartridge", "c", "cartridge.use")
    with pytest.raises(TypeError):
        rights.resources[("printer", "p")] = PRINTER_PERMISSIONS  # pyright: ignore[reportIndexIssue] -- verify runtime immutability


def test_location_inheritance_is_directional_and_namespaced(foundation_session):
    session = foundation_session
    user = seed(session)
    grant(session, "printer.start_own", "location", "home")
    grant(session, "cartridge.use", "location", "room")
    rights = resolve_resource_access(session, user)
    assert rights.can("printer", "p", "printer.start_own")
    assert rights.can("cartridge", "c", "cartridge.use")
    assert not rights.can("printer", "q", "printer.start_own")
    assert not rights.can("printer_group", "g", "printer.start_own")
    session.get(PrinterDevice, "p").location_id = "other"
    session.flush()
    assert not resolve_resource_access(session, user).can("printer", "p", "printer.start_own")
    assert resolve_resource_access(session, user).can("cartridge", "c", "cartridge.use")


def test_ownership_transfers_all_rights_without_leaking_to_other_resources(foundation_session):
    session = foundation_session
    user = seed(session)
    owner = session.get(User, "owner")
    rights = resolve_resource_access(session, owner)
    assert PRINTER_PERMISSIONS <= rights.resources[("printer", "p")]
    assert CARTRIDGE_PERMISSIONS <= rights.resources[("cartridge", "c")]
    assert rights.can("printer", "p", "printer.manage_user_access")
    assert not rights.can("printer", "q", "printer.view")
    assert not rights.has("audit.view_all")
    session.get(PrinterDevice, "p").owner_id = user.id
    session.flush()
    assert resolve_resource_access(session, user).can("printer", "p", "printer.transfer_ownership")
    assert not resolve_resource_access(session, owner).can("printer", "p", "printer.view")
    assert not resolve_resource_access(session, user).can("cartridge", "c", "cartridge.use")


def test_role_removal_recomputes_access_but_retains_direct_grant(foundation_session):
    session = foundation_session
    user = seed(session)
    grant(session, "printer.view", principal_kind="role", principal_id="staff")
    direct = grant(session, "printer.view")
    grant(session, "printer.start_own", principal_kind="role", principal_id="staff")
    user.role_ids = []
    session.flush()
    rights = resolve_resource_access(session, user)
    assert rights.can("printer", "p", "printer.view")
    assert not rights.can("printer", "p", "printer.start_own")
    session.delete(direct)
    session.flush()
    assert not resolve_resource_access(session, user).can("printer", "p", "printer.view")


def test_disabled_owner_or_administrator_has_no_access(foundation_session):
    session = foundation_session
    seed(session)
    for identifier in ("owner", "admin"):
        user = session.get(User, identifier)
        user.disabled = True
        session.flush()
        rights = resolve_resource_access(session, user)
        assert not rights.is_admin and not rights.resources and not rights.application
        assert not rights.has("audit.view_all")


def test_group_grants_never_authorize_member_hardware(foundation_session):
    session = foundation_session
    user = seed(session)
    role = session.get(Role, "staff")
    role.permissions = [{"kind": "destination", "destination_id": "g", "level": "full"}]
    session.flush()
    rights = resolve_resource_access(session, user)
    assert rights.resources[("printer_group", "g")] == GROUP_PERMISSIONS - {"printer.view_audit"}
    assert not rights.can("printer", "p", "printer.configure")
    assert not rights.can("printer_group", "g", "printer.swap_cartridges")
    with pytest.raises(ValueError, match="does not apply"):
        grant(session, "printer.emergency_stop", "printer_group", "g")


@pytest.mark.parametrize("level", ["none", "request", "print", "moderator", "full"])
def test_legacy_mapping_never_invents_audit_or_ownership_rights(level):
    rights = legacy_permissions(level)
    assert "printer.view_audit" not in rights
    assert "printer.manage_user_access" not in rights
    assert "printer.transfer_ownership" not in rights
    assert ("printer.hold_resume" in rights) == (level in {"moderator", "full"})
    assert ("printer.swap_cartridges" in rights) == (level == "full")


def test_legacy_levels_remain_available_without_consuming_new_grants(foundation_session):
    from app.auth import actor_for_user

    session = foundation_session
    user = seed(session)
    session.get(Role, "staff").permissions = [
        {"kind": "destination", "destination_id": "p", "level": "moderator"}
    ]
    grant(session, "printer.configure")
    rights = resolve_resource_access(session, user)
    assert rights.can("printer", "p", "printer.configure")
    assert rights.can("printer", "p", "printer.hold_resume")
    assert not rights.can("printer", "p", "printer.swap_cartridges")
    assert actor_for_user(session, user).destination_levels["p"] == "moderator"


def test_edit_all_is_not_universal_print_or_audit_access(foundation_session):
    session = foundation_session
    user = seed(session)
    session.get(Role, "staff").permissions = [
        {"kind": "application", "permission": "printers.edit_all"},
        {"kind": "application", "permission": "cartridges.edit_all"},
    ]
    session.flush()
    rights = resolve_resource_access(session, user)
    assert rights.can("printer", "p", "printer.transfer_ownership")
    assert rights.can("cartridge", "c", "cartridge.transfer_ownership")
    assert not rights.can("printer", "p", "printer.start_any")
    assert not rights.can("cartridge", "c", "cartridge.use")
    assert not rights.can("cartridge", "c", "cartridge.view_audit")


def test_invalid_location_paths_and_parent_changes_fail_closed(foundation_session):
    session = foundation_session
    user = seed(session)
    with pytest.raises(ValueError, match="cycle"):
        validate_location_parent(session, "home", "room")
    with pytest.raises(ValueError, match="exist"):
        validate_location_parent(session, "home", "missing")
    validate_location_parent(session, "room", "other")
    assert session.get(Location, "room").parent_id == "home"
    grant(session, "printer.view", "location", "home")
    # Simulate a corrupt import; resolver must not hang or partially inherit.
    session.get(Location, "home").parent_id = "room"
    session.flush()
    assert not resolve_resource_access(session, user).can("printer", "p", "printer.view")
    assert location_ancestors({"home": None, "room": "home"}, "room") == {"home", "room"}


@pytest.mark.parametrize(
    "permission,scope_kind,scope_id,principal_kind,principal_id",
    [
        ("cartridge.use", "printer", "p", "user", "staff-user"),
        ("printer.manage_user_access", "printer", "p", "user", "staff-user"),
        ("printer.view", "printer", "missing", "user", "staff-user"),
        ("printer.view", "printer", "p", "user", "missing"),
        ("printer.view", "printer", "p", "role", "missing"),
        ("invented", "location", "room", "user", "staff-user"),
    ],
)
def test_grant_validation_rejects_unknown_or_cross_namespace_references(
    foundation_session, permission, scope_kind, scope_id, principal_kind, principal_id
):
    seed(foundation_session)
    with pytest.raises(ValueError):
        grant(foundation_session, permission, scope_kind, scope_id, principal_kind, principal_id)


def test_database_prevents_self_parent_and_duplicate_grants(foundation_session):
    session = foundation_session
    seed(session)
    session.commit()
    session.get(Location, "home").parent_id = "home"
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()
    grant(session, "printer.view")
    session.commit()
    with pytest.raises(IntegrityError):
        grant(session, "printer.view")


def test_retired_printer_only_retains_history_access(foundation_session):
    session = foundation_session
    seed(session)
    session.get(PrinterDevice, "p").config = {"retired": True}
    session.flush()
    rights = resolve_resource_access(session, session.get(User, "owner"))
    assert rights.resources[("printer", "p")] == {"printer.view_audit", "printer.view_activity"}
