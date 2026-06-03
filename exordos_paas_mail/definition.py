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

import os

from exordos_metapaas.registry import PaaSDefinition
from exordos_paas_mail import routes


class MailDefinition(PaaSDefinition):
    """Mail-aaS as a metapaas plugin: control-plane API, dataplane
    (Postfix + Dovecot) and all the runtime wiring (builders, core-agent
    models, IAM perms) declared through the registry contract so the
    metapaas runtime hosts it generically.
    """

    slug = "mail"
    element_name = "mail-aas"

    def get_type_route(self):
        return routes.MailRoute

    def get_migrations_path(self):
        return os.path.join(os.path.dirname(__file__), "migrations")

    def get_builders(self, core_username, core_password, core_api_base_url, project_id):
        from exordos_paas_mail.infra_builder import CoreInfraBuilder
        from exordos_paas_mail.infra_models import MailInstance as InfraMailInstance
        from exordos_paas_mail.paas_builder import MailInstanceBuilder
        from exordos_paas_mail.paas_models import MailInstance as PaaSMailInstance

        return [
            CoreInfraBuilder(
                core_username=core_username,
                core_password=core_password,
                core_api_base_url=core_api_base_url,
                project_id=project_id,
                instance_model=InfraMailInstance,
            ),
            MailInstanceBuilder(instance_model=PaaSMailInstance),
        ]

    def get_agent_models(self):
        return {
            "versions": "exordos_paas_mail.models:MailVersion",
            "instances": "exordos_paas_mail.infra_models:MailInstance",
            "instances.accounts": "exordos_paas_mail.models:MailAccount",
        }

    def get_agent_filters(self):
        return {
            "versions": "description",
            "instances": "project_id",
            "instances.accounts": "project_id",
        }
