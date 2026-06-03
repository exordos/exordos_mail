"""Mail server PaaS instance models."""

from __future__ import annotations

from sqlalchemy import Boolean, Column, Integer, String
from metapaas.models import PaaS


class MailInstance(PaaS):
    """Mail server instance (Postfix + Dovecot)."""

    __tablename__ = "mail_instances"

    # Service-specific fields
    domain = Column(String(255), nullable=False, doc="Mail domain (e.g., example.com)")
    max_users = Column(Integer, default=100, doc="Maximum mail users")
    backup_enabled = Column(Boolean, default=False, doc="Enable automated backups")
    spam_filter_enabled = Column(Boolean, default=True, doc="Enable spam filtering")
    virus_scan_enabled = Column(Boolean, default=True, doc="Enable virus scanning")

    class Config:
        kind = "single_node"
