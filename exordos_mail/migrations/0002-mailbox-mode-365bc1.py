# SPDX-License-Identifier: Apache-2.0

from restalchemy.storage.sql import migrations


class MigrationStep(migrations.AbstractMigrationStep):
    def __init__(self):
        self._depends = ["0001-account-password-7d26b2.py"]

    @property
    def migration_id(self):
        return "365bc18b-e45a-4668-931a-eda3e158510d"

    @property
    def is_manual(self):
        return False

    def upgrade(self, session):
        session.execute(
            "ALTER TABLE mail_versions ADD COLUMN supports_mailbox BOOLEAN NOT NULL DEFAULT FALSE"
        )
        session.execute(
            "ALTER TABLE mail_instances ADD COLUMN mode TEXT NOT NULL DEFAULT 'smtp_only'"
        )
        session.execute(
            "ALTER TABLE mail_instances ADD COLUMN endpoints JSONB NOT NULL DEFAULT '{}'"
        )
        session.execute("""\
CREATE TABLE mail_mailboxes (
    uuid UUID PRIMARY KEY,
    instance UUID NOT NULL REFERENCES mail_instances(uuid),
    project_id UUID NOT NULL,
    local_part VARCHAR(64) NOT NULL,
    owner_user_uuid UUID NOT NULL,
    aliases VARCHAR(64) ARRAY NOT NULL DEFAULT '{}',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    address VARCHAR(319) NOT NULL,
    status VARCHAR(64) NOT NULL DEFAULT 'NEW',
    password VARCHAR(1024) CHECK (password IS NULL),
    password_hash VARCHAR(1024) NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    UNIQUE (instance, local_part)
)
""")

        session.execute("UPDATE mail_instances SET updated_at = now()")

    def downgrade(self, session):
        self._delete_table_if_exists(session, "mail_mailboxes")
        session.execute(
            "ALTER TABLE mail_instances DROP COLUMN endpoints, DROP COLUMN mode"
        )
        session.execute("ALTER TABLE mail_versions DROP COLUMN supports_mailbox")


migration_step = MigrationStep()
