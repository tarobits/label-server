"""Existing invitations retain their group selections through the additive migration."""

import time

from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, select

from app.db import make_engine


def test_existing_registration_code_survives_group_permissions_migration(tmp_path):
    url = f"sqlite:///{tmp_path / 'invitations.db'}"
    config = Config("alembic.ini")
    config.attributes["database_url"] = url
    command.upgrade(config, "b7e42a61d903")
    engine = make_engine(url)
    try:
        with engine.begin() as connection:
            codes = Table("registration_codes", MetaData(), autoload_with=connection)
            connection.execute(
                codes.insert().values(
                    id="legacy-code",
                    token_hash="hashed-secret",
                    name="Existing invitation",
                    role_ids=["member"],
                    group_ids=["existing-group"],
                    created_at=time.time(),
                    expires_at=time.time() + 86400,
                    revoked=False,
                )
            )
        command.upgrade(config, "head")
        with engine.connect() as connection:
            codes = Table("registration_codes", MetaData(), autoload_with=connection)
            code = connection.execute(select(codes)).mappings().one()
            assert code["group_ids"] == ["existing-group"]
            assert code["role_ids"] == ["member"]
            assert code["token_hash"] == "hashed-secret"
            assert code["redeemed_at"] is None
            assert code["group_permissions"] == {}
    finally:
        engine.dispose()


def test_template_creation_migration_preserves_member_defaults_and_custom_role_settings(tmp_path):
    url = f"sqlite:///{tmp_path / 'permissions.db'}"
    config = Config("alembic.ini")
    config.attributes["database_url"] = url
    command.upgrade(config, "f17a2c53b908")
    engine = make_engine(url)
    old_grants = [{"kind": "application", "permission": "assets.write"}]
    try:
        with engine.begin() as connection:
            roles = Table("roles", MetaData(), autoload_with=connection)
            connection.execute(
                roles.update().where(roles.c.id == "member").values(permissions=old_grants)
            )
            connection.execute(
                roles.insert().values(id="custom", name="Custom", permissions=[], protected=False)
            )
        command.upgrade(config, "head")
        with engine.connect() as connection:
            values = dict(connection.execute(select(roles.c.id, roles.c.permissions)).all())
            assert values["member"] == [
                {"kind": "application", "permission": "templates.create_personal"},
                {"kind": "application", "permission": "fonts.create_personal"},
                {"kind": "application", "permission": "images.create_personal"},
            ]
            assert values["custom"] == []
        command.downgrade(config, "f17a2c53b908")
        with engine.connect() as connection:
            assert (
                connection.scalar(select(roles.c.permissions).where(roles.c.id == "member"))
                == old_grants
            )
    finally:
        engine.dispose()
