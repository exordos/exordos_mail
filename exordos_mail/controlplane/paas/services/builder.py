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

import logging
import typing as tp
import uuid as sys_uuid

from gcl_sdk.agents.universal.dm import models as ua_models
from gcl_sdk.paas.services import builder

from exordos_mail.controlplane.paas.dm import models

LOG = logging.getLogger(__name__)
AGENT_UUID5_NAME = "mail-aas"


class PaaSBuilder(builder.PaaSBuilder):
    @classmethod
    def agent_uuid_by_node(cls, node_uuid: sys_uuid.UUID) -> sys_uuid.UUID:
        return sys_uuid.uuid5(node_uuid, AGENT_UUID5_NAME)

    def schedule_paas_objects(
        self,
        instance: ua_models.InstanceWithDerivativesMixin,
        paas_objects: tp.Collection[ua_models.TargetResourceKindAwareMixin],
    ) -> dict[sys_uuid.UUID, tp.Collection[ua_models.TargetResourceKindAwareMixin]]:
        scheduled = {}
        for entity in paas_objects:
            scheduled[entity.uuid] = [entity]
        return scheduled


class MailInstanceBuilder(PaaSBuilder):
    def __init__(
        self,
        instance_model: tp.Type[models.MailInstance] = models.MailInstance,
    ):
        super().__init__(instance_model)

    def _get_accounts(self, instance):
        result = {}
        for account in instance.get_accounts():
            result[account.username] = {
                "password_hash": account.password_hash,
                "active": account.active,
            }
        return result

    def create_paas_objects(
        self, instance: models.MailInstance
    ) -> tp.Collection[ua_models.TargetResourceKindAwareMixin]:
        return self.actualize_paas_objects(
            instance, builder.PaaSCollection(paas_objects=tuple())
        )

    def actualize_paas_objects(
        self,
        instance: models.MailInstance,
        paas_collection: builder.PaaSCollection,
    ) -> tp.Collection[ua_models.TargetResourceKindAwareMixin]:
        accounts = self._get_accounts(instance)

        nodeset = instance.get_actual_nodeset()
        nodes_by_idx = list(nodeset.nodes.keys())

        # Mail is always single-node
        node_uuid = sys_uuid.UUID(nodes_by_idx[0])
        return [
            models.MailInstanceNode(
                uuid=PaaSBuilder.agent_uuid_by_node(node_uuid),
                name=instance.name,
                domain=instance.domain,
                accounts=accounts,
            )
        ]
