import json

import pytest
from assertions import require_value
from sqlalchemy import func, select

from app.audit.audit import (
    AuditField,
    AuditFilters,
    AuditRequirement,
    AuditScope,
    append_audit,
    audit_page,
    project_audit,
)
from app.authn.resource_access import ResourceAccess, resolve_resource_access
from app.models import AuditEvent, Location, PrinterDevice, ResourceGrant, User


def access(*, admin=False, application=(), resources=None):
    return ResourceAccess("reader", admin, frozenset(application), resources or {})


def printer_access(identifier="p"):
    return access(resources={("printer", identifier): {"printer.view_audit"}})


def write_swap(session, identifier="event", occurred_at=10, *, extra_fields=None, **overrides):
    fields = {
        "actor_id": AuditField("operator", ()),
        "actor_name": AuditField("Operator", ()),
        "victim_ids": AuditField(
            ["requester"], (AuditRequirement("application", "", "usage.view_others"),)
        ),
        "old_cartridge_id": AuditField(
            "private-old-cartridge",
            (AuditRequirement("cartridge", "private-old-cartridge", "cartridge.view"),),
        ),
        "new_cartridge_id": AuditField(
            "private-new-cartridge",
            (AuditRequirement("cartridge", "private-new-cartridge", "cartridge.view"),),
        ),
    }
    fields.update(overrides)
    fields.update(extra_fields or {})
    return append_audit(
        session,
        event_id=identifier,
        action="cartridge.swapped",
        outcome="succeeded",
        occurred_at=occurred_at,
        scopes=(AuditScope("printer", "p"), AuditScope("cartridge", "private-new-cartridge")),
        fields=fields,
    )


def test_scoped_projection_does_not_serialize_private_values_or_requirements(foundation_session):
    entry = write_swap(foundation_session)
    projection = project_audit(entry, printer_access())
    assert projection is not None
    assert projection["fields"] == {"actor_id": "operator", "actor_name": "Operator"}
    assert projection["printers"] == ["p"]
    assert projection["cartridges"] == []
    serialized = json.dumps(projection)
    assert "private-" not in serialized
    assert "requester" not in serialized
    assert "requires" not in serialized
    assert project_audit(entry, printer_access("another")) is None


def test_global_audit_permission_does_not_grant_accounting_or_cartridge_content(foundation_session):
    entry = write_swap(foundation_session)
    global_reader = access(application={"audit.view_all"})
    projection = project_audit(entry, global_reader)
    assert projection is not None
    assert projection["cartridges"] == ["private-new-cartridge"]
    assert "victim_ids" not in projection["fields"]
    assert "old_cartridge_id" not in projection["fields"]
    assert global_reader.can("printer", "p", "printer.view_audit")
    assert not global_reader.can("printer", "p", "printer.configure")
    privileged = access(application={"audit.view_all", "usage.view_others"})
    assert require_value(project_audit(entry, privileged))["fields"]["victim_ids"] == ["requester"]


def test_global_events_require_global_audit_access(foundation_session):
    session = foundation_session
    entry = append_audit(
        session,
        event_id="global",
        action="permission.changed",
        outcome="succeeded",
        occurred_at=20,
        scopes=(AuditScope("global"),),
        fields={
            "new_permissions": AuditField(
                ["audit.view_all"], (AuditRequirement("application", "", "audit.view_all"),)
            )
        },
    )
    assert project_audit(entry, printer_access()) is None
    assert require_value(project_audit(entry, access(application={"audit.view_all"})))[
        "fields"
    ] == {"new_permissions": ["audit.view_all"]}


def test_every_requirement_must_hold_for_sensitive_change_details(foundation_session):
    entry = append_audit(
        foundation_session,
        event_id="price",
        action="cartridge.price_changed",
        outcome="succeeded",
        occurred_at=20,
        scopes=(AuditScope("printer", "p"),),
        fields={
            "new_price_minor": AuditField(
                1200,
                (
                    AuditRequirement("application", "", "usage.view_others"),
                    AuditRequirement("cartridge", "c", "cartridge.view_audit"),
                ),
            )
        },
    )
    partial = access(
        application={"usage.view_others"},
        resources={
            ("printer", "p"): {"printer.view_audit"},
        },
    )
    assert "new_price_minor" not in require_value(project_audit(entry, partial))["fields"]
    complete = access(application={"usage.view_others", "audit.view_all"})
    assert require_value(project_audit(entry, complete))["fields"]["new_price_minor"] == 1200
    assert (
        require_value(project_audit(entry, access(admin=True)))["fields"]["new_price_minor"] == 1200
    )


@pytest.mark.parametrize(
    "filters",
    [
        AuditFilters(search="private-old-cartridge"),
        AuditFilters(search="private-new-cartridge"),
        AuditFilters(cartridge="private-new-cartridge"),
        AuditFilters(victim="requester"),
    ],
)
def test_hidden_fields_cannot_match_search_filters_or_counts(foundation_session, filters):
    write_swap(foundation_session)
    assert audit_page(foundation_session, printer_access(), filters=filters)["total"] == 0


def test_hidden_actor_cannot_be_discovered_by_filter(foundation_session):
    write_swap(
        foundation_session,
        actor_id=AuditField(
            "hidden-actor", (AuditRequirement("application", "", "usage.view_others"),)
        ),
    )
    assert (
        audit_page(
            foundation_session, printer_access(), filters=AuditFilters(actor="hidden-actor")
        )["total"]
        == 0
    )


