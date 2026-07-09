#    Copyright 2026 Genesis Corporation.
#
#    All Rights Reserved.
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


class MigrationStep(migrations.AbstractMigrationStep):
    def __init__(self):
        self._depends = ["0000-init-mail.py"]

    @property
    def migration_id(self):
        return "7d26b20c-e291-478d-9d40-8ab0bb525ca5"

    @property
    def is_manual(self):
        return False

    def upgrade(self, session):
        expressions = [
            # Plaintext password: what the EM target (manifest) is reconciled
            # against, so an unchanged re-apply is a no-op instead of a loop.
            "ALTER TABLE mail_accounts ADD COLUMN password VARCHAR(1024);",
            # Backfill existing rows with the current crypt hash so the data
            # plane is undisturbed; the next EM re-apply replaces it with the
            # manifest plaintext and re-derives the hash once.
            "UPDATE mail_accounts SET password = password_hash "
            "WHERE password IS NULL;",
            "ALTER TABLE mail_accounts ALTER COLUMN password SET NOT NULL;",
            # password_hash is now derived, not user-supplied.
            "ALTER TABLE mail_accounts ALTER COLUMN password_hash DROP NOT NULL;",
        ]

        for expression in expressions:
            session.execute(expression)

    def downgrade(self, session):
        session.execute(
            "ALTER TABLE mail_accounts DROP COLUMN IF EXISTS password;"
        )


migration_step = MigrationStep()
