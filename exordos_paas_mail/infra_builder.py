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

from gcl_looper.services.oslo import base as oslo_base
from gcl_sdk.agents.universal.dm import models as ua_models
from gcl_sdk.agents.universal.drivers import core as core_drivers
from gcl_sdk.common.oslo import types as sdk_cfg_types
from gcl_sdk.infra import constants as sdk_c
from gcl_sdk.infra.dm import models as sdk_models
from gcl_sdk.infra.services import builder
from oslo_config import cfg
from restalchemy.dm import filters as dm_filters

from exordos_paas_mail import infra_models as models

LOG = logging.getLogger(__name__)
NODE_KIND = sdk_models.Node.get_resource_kind()
NODE_SET_KIND = sdk_models.NodeSet.get_resource_kind()
CONFIG_KIND = sdk_models.Config.get_resource_kind()


MAIL_CONF_TEMPLATE = """\
# Mail node environment configuration
# Managed by Exordos mail control plane — do not edit manually
MAIL_DOMAIN={domain}
"""


class CoreInfraBuilder(builder.CoreInfraBuilder, oslo_base.OsloConfigurableService):
    def __init__(
        self,
        core_username,
        core_password,
        core_api_base_url,
        project_id: sys_uuid.UUID,
        instance_model: tp.Type[models.MailInstance] = models.MailInstance,
    ):
        super().__init__(instance_model)
        self._project_id = project_id
        self.core_driver = core_drivers.RestCoreCapabilityDriver(
            username=core_username,
            password=core_password,
            user_api_base_url=core_api_base_url,
            project_id=self._project_id,
            use_project_scope=True,
            node_set="/v1/compute/sets/",
            config="/v1/config/configs/",
        )
        self._cclient = self.core_driver._client._client

    @classmethod
    def svc_get_config_opts(cls) -> tp.Collection[cfg.Opt]:
        return [
            cfg.StrOpt(
                "core_username",
                default="exordos_mail",
                help=("User to work with Core."),
            ),
            cfg.StrOpt(
                "core_password",
                default="exordos_mail",
                help=("User password to work with Core."),
            ),
            cfg.StrOpt(
                "core_api_base_url",
                default="http://core.local.genesis-core.tech:11010",
                help=("Core's user api endpoint."),
            ),
            sdk_cfg_types.UuidOpt(
                "project_id",
                help=("Project id to work with Core."),
            ),
        ]

    def create_infra(
        self, instance: models.MailInstance
    ) -> tp.Collection[ua_models.TargetResourceKindAwareMixin]:
        return instance.get_infra(self._project_id)

    def actualize_infra(
        self,
        instance: models.MailInstance,
        infra: builder.InfraCollection,
    ) -> tp.Collection[ua_models.TargetResourceKindAwareMixin]:
        nodeset = None
        configs = []

        for target, actual in infra.infra_objects:
            if target.get_resource_kind() == NODE_SET_KIND:
                nodeset = actual
            elif actual.get_resource_kind() == CONFIG_KIND:
                configs.append(actual)

        if nodeset.nodes:
            instance.ipsv4 = [node["ipv4"] for node in nodeset.nodes.values()]

        new_objects = []

        # Retrieve private keys for nodes
        node_keys = self._cclient.do_action(
            "/v1/compute/sets/", "get_private_keys", nodeset.uuid
        )
        for u, v in node_keys.items():
            if nkey := ua_models.NodeEncryptionKey.objects.get_one_or_none(
                filters={"uuid": dm_filters.EQ(u)}
            ):
                nkey.private_key = v
                nkey.update()
            else:
                nkey = ua_models.NodeEncryptionKey(uuid=sys_uuid.UUID(u), private_key=v)
                nkey.insert()

        # Mail is single-node; generate config for the one node
        for node_uuid_str, node in nodeset.nodes.items():
            content = MAIL_CONF_TEMPLATE.format(
                domain=instance.domain,
            )
            config = instance._create_config(
                sys_uuid.UUID(node_uuid_str), self._project_id, content
            )
            new_objects.append(config)

        tgt_nodeset = None

        for target, _ in infra.infra_objects:
            if target.get_resource_kind() == CONFIG_KIND:
                continue
            elif target.get_resource_kind() == NODE_SET_KIND:
                target.cores = instance.cpu
                target.ram = instance.ram
                target.disk_spec = sdk_models.SetDisksSpec(
                    disks=[
                        {
                            "size": models.ROOT_DISK_SIZE,
                            "image": instance.version.image,
                            "label": "root",
                        },
                        {
                            "size": instance.disk_size,
                            "label": "data",
                        },
                    ]
                )
                target.replicas = 1
                tgt_nodeset = target
            else:
                LOG.warning(
                    "%s kind is not supported here, ignoring...",
                    target.get_resource_kind(),
                )

        try:
            instance.status = sdk_c.InstanceStatus(nodeset.status).value
        except ValueError:
            instance.status = sdk_c.InstanceStatus.IN_PROGRESS.value

        return (tgt_nodeset, *new_objects)

    def pre_delete_instance_resource(self, resource):
        target_resources = ua_models.TargetResource.objects.get_all(
            filters={
                "master": dm_filters.EQ(resource.uuid),
                "kind": dm_filters.EQ(NODE_SET_KIND),
            },
        )
        actual_resources = ua_models.Resource.objects.get_all(
            filters={
                "uuid": dm_filters.In(r.uuid for r in target_resources),
                "kind": dm_filters.EQ(NODE_SET_KIND),
            },
        )

        for ns in actual_resources:
            for key in ua_models.NodeEncryptionKey.objects.get_all(
                filters={"uuid": dm_filters.In(ns.value["nodes"].keys())}
            ):
                key.delete()
