"""Independent group billing accounts, requests and immutable financial entries."""

from typing import TypedDict

import sqlalchemy as sa
from alembic import op

revision = "181819fa30f6"
down_revision = "171718e92fe5"
branch_labels = None
depends_on = None


# Match the referenced batches.id from the frozen MariaDB baseline, regardless
# of the database's default character set or collation.
class TableOptions(TypedDict):
    mysql_engine: str
    mysql_charset: str
    mysql_collate: str
    mariadb_engine: str
    mariadb_charset: str
    mariadb_collate: str


TABLE_OPTIONS: TableOptions = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_nopad_bin",
    "mariadb_engine": "InnoDB",
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_nopad_bin",
}


def upgrade() -> None:
    op.create_table(
        "billing_accounts",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.Double(), nullable=False),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "billing_grants",
        sa.Column(
            "account_id", sa.String(128), sa.ForeignKey("billing_accounts.id"), primary_key=True
        ),
        sa.Column("principal_kind", sa.String(16), primary_key=True),
        sa.Column("principal_id", sa.String(128), primary_key=True),
        sa.Column("permission", sa.String(64), primary_key=True),
        sa.Column("effect", sa.String(8), nullable=False),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "billing_requests",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column(
            "account_id", sa.String(128), sa.ForeignKey("billing_accounts.id"), nullable=False
        ),
        sa.Column("requester_id", sa.String(128), nullable=False),
        sa.Column("requester_name", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("source_id", sa.String(128), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.Double(), nullable=False),
        sa.Column("decided_at", sa.Double()),
        sa.Column("decided_by", sa.String(128)),
        sa.Column("reason", sa.String(500)),
        **TABLE_OPTIONS,
    )
    for column in ("account_id", "requester_id", "source_id"):
        op.create_index(f"ix_billing_requests_{column}", "billing_requests", [column])
    op.create_table(
        "billing_charges",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column(
            "account_id", sa.String(128), sa.ForeignKey("billing_accounts.id"), nullable=False
        ),
        sa.Column(
            "request_id", sa.String(128), sa.ForeignKey("billing_requests.id"), nullable=False
        ),
        sa.Column("batch_id", sa.String(128), sa.ForeignKey("batches.id"), nullable=False),
        sa.Column("requester_id", sa.String(128), nullable=False),
        sa.Column("requester_name", sa.String(100), nullable=False),
        sa.Column("recipient_id", sa.String(128)),
        sa.Column("recipient_name", sa.String(100)),
        sa.Column("cartridge_id", sa.String(128), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("amount_micros", sa.String(128), nullable=False),
        sa.Column("created_at", sa.Double(), nullable=False),
        sa.UniqueConstraint("request_id", "batch_id", "kind"),
        **TABLE_OPTIONS,
    )
    for column in ("account_id", "recipient_id"):
        op.create_index(f"ix_billing_charges_{column}", "billing_charges", [column])
    op.create_table(
        "billing_payments",
        sa.Column(
            "request_id", sa.String(128), sa.ForeignKey("billing_requests.id"), primary_key=True
        ),
        sa.Column(
            "charge_id", sa.String(128), sa.ForeignKey("billing_charges.id"), primary_key=True
        ),
        sa.Column("amount_micros", sa.String(128), nullable=False),
        sa.Column("confirmed_by", sa.String(128), nullable=False),
        sa.Column("confirmed_at", sa.Double(), nullable=False),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "billing_events",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column(
            "account_id", sa.String(128), sa.ForeignKey("billing_accounts.id"), nullable=False
        ),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("actor_name", sa.String(100), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.Double(), nullable=False),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_billing_events_account_id", "billing_events", ["account_id"])


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT 1 FROM billing_accounts LIMIT 1")).first():
        raise RuntimeError(
            "Group billing history exists; restore a coordinated backup to roll back"
        )
    for table in (
        "billing_events",
        "billing_payments",
        "billing_charges",
        "billing_requests",
        "billing_grants",
        "billing_accounts",
    ):
        op.drop_table(table)
