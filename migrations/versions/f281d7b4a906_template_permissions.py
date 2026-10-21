"""Preserve the Member role's personal template creation permission."""

import sqlalchemy as sa
from alembic import op

revision = "f281d7b4a906"
down_revision = "f17a2c53b908"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    roles = sa.table("roles", sa.column("id", sa.String()), sa.column("permissions", sa.JSON()))
    permissions = connection.scalar(sa.select(roles.c.permissions).where(roles.c.id == "member"))
    grant = {"kind": "application", "permission": "templates.create_personal"}
    if permissions is not None and grant not in permissions:
        connection.execute(
            roles.update().where(roles.c.id == "member").values(permissions=[*permissions, grant])
        )


def downgrade() -> None:
    connection = op.get_bind()
    roles = sa.table("roles", sa.column("id", sa.String()), sa.column("permissions", sa.JSON()))
    new_permissions = {
        "templates.create_personal",
        "templates.create_global",
        "templates.edit_global",
        "templates.delete_global",
    }
    for role in connection.execute(sa.select(roles)).mappings():
        permissions = [
            grant
            for grant in role["permissions"]
            if not (
                grant.get("kind") == "application" and grant.get("permission") in new_permissions
            )
        ]
        connection.execute(
            roles.update().where(roles.c.id == role["id"]).values(permissions=permissions)
        )
