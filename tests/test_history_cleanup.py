"""Permanent duplicate cleanup must conserve queue state and real accounting."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import install, job, profile
from sqlalchemy import event, func, select, text
from test_access_security import accounts as account_fixture

from app.http import record
from app.models import (
    Batch,
    BatchItem,
    FlushRequest,
    LabelCopy,
    Notification,
    NotificationDelivery,
    NotificationEndpoint,
    Role,
    State,
    TapeAllocation,
)
from app.printer.base import PrintNotStarted
from app.usage import usage_report

accounts = account_fixture
PREVIEW = "/api/admin/history/duplicates"
PURGE = PREVIEW + "/purge"


def seed_duplicates(client, monkeypatch, count=3, *, manual=True):
    tape = profile(client, threshold=1)
    cartridge = install(client, tape["id"])
    client.put(f"/api/cartridges/{cartridge['id']}/price", json={"price_minor": 2000})
    queued = job(client, tape["id"], 2)
    if manual:
        assert client.post("/api/queue/print").status_code == 202
    worker = client.app.state.fleet.workers["main"]

    def reject(_):
        raise PrintNotStarted("Rejected before transmission")

    with monkeypatch.context() as patch:
        patch.setattr(worker.backend, "print_batch", reject)
        worker.tick()
    ids = []
    with client.app.state.factory.begin() as session:
        first = session.scalar(select(Batch))
        first.created_at, first.finished_at = 1000, 1001
        ids.append(first.id)
        batch_values = record(first)
        items = [record(item) for item in session.scalars(select(BatchItem))]
        allocations = [record(row) for row in session.scalars(select(TapeAllocation))]
        for index in range(1, count):
            identifier = f"duplicate-{index:04}"
            values = dict(batch_values)
            if not manual:
                values["trigger"] = {**values["trigger"], "at": 1000 + index * 2}
            session.add(
                Batch(
                    **{
                        **values,
                        "id": identifier,
                        "created_at": 1000 + index * 2,
                        "finished_at": 1001 + index * 2,
                    }
                )
            )
            session.flush()
            for item in items:
                session.add(BatchItem(**{**item, "batch_id": identifier}))
            for allocation in allocations:
                session.add(TapeAllocation(**{**allocation, "batch_id": identifier}))
            ids.append(identifier)
    return ids, queued


def counts(client):
    with client.app.state.factory() as session:
        return {
            model.__tablename__: session.scalar(select(func.count()).select_from(model))
            for model in (Batch, BatchItem, TapeAllocation, Notification, NotificationDelivery)
        }


@pytest.mark.parametrize("manual", [True, False])
def test_purge_removes_all_duplicates_and_usage_rows_beyond_the_first_page(
    client, monkeypatch, manual
):
    ids, queued = seed_duplicates(client, monkeypatch, count=137, manual=manual)
    with client.app.state.factory.begin() as session:
        session.add(
            NotificationEndpoint(
                id="endpoint",
                name="Test",
                url="https://example.test",
                topic="test",
                kinds=["batch_review"],
                enabled=False,
            )
        )
        session.flush()
        # Cover explicit context and legacy links; unrelated printer alerts stay.
        for index, identifier in enumerate(ids):
            notice = Notification(
                id=f"notice-{index}",
                title="Attempt",
                message="Failed",
                kind="batch_review",
                context={"batch_id": identifier} if index % 2 else {},
                path=f"/#/batches/{identifier}",
            )
            session.add(notice)
            session.flush()
            session.add(
                NotificationDelivery(
                    notification_id=notice.id,
                    endpoint_id="endpoint",
                    endpoint_revision=1,
                    endpoint_name="Test",
                )
            )
        before_usage = usage_report(session, None)
        before_copies = [record(row) for row in session.scalars(select(LabelCopy))]
        before_flushes = [record(row) for row in session.scalars(select(FlushRequest))]
    before_cartridges = client.get("/api/cartridges").json()
    before = counts(client)
    preview = client.get(PREVIEW).json()
    assert preview["batches"] == 136 and preview["items"] == 272
    assert preview["allocations"] == preview["notifications"] == preview["deliveries"] == 136
    assert len(preview["groups"]) == 1
    assert preview["groups"][0]["retained_batch_id"] == ids[0]
    assert counts(client) == before  # Preview is read-only.
    response = client.post(PURGE, json={"confirmation": preview["confirmation"]})
    assert response.status_code == 200, response.text
    assert counts(client) == {
        "batches": 1,
        "batch_items": 2,
        "tape_allocations": 1,
        "notifications": 2,
        "notification_deliveries": 1,
    }
    with client.app.state.factory() as session:
        after_usage = usage_report(session, None)
        assert after_usage["users"] == before_usage["users"]
        assert after_usage["accounts"] == before_usage["accounts"]
        assert [row["batch_id"] for row in after_usage["entries"]] == [ids[0]]
        assert [record(row) for row in session.scalars(select(LabelCopy))] == before_copies
        assert [record(row) for row in session.scalars(select(FlushRequest))] == before_flushes
        assert list(session.execute(text("PRAGMA foreign_key_check"))) == []
    assert client.get("/api/cartridges").json() == before_cartridges
    assert client.get(f"/api/jobs/{queued['id']}").json()["status"] == "queued"
    assert client.get(f"/api/batches/{ids[1]}").status_code == 404
    assert client.get(PREVIEW).json()["batches"] == 0


@pytest.mark.parametrize(
    "change",
    [
        "printed",
        "printing",
        "review",
        "reported",
        "consumed",
        "partial",
        "no_items",
        "pending_usage",
        "charged",
        "used_tape",
        "no_finish",
        "no_error",
    ],
)
def test_real_or_uncertain_usage_and_non_failed_output_are_never_purge_candidates(
    client, monkeypatch, change
):
    ids, _ = seed_duplicates(client, monkeypatch)
    with client.app.state.factory.begin() as session:
        # Mutate all attempts identically so that equality cannot bypass safety.
        for identifier in ids:
            batch = session.get(Batch, identifier)
            allocation = session.scalar(
                select(TapeAllocation).where(TapeAllocation.batch_id == identifier)
            )
            item = session.scalar(select(BatchItem).where(BatchItem.batch_id == identifier))
            if change in ("printed", "printing", "review"):
                batch.state = {
                    "printed": State.PRINTED,
                    "printing": State.PRINTING,
                    "review": State.NEEDS_REVIEW,
                }[change]
            elif change == "reported":
                batch.consumption_source, batch.consumed_mm = "reported", 0
            elif change == "consumed":
                batch.consumed_mm = 1
            elif change == "partial":
                item.outcome = State.PRINTED
            elif change == "no_items":
                for row in session.scalars(
                    select(BatchItem).where(BatchItem.batch_id == identifier)
                ):
                    session.delete(row)
            elif change == "pending_usage":
                allocation.consumed_mm = None
            elif change == "charged":
                allocation.cost_micros = "1"
            elif change == "used_tape":
                allocation.consumed_mm = 1
            elif change == "no_finish":
                batch.finished_at = None
            elif change == "no_error":
                batch.error = None
    before = counts(client)
    preview = client.get(PREVIEW).json()
    assert preview["batches"] == 0
    assert client.post(PURGE, json={"confirmation": preview["confirmation"]}).json()["batches"] == 0
    assert counts(client) == before


@pytest.mark.parametrize("change", ["request", "error", "printer", "copy", "attribution", "plan"])
def test_similar_but_distinct_attempts_remain(client, monkeypatch, change):
    ids, queued = seed_duplicates(client, monkeypatch)
    with client.app.state.factory.begin() as session:
        last = session.get(Batch, ids[-1])
        if change == "request":
            last.trigger = {**last.trigger, "flush_request_id": "another-request"}
        elif change == "error":
            last.error = "Another failure"
        elif change == "printer":
            last.printer_id = "another-printer"
        elif change == "plan":
            last.print_plan = {"changed": True}
        else:
            item = session.scalar(select(BatchItem).where(BatchItem.batch_id == last.id))
            if change == "copy":
                session.add(LabelCopy(id="another-copy", job_id=queued["id"], ordinal=2))
                session.flush()
                item.copy_id = "another-copy"
            else:
                item.attribution = {"requested_by": {"id": "other", "name": "Other"}}
    preview = client.get(PREVIEW).json()
    assert preview["batches"] == 1
    assert client.post(PURGE, json={"confirmation": preview["confirmation"]}).status_code == 200
    assert client.get(f"/api/batches/{ids[-1]}").status_code == 200


def test_legacy_render_failures_without_allocations_can_be_purged(client, monkeypatch):
    ids, _ = seed_duplicates(client, monkeypatch)
    with client.app.state.factory.begin() as session:
        for row in session.scalars(select(TapeAllocation)):
            session.delete(row)
        for batch in session.scalars(select(Batch)):
            batch.trigger, batch.print_plan, batch.estimated_mm = None, None, 0
    preview = client.get(PREVIEW).json()
    assert preview["batches"] == 2 and preview["allocations"] == 0
    assert client.post(PURGE, json={"confirmation": preview["confirmation"]}).status_code == 200
    assert client.get("/api/batches").json()[0]["id"] == ids[0]


def test_preview_must_match_current_history_and_requests_cannot_delete_twice(client, monkeypatch):
    ids, _ = seed_duplicates(client, monkeypatch)
    preview = client.get(PREVIEW).json()
    with client.app.state.factory.begin() as session:
        session.get(Batch, ids[-1]).error = "Changed"
    before = counts(client)
    assert client.post(PURGE, json={"confirmation": preview["confirmation"]}).status_code == 409
    assert counts(client) == before
    assert client.post(PURGE, json={}).status_code == 422
    preview = client.get(PREVIEW).json()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: (
                    client.post(PURGE, json={"confirmation": preview["confirmation"]}).status_code
                ),
                range(2),
            )
        )
    assert sorted(results) == [200, 409]
    assert counts(client)["batches"] == 2


def test_purge_is_admin_only_and_requires_csrf(accounts, monkeypatch):
    admin, alice, bob = accounts
    seed_duplicates(admin, monkeypatch)
    with admin.app.state.factory.begin() as session:
        session.get(Role, "alice-access").permissions = [
            {"kind": "destination", "destination_id": "main", "level": "full"},
            {"kind": "application", "permission": "usage.edit_accounts"},
        ]
    preview = admin.get(PREVIEW).json()
    for other in (alice, bob):
        assert other.get(PREVIEW).status_code == 403
        assert other.post(PURGE, json={"confirmation": preview["confirmation"]}).status_code == 403
    assert (
        admin.post(
            PURGE,
            json={"confirmation": preview["confirmation"]},
            headers={"X-CSRF-Token": "invalid"},
        ).status_code
        == 403
    )
    assert counts(admin)["batches"] == 3


def test_purge_preserves_later_successful_usage_and_balance(client, monkeypatch):
    ids, _ = seed_duplicates(client, monkeypatch)
    assert client.post("/api/queue/print").status_code == 202
    client.app.state.fleet.workers["main"].tick()
    before = client.get("/api/usage").json()
    assert before["users"][0]["consumed_mm"] > 0
    preview = client.get(PREVIEW).json()
    assert preview["batches"] == 2
    assert client.post(PURGE, json={"confirmation": preview["confirmation"]}).status_code == 200
    after = client.get("/api/usage").json()
    assert after["accounts"] == before["accounts"]
    assert after["users"] == before["users"]
    assert len(after["entries"]) == 2
    assert {row["state"] for row in after["entries"]} == {"failed", "printed"}
    assert ids[0] in {row["batch_id"] for row in after["entries"]}


def test_purge_rolls_back_dependent_deletes_on_failure(client, monkeypatch):
    seed_duplicates(client, monkeypatch)
    preview = client.get(PREVIEW).json()
    before = counts(client)
    engine = client.app.state.factory.kw["bind"]

    def fail_delete(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.startswith("DELETE FROM batches"):
            raise RuntimeError("Injected failure")

    event.listen(engine, "before_cursor_execute", fail_delete)
    try:
        with pytest.raises(RuntimeError, match="Injected failure"):
            client.post(PURGE, json={"confirmation": preview["confirmation"]})
    finally:
        event.remove(engine, "before_cursor_execute", fail_delete)
    assert counts(client) == before
