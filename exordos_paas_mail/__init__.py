"""Mail server PaaS plugin for MetaPaaS."""

from exordos_paas_mail.models import MailInstance
from exordos_paas_mail.controllers import MailInstancesController
from exordos_paas_mail.iam_config import IAM_MAIL

__all__ = ["MailInstance", "MailInstancesController", "IAM_MAIL"]
