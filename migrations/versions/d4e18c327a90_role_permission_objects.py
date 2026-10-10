"""Direct role assignments, scoped permissions and independent template membership.

Revision ID: d4e18c327a90
Revises: b7d49210cf36
"""

import sqlalchemy as sa
from alembic import op

revision = "d4e18c327a90"
down_revision = "b7d49210cf36"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    meta = sa.MetaData()
    users = sa.Table("users", meta, autoload_with=connection)
    roles = sa.Table("roles", meta, autoload_with=connection)
    groups = sa.Table("user_groups", meta, autoload_with=connection)
    grants = sa.Table("printer_grants", meta, autoload_with=connection)
    old_roles = {row["id"]: row for row in connection.execute(roles.select()).mappings()}
    old_groups = list(connection.execute(groups.select()).mappings())
    old_grants = list(connection.execute(grants.select()).mappings())
    template_editors = set()
    for user in connection.execute(users.select()).mappings():
        group_ids = {group["id"] for group in old_groups if user["id"] in group["user_ids"]}
        role_ids = set(user["role_ids"])
        for group in old_groups:
            if group["id"] in group_ids:
                role_ids.update(group["role_ids"])
        old_permissions = {
            permission
            for identifier in role_ids
            if identifier in old_roles
            for permission in old_roles[identifier]["permissions"]
        }
        if user["is_admin"] or "templates.write" in old_permissions:
            template_editors.add(user["id"])
        destinations = {
            grant["printer_id"]
            for grant in old_grants
            if (grant["subject_type"] == "user" and grant["subject_id"] == user["id"])
            or (grant["subject_type"] == "group" and grant["subject_id"] in group_ids)
        }
        # The reserved role ID cannot turn an old ordinary role into an administrator.
        role_ids.discard("administrator")
        if user["is_admin"]:
            role_ids.add("administrator")
        elif destinations:
            level = (
                "print"
                if {"print.submit", "print.direct"} <= old_permissions
                else "request"
                if "print.submit" in old_permissions
                else "none"
            )
            migrated_id = "migrated-access-" + user["id"]
            connection.execute(
                roles.insert().values(
                    id=migrated_id,
                    name="Migrated access: " + user["username"],
                    permissions=[
                        {"kind": "destination", "destination_id": identifier, "level": level}
                        for identifier in sorted(destinations)
                    ],
                )
            )
            role_ids.add(migrated_id)
        connection.execute(
            users.update().where(users.c.id == user["id"]).values(role_ids=sorted(role_ids))
        )
    for identifier, role in old_roles.items():
        permissions = [
            {"kind": "application", "permission": item}
            for item in role["permissions"]
            if item in ("assets.write", "inventory.manage", "printers.manage")
        ]
        values = {"permissions": permissions}
        if role["name"] == "Administrator" and identifier != "administrator":
            values["name"] = "Administrator (legacy " + identifier + ")"
        connection.execute(roles.update().where(roles.c.id == identifier).values(**values))
    if "administrator" not in old_roles:
        connection.execute(
            roles.insert().values(id="administrator", name="Administrator", permissions=[])
        )
    op.add_column("roles", sa.Column("protected", sa.Boolean(), nullable=False, server_default="0"))
    op.execute(
        "UPDATE roles SET protected = 1, name = 'Administrator', permissions = '[]' WHERE id = 'administrator'"
    )
    op.add_column(
        "user_groups", sa.Column("members", sa.JSON(), nullable=False, server_default="[]")
    )
    new_groups = sa.Table("user_groups", sa.MetaData(), autoload_with=connection)
    for group in old_groups:
        connection.execute(
            new_groups.update()
            .where(new_groups.c.id == group["id"])
            .values(
                members=[
                    {
                        "user_id": identifier,
                        "can_create": identifier in template_editors,
                        "can_edit_others": identifier in template_editors,
                        "can_delete_others": identifier in template_editors,
                    }
                    for identifier in group["user_ids"]
                ]
            )
        )
    op.drop_column("user_groups", "role_ids")
    op.drop_column("user_groups", "user_ids")
    op.drop_column("users", "is_admin")
    op.drop_table("printer_grants")
    op.create_table(
        "access_change_confirmations",
        sa.Column("token_hash", sa.String(), primary_key=True),
        sa.Column("actor_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("state_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.Double(), nullable=False),
    )


def downgrade():
    connection = op.get_bind()
    op.drop_table("access_change_confirmations")
    op.add_column("users", sa.Column("is_admin", sa.Boolean(), nullable=False, server_default="0"))
    op.add_column(
        "user_groups", sa.Column("user_ids", sa.JSON(), nullable=False, server_default="[]")
    )
    op.add_column(
        "user_groups", sa.Column("role_ids", sa.JSON(), nullable=False, server_default="[]")
    )
    groups = sa.Table("user_groups", sa.MetaData(), autoload_with=connection)
    users = sa.Table("users", sa.MetaData(), autoload_with=connection)
    roles = sa.Table("roles", sa.MetaData(), autoload_with=connection)
    for group in connection.execute(groups.select()).mappings():
        connection.execute(
            groups.update()
            .where(groups.c.id == group["id"])
            .values(user_ids=[member["user_id"] for member in group["members"]])
        )
    for user in connection.execute(users.select()).mappings():
        connection.execute(
            users.update()
            .where(users.c.id == user["id"])
            .values(
                is_admin="administrator" in user["role_ids"],
                role_ids=[
                    identifier for identifier in user["role_ids"] if identifier != "administrator"
                ],
            )
        )
    for role in connection.execute(roles.select()).mappings():
        connection.execute(
            roles.update()
            .where(roles.c.id == role["id"])
            .values(
                permissions=[
                    item["permission"]
                    for item in role["permissions"]
                    if item["kind"] == "application"
                ]
            )
        )
    op.drop_column("user_groups", "members")
    op.drop_column("roles", "protected")
    op.create_table(
        "printer_grants",
        sa.Column("subject_type", sa.String(), primary_key=True),
        sa.Column("subject_id", sa.String(), primary_key=True),
        sa.Column("printer_id", sa.String(), sa.ForeignKey("printers.id"), primary_key=True),
    )
    # Scoped grants cannot safely become broad legacy grants; downgrade denies them.
