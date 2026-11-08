"""Location owners and explicit resource permission denials."""

import json

import sqlalchemy as sa
from alembic import op

revision = "131314a58ba1"
down_revision = "121313f47a90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("locations") as batch:
        batch.add_column(sa.Column("owner_id", sa.String(128), nullable=True))
        batch.create_index("ix_locations_owner_id", ["owner_id"])
    with op.batch_alter_table("resource_grants") as batch:
        batch.add_column(sa.Column("effect", sa.String(8), nullable=False, server_default="allow"))
        batch.create_check_constraint("ck_grant_effect", "effect IN ('allow', 'deny')")


def downgrade() -> None:
    for row in op.get_bind().execute(sa.text("SELECT permissions FROM roles")):
        permissions = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        if any(entry.get("denied_permissions") for entry in permissions):
            raise RuntimeError("Remove explicit permission denials before downgrading")
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM resource_grants WHERE effect = 'deny' LIMIT 1"))
        .first()
    ):
        raise RuntimeError("Remove explicit permission denials before downgrading")
    with op.batch_alter_table("resource_grants") as batch:
        batch.drop_constraint("ck_grant_effect", type_="check")
        batch.drop_column("effect")
    # Native DROP COLUMN avoids rebuilding a table referenced by inventory.
    op.drop_index("ix_locations_owner_id", table_name="locations")
    op.drop_column("locations", "owner_id")