def test_filters_and_totals_run_before_pagination(foundation_session):
    session = foundation_session
    for index in range(5):
        write_swap(session, f"event-{index}", occurred_at=index)
    append_audit(
        session,
        event_id="hidden",
        action="audit.viewed",
        outcome="succeeded",
        occurred_at=100,
        scopes=(AuditScope("global"),),
        fields={},
    )
    page = audit_page(
        session,
        printer_access(),
        offset=1,
        limit=2,
        filters=AuditFilters(
            printer="p",
            actor="operator",
            action="cartridge.swapped",
            search="Operator",
        ),
    )
    assert page["total"] == 5
    assert [item["id"] for item in page["items"]] == ["event-3", "event-2"]
    assert audit_page(session, access())["total"] == 0


def test_idempotency_rejects_changed_evidence_and_detaches_mutable_values(foundation_session):
    session = foundation_session
    victims = ["requester"]
    original = write_swap(session, victim_ids=AuditField(victims, ()))
    victims.append("not-recorded")
    replay = write_swap(session, victim_ids=AuditField(["requester"], ()))
    assert replay is original
    assert session.scalar(select(func.count()).select_from(AuditEvent)) == 1
    assert original.fields["victim_ids"]["value"] == ["requester"]
    with pytest.raises(ValueError, match="different evidence"):
        write_swap(session, occurred_at=11)


def test_evidence_commits_and_rolls_back_with_the_domain_mutation(foundation_session):
    session = foundation_session
    session.add(Location(id="room", name="Original"))
    session.commit()
    session.get(Location, "room").name = "Changed"
    write_swap(session)
    session.rollback()
    assert session.get(Location, "room").name == "Original"
    assert session.get(AuditEvent, "event") is None
    session.get(Location, "room").name = "Committed"
    write_swap(session)
    session.commit()
    assert session.get(Location, "room").name == "Committed"
    assert session.get(AuditEvent, "event") is not None


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_evidence_cannot_be_changed_through_orm(foundation_session, operation):
    session = foundation_session
    entry = write_swap(session)
    session.commit()
    if operation == "update":
        entry.outcome = "failed"
    else:
        session.delete(entry)
    with pytest.raises(ValueError, match="cannot be edited"):
        session.flush()


@pytest.mark.parametrize(
    "key,value",
    [
        ("password", "never-store"),
        ("pin", "never-store"),
        ("api_key", "never-store"),
        ("settings", {"token": "never-store"}),
        ("new_cartridge_id", {"token": "never-store"}),
    ],
)
def test_unclassified_fields_and_nested_payloads_are_rejected(foundation_session, key, value):
    with pytest.raises(ValueError, match="Unclassified or invalid"):
        write_swap(foundation_session, extra_fields={key: AuditField(value, ())})
    assert foundation_session.scalar(select(func.count()).select_from(AuditEvent)) == 0


def test_change_fields_cannot_omit_permissions(foundation_session):
    with pytest.raises(ValueError, match="explicit permission"):
        write_swap(foundation_session, new_cartridge_id=AuditField("private", ()))


@pytest.mark.parametrize(
    "field",
    [
        {"value": "hidden", "requires": []},
        {"value": "hidden"},
        {
            "value": "hidden",
            "requires": [{"kind": "application", "id": "", "permission": "unknown"}],
        },
        {
            "value": "hidden",
            "requires": [{"kind": "printer", "id": [], "permission": "printer.view"}],
        },
        {"value": {"secret": "hidden"}, "requires": []},
    ],
)
def test_malformed_imported_fields_fail_closed_even_for_admin(field):
    value = AuditEvent(
        id="imported",
        action="cartridge.swapped",
        outcome="succeeded",
        occurred_at=1,
        recorded_at=2,
        scopes=[{"kind": "printer", "id": "p"}],
        fields={"new_cartridge_id": field, "unclassified": {"value": "hidden", "requires": []}},
    )
    projection = project_audit(value, access(admin=True))
    assert projection is not None
    assert projection["fields"] == {}
    assert "hidden" not in json.dumps(projection)


def test_revocation_and_owner_transfer_affect_next_projection_without_changing_evidence(
    foundation_session,
):
    session = foundation_session
    user = User(id="reader", username="reader", password_hash="unused", role_ids=[])
    session.add(user)
    session.flush()
    session.add(PrinterDevice(id="p", name="Printer", driver="mock", config={}, owner_id=user.id))
    session.flush()
    write_swap(session)
    assert audit_page(session, resolve_resource_access(session, user))["total"] == 1
    session.get(PrinterDevice, "p").owner_id = None
    session.flush()
    assert audit_page(session, resolve_resource_access(session, user))["total"] == 0
    grant = ResourceGrant(
        principal_kind="user",
        principal_id=user.id,
        scope_kind="printer",
        scope_id="p",
        permission="printer.view_audit",
    )
    session.add(grant)
    session.flush()
    assert audit_page(session, resolve_resource_access(session, user))["total"] == 1
    session.delete(grant)
    session.flush()
    assert audit_page(session, resolve_resource_access(session, user))["total"] == 0
    assert session.scalar(select(func.count()).select_from(AuditEvent)) == 1


@pytest.mark.parametrize("outcome", ["denied", "failed"])
def test_unsuccessful_actions_keep_their_actual_outcome(foundation_session, outcome):
    entry = append_audit(
        foundation_session,
        event_id="attempt",
        action="audit.viewed",
        outcome=outcome,
        occurred_at=1,
        scopes=(AuditScope("global"),),
        fields={},
    )
    assert require_value(project_audit(entry, access(admin=True)))["outcome"] == outcome
