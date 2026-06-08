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
        self._depends = ["b2c3d4e5-f6a7-8901-bcde-f12345678901"]

    @property
    def migration_id(self):
        return "c3d4e5f6-a7b8-9012-cdef-123456789012"

    @property
    def is_manual(self):
        return False

    def upgrade(self, session):
        session.execute(
            "ALTER TABLE mail_instances DROP COLUMN IF EXISTS root_password;"
        )

    def downgrade(self, session):
        session.execute(
            "ALTER TABLE mail_instances ADD COLUMN IF NOT EXISTS "
            "root_password VARCHAR(256) NOT NULL DEFAULT '';"
        )


migration_step = MigrationStep()
