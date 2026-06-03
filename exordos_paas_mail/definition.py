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
from exordos_paas_mail import permissions
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

    def get_builders(self):
        return [
            {
                "service": "exordos_paas_mail.infra_builder:CoreInfraBuilder",
                "core_creds": True,
            },
            {
                "service": "exordos_paas_mail.paas_builder:MailInstanceBuilder",
                "core_creds": False,
            },
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

    def get_iam_permissions(self):
        return list(permissions.PERMS_OWNER)
