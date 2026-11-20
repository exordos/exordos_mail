# Exordos Mail

Exordos Mail is the `mailaas` element for MetaPaaS. It provisions an SMTP
relay or a mail server with SMTP submission, IMAP and CalDAV.

Both modes use the same DP image, registered as `exim4_1` for existing deployments. Postfix handles SMTP in
both modes. Change the
instance's mode through the Mail API.

| Mode | Services |
| ---- | -------- |
| `smtp_only` (default) | Authenticated SMTP relay |
| `mailbox` | SMTP ingress and submission, mailboxes and calendars |

## Documentation

[English](docs/index.md) · [Русский](docs/index.ru.md)

- [Deploy and configure DNS](docs/usage/deployment.md)
- [Set up an external MX with a persistent queue](docs/usage/external-mx.md)
- [Persistent data, upgrades and TLS certificates](docs/usage/operations.md)
- [Control plane API](docs/api/reference.md)
- [Build and test the element](docs/developers/guide.md)
