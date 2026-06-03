"""IAM configuration for mail PaaS plugin."""

from __future__ import annotations

from gcl_iam.models import Action, Resource

# Define IAM resource
IAM_MAIL = Resource(
    name="mail",
    display_name="Mail Server",
    parent=None,
)

# Actions available for mail instances
IAM_MAIL_CREATE = Action(name="create", display_name="Create mail instance")
IAM_MAIL_READ = Action(name="read", display_name="View mail instance")
IAM_MAIL_UPDATE = Action(name="update", display_name="Update configuration")
IAM_MAIL_DELETE = Action(name="delete", display_name="Delete instance")

# Role → action mappings
IAM_ROLES = {
    "owner": [IAM_MAIL_CREATE, IAM_MAIL_READ, IAM_MAIL_UPDATE, IAM_MAIL_DELETE],
    "operator": [IAM_MAIL_READ, IAM_MAIL_UPDATE],
    "viewer": [IAM_MAIL_READ],
}
