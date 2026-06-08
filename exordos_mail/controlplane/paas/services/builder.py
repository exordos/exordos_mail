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
from restalchemy.storage import exceptions as storage_exceptions

from exordos_mail.controlplane.paas.dm import models

LOG = logging.getLogger(__name__)
AGENT_UUID5_NAME = "mailaas"


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

    def _build_paas_objects(
        self, instance: models.MailInstance
    ) -> tp.Collection[ua_models.TargetResourceKindAwareMixin]:
        try:
            nodeset = instance.get_actual_nodeset()
        except storage_exceptions.RecordNotFound:
            LOG.debug(
                "Nodeset for mail instance %s not ready yet, skipping", instance.uuid
            )
            return []

        nodes_by_idx = list(nodeset.nodes.keys())
        if not nodes_by_idx:
            return []

        accounts = self._get_accounts(instance)
        # Mail is always single-node
        node_uuid = sys_uuid.UUID(nodes_by_idx[0])
        return [
            models.MailInstanceNode(
                uuid=PaaSBuilder.agent_uuid_by_node(node_uuid),
                name=instance.name,
                domain=instance.domain,
                accounts=accounts,
                dkim_public_key=instance.dkim_public_key,
                dkim_selector=instance.dkim_selector,
            )
        ]

    def _sync_dkim_from_actuals(
        self,
        instance: models.MailInstance,
        paas_collection: builder.PaaSCollection,
    ) -> None:
        """Surface the DKIM public key discovered on the data plane.

        The configure script generates the key on the node; the DP agent
        reports it back on the actual ``mail_instance_node`` resource. Copy it
        onto the user-facing instance so it can be read via the API and
        published in DNS. The framework persists the instance afterwards.
        """
        for actual in paas_collection.actuals():
            if actual is None:
                continue
            pubkey = getattr(actual, "dkim_public_key", "") or ""
            selector = getattr(actual, "dkim_selector", "") or ""
            if pubkey and (
                instance.dkim_public_key != pubkey or instance.dkim_selector != selector
            ):
                instance.dkim_public_key = pubkey
                instance.dkim_selector = selector

    def create_paas_objects(
        self, instance: models.MailInstance
    ) -> tp.Collection[ua_models.TargetResourceKindAwareMixin]:
        return self._build_paas_objects(instance)

    def actualize_paas_objects(
        self,
        instance: models.MailInstance,
        paas_collection: builder.PaaSCollection,
    ) -> tp.Collection[ua_models.TargetResourceKindAwareMixin]:
        return self._build_paas_objects(instance)

    def actualize_paas_objects_source_data_plane(
        self,
        instance: models.MailInstance,
        paas_collection: builder.PaaSCollection,
    ) -> tp.Collection[ua_models.TargetResourceKindAwareMixin]:
        self._sync_dkim_from_actuals(instance, paas_collection)
        return self.actualize_paas_objects(instance, paas_collection)
