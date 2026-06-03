"""REST API controllers for mail PaaS instances."""

from __future__ import annotations

from restalchemy.framework import BaseController, CRUD
from exordos_paas_mail.models import MailInstance
from exordos_paas_mail.iam_config import IAM_MAIL, IAM_MAIL_CREATE, IAM_MAIL_READ, IAM_MAIL_UPDATE, IAM_MAIL_DELETE


class MailInstancesController(BaseController):
    """REST controller for /v1/types/mail/instances."""

    model = MailInstance
    crud = [CRUD.CREATE, CRUD.READ, CRUD.UPDATE, CRUD.DELETE]

    # Field-level permissions based on role
    fields_permissions = {
        "owner": {
            "read": [
                "id",
                "project_id",
                "name",
                "version",
                "status",
                "kind",
                "created_at",
                "domain",
                "max_users",
                "backup_enabled",
                "spam_filter_enabled",
                "virus_scan_enabled",
                "nodes",
            ],
            "write": ["name", "domain", "max_users", "backup_enabled", "spam_filter_enabled", "virus_scan_enabled"],
        },
        "operator": {
            "read": ["id", "project_id", "name", "version", "status", "domain", "max_users"],
            "write": ["max_users", "backup_enabled", "spam_filter_enabled"],
        },
        "viewer": {
            "read": ["id", "project_id", "name", "version", "status", "domain"],
            "write": [],
        },
    }

    def create(self, **kwargs) -> MailInstance:
        """Create a new mail instance.

        Do not set 'kind', 'id', 'status', 'created_at' — they are read-only
        and will be auto-populated from model.Config and defaults.
        """
        # Remove read-only fields if present
        for field in ["kind", "id", "status", "created_at", "nodes"]:
            kwargs.pop(field, None)

        instance = MailInstance(**kwargs)
        return super().create(instance)
