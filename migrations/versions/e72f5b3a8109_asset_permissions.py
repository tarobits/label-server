"""Give fonts and images independent permissions without broadening sharing."""

import sqlalchemy as sa
from alembic import op

revision = "e72f5b3a8109"
down_revision = "d91e6a27b430"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    roles = sa.table("roles", sa.column("id", sa.String()), sa.column("permissions", sa.JSON()))
    for role in connection.execute(sa.select(roles)).mappings():
        grants = role["permissions"]
        old = {"kind": "application", "permission": "assets.write"}
        if old in grants:
            grants = [grant for grant in grants if grant != old]
            for kind in ("fonts", "images"):
                new = {"kind": "application", "permission": f"{kind}.create_personal"}
                if new not in grants:
                    grants.append(new)
            connection.execute(
                roles.update().where(roles.c.id == role["id"]).values(permissions=grants)
            )


def downgrade() -> None:
    connection = op.get_bind()
    roles = sa.table("roles", sa.column("id", sa.String()), sa.column("permissions", sa.JSON()))
    for role in connection.execute(sa.select(roles)).mappings():
        grants = role["permissions"]
        # The old combined grant cannot represent only one library's access.
        personal = {
            grant.get("permission") for grant in grants if grant.get("kind") == "application"
        }
        remaining = [
            grant
            for grant in grants
            if not (
                grant.get("kind") == "application"
                and grant.get("permission", "").startswith(("images.", "fonts."))
            )
        ]
        if {"images.create_personal", "fonts.create_personal"}.issubset(personal):
            remaining.append({"kind": "application", "permission": "assets.write"})
        connection.execute(
            roles.update().where(roles.c.id == role["id"]).values(permissions=remaining)
        )
