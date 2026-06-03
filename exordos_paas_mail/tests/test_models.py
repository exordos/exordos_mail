"""Unit tests for mail PaaS models."""

from __future__ import annotations

import pytest
from exordos_paas_mail.models import MailInstance


def test_mail_instance_creation() -> None:
    """Test MailInstance can be instantiated with required fields."""
    instance = MailInstance(
        project_id="test-project",
        name="mail-1",
        version="1.0.0",
        domain="example.com",
        max_users=50,
    )

    assert instance.project_id == "test-project"
    assert instance.name == "mail-1"
    assert instance.version == "1.0.0"
    assert instance.domain == "example.com"
    assert instance.max_users == 50


def test_mail_instance_defaults() -> None:
    """Test MailInstance defaults for optional fields."""
    instance = MailInstance(
        project_id="test-project",
        name="mail-2",
        version="1.0.0",
        domain="test.com",
    )

    assert instance.max_users == 100
    assert instance.backup_enabled is False
    assert instance.spam_filter_enabled is True
    assert instance.virus_scan_enabled is True


def test_mail_instance_kind() -> None:
    """Test MailInstance kind is single_node."""
    assert MailInstance.Config.kind == "single_node"
