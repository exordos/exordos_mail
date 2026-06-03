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

from gcl_iam import controllers as iam_controllers
from restalchemy.api import constants
from restalchemy.api import controllers as ra_controllers
from restalchemy.api import field_permissions as field_p
from restalchemy.api import resources as ra_resources

from exordos_paas_mail import models


class MailController(ra_controllers.RoutesListController):
    """Controller for /v1/types/mail/ endpoint"""

    __TARGET_PATH__ = "/v1/types/mail/"


class MailVersionController(
    iam_controllers.PolicyBasedWithoutProjectController,
    ra_controllers.BaseResourceControllerPaginated,
):
    __policy_service_name__ = "exordos_mail"
    __policy_name__ = "mail_version"

    __resource__ = ra_resources.ResourceByRAModel(
        model_class=models.MailVersion,
        convert_underscore=False,
        process_filters=True,
    )


class MailInstanceController(
    iam_controllers.PolicyBasedController,
    ra_controllers.BaseResourceControllerPaginated,
):
    __policy_service_name__ = "exordos_mail"
    __policy_name__ = "mail_instance"

    __resource__ = ra_resources.ResourceByRAModel(
        model_class=models.MailInstance,
        convert_underscore=False,
        process_filters=True,
        fields_permissions=field_p.FieldsPermissions(
            default=field_p.Permissions.RW,
            fields={
                "status": {constants.ALL: field_p.Permissions.RO},
                "ipsv4": {constants.ALL: field_p.Permissions.RO},
                "domain": {
                    constants.ALL: field_p.Permissions.RO,
                    constants.CREATE: field_p.Permissions.RW,
                },
            },
        ),
    )


class MailAccountController(
    iam_controllers.NestedPolicyBasedController,
    ra_controllers.BaseNestedResourceControllerPaginated,
):
    __policy_service_name__ = "exordos_mail"
    __policy_name__ = "account"
    __pr_name__ = "instance"

    __resource__ = ra_resources.ResourceByRAModel(
        model_class=models.MailAccount,
        convert_underscore=False,
        process_filters=True,
        fields_permissions=field_p.FieldsPermissions(
            default=field_p.Permissions.RW,
            fields={
                "username": {
                    constants.ALL: field_p.Permissions.RO,
                    constants.CREATE: field_p.Permissions.RW,
                },
                "password_hash": {
                    constants.ALL: field_p.Permissions.HIDDEN,
                    constants.CREATE: field_p.Permissions.RW,
                    constants.UPDATE: field_p.Permissions.RW,
                },
            },
        ),
    )
