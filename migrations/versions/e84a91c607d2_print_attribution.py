"""Persist requester, authorization and batch-start snapshots.

Revision ID: e84a91c607d2
Revises: c9e4136a7052
"""

import copy

import sqlalchemy as sa
from alembic import op

revision = "e84a91c607d2"
down_revision = "c9e4136a7052"
branch_labels = None
depends_on = None


def unknown():
    return {
        "requested_by": None,
        "requested_at": None,
        "authorization": {
            "kind": "unknown",
            "actor": None,
            "at": None,
            "request_id": None,
        },
        "release": None,
    }


def upgrade():
    for table, column in (
        ("print_jobs", "attribution"),
        ("print_requests", "requested_by"),
        ("flush_requests", "started_by"),
        ("batches", "trigger"),
        ("batch_items", "attribution"),
        ("job_access_holds", "resolved_by_snapshot"),
    ):
        op.add_column(table, sa.Column(column, sa.JSON(), nullable=True))
    connection = op.get_bind()
    meta = sa.MetaData()
    tables = {
        name: sa.Table(name, meta, autoload_with=connection)
        for name in (
            "users",
            "print_requests",
            "print_jobs",
            "job_access_holds",
            "batches",
            "batch_items",
            "label_copies",
        )
    }
    users = {row["id"]: row for row in connection.execute(tables["users"].select()).mappings()}

    def person(identifier, at):
        user = users.get(identifier)
        # Legacy local-owner IDs were assigned before authentication existed.
        # The eventual bootstrap administrator did not necessarily request that work.
        if user is None or at is None or user["created_at"] > at:
            return None
        return {"id": identifier, "name": user["username"]}

    approvals = {}
    for value in connection.execute(tables["print_requests"].select()).mappings():
        requester = person(value["owner_id"], value["created_at"])
        connection.execute(
            tables["print_requests"]
            .update()
            .where(tables["print_requests"].c.id == value["id"])
            .values(requested_by=requester)
        )
        if value["status"] == "approved" and value["decided_at"] is not None:
            for job_id in value["job_ids"]:
                approvals[job_id] = {
                    "requested_by": requester,
                    "requested_at": value["created_at"],
                    "authorization": {
                        "kind": "approval",
                        "actor": person(value["decided_by"], value["decided_at"]),
                        "at": value["decided_at"],
                        "request_id": value["id"],
                    },
                    "release": None,
                }
    jobs = {}
    for job in connection.execute(tables["print_jobs"].select()).mappings():
        attribution = approvals.get(job["id"])
        if attribution is None:
            attribution = unknown()
            # A CSV draft may have been submitted by an administrator other than
            # its owner. No legacy record identifies that direct submitter.
            attribution["requested_by"] = (
                person(job["owner_id"], job["created_at"]) if job["run_id"] is None else None
            )
            attribution["requested_at"] = job["created_at"]
            # Ownership proves no historical direct submitter/authorizer identity.
        jobs[job["id"]] = attribution
        connection.execute(
            tables["print_jobs"]
            .update()
            .where(tables["print_jobs"].c.id == job["id"])
            .values(attribution=attribution)
        )
    releases = {}
    for hold in connection.execute(tables["job_access_holds"].select()).mappings():
        actor = person(hold["resolved_by"], hold["resolved_at"])
        connection.execute(
            tables["job_access_holds"]
            .update()
            .where(tables["job_access_holds"].c.job_id == hold["job_id"])
            .values(resolved_by_snapshot=actor)
        )
        if hold["status"] == "released" and hold["resolved_at"] is not None:
            releases[hold["job_id"]] = {"actor": actor, "at": hold["resolved_at"]}
    copies = {
        row["id"]: row["job_id"]
        for row in connection.execute(tables["label_copies"].select()).mappings()
    }
    batches = {row["id"]: row for row in connection.execute(tables["batches"].select()).mappings()}
    for item in connection.execute(tables["batch_items"].select()).mappings():
        job_id = copies[item["copy_id"]]
        attribution = copy.deepcopy(jobs.get(job_id, unknown()))
        release = releases.get(job_id)
        if release and release["at"] <= batches[item["batch_id"]]["created_at"]:
            attribution["release"] = release
        connection.execute(
            tables["batch_items"]
            .update()
            .where(
                tables["batch_items"].c.batch_id == item["batch_id"],
                tables["batch_items"].c.copy_id == item["copy_id"],
            )
            .values(attribution=attribution)
        )
    # No old batch-to-flush link existed. Missing trigger snapshots deliberately
    # remain unknown; assigning automatic here would invent historical facts.


def downgrade():
    for table, column in (
        ("batch_items", "attribution"),
        ("batches", "trigger"),
        ("flush_requests", "started_by"),
        ("job_access_holds", "resolved_by_snapshot"),
        ("print_requests", "requested_by"),
        ("print_jobs", "attribution"),
    ):
        op.drop_column(table, column)
