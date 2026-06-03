#    Copyright 2026 Genesis Corporation.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from restalchemy.storage.sql import migrations


class MigrationStep(migrations.AbstarctMigrationStep):
    def __init__(self):
        self._depends = []

    @property
    def migration_id(self):
        return "b2c3d4e5-f6a7-8901-bcde-f12345678901"

    @property
    def is_manual(self):
        return False

    def upgrade(self, session):
        expressions = [
            """\
CREATE TABLE mail_versions (
    uuid UUID PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    description TEXT,
    image TEXT,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);
""",
            """\
CREATE TABLE mail_instances (
    uuid UUID PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    project_id UUID NOT NULL,
    domain VARCHAR(255) NOT NULL,
    status VARCHAR(64) NOT NULL DEFAULT 'NEW',
    cpu INT NOT NULL CHECK (cpu BETWEEN 1 AND 128),
    ram INT NOT NULL CHECK (ram BETWEEN 512 AND 1073741824),
    disk_size INT NOT NULL CHECK (disk_size BETWEEN 8 AND 1073741824),
    root_password VARCHAR(256) NOT NULL,
    version UUID NOT NULL,
    "ipsv4" VARCHAR(15) ARRAY,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    FOREIGN KEY (version) REFERENCES mail_versions(uuid)
);

CREATE INDEX ON mail_instances(project_id, name);
""",
            """\
CREATE TABLE mail_accounts (
    uuid UUID PRIMARY KEY,
    name VARCHAR(255),
    description TEXT,
    project_id UUID NOT NULL,
    instance UUID NOT NULL,
    username VARCHAR(255) NOT NULL,
    password_hash VARCHAR(1024) NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    quota_mb INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    FOREIGN KEY (instance) REFERENCES mail_instances(uuid)
);

CREATE INDEX IF NOT EXISTS mail_accounts_project_id_idx
    ON mail_accounts (project_id);
CREATE UNIQUE INDEX IF NOT EXISTS mail_accounts_instance_username_idx
    ON mail_accounts (instance, username);
""",
        ]

        for expression in expressions:
            session.execute(expression)

    def downgrade(self, session):
        tables = [
            "mail_accounts",
            "mail_instances",
            "mail_versions",
        ]

        for table in tables:
            self._delete_table_if_exists(session, table)


migration_step = MigrationStep()
