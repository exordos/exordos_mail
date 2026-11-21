# Mail API

[Русский](reference.ru.md)

The API is served by MetaPaaS at `/v1/types/mail/`. Authenticate with a
Bearer token. The API applies project authorization to instances and
their child resources. See [deployment](../usage/deployment.md) for a
complete instance request.

| Method | Path relative to `/v1/types/mail/` | Operation |
| ------ | ----------------------------------- | --------- |
| GET | `versions/` | List registered image versions and mailbox support |
| GET | `versions/{version_uuid}` | Read an image version |
| GET, POST | `instances/` | List or create instances |
| GET, PUT, DELETE | `instances/{instance_uuid}` | Read, update or delete an instance |
| GET, POST | `instances/{instance_uuid}/accounts/` | List or create SMTP accounts |
| GET, PUT, DELETE | `instances/{instance_uuid}/accounts/{account_uuid}` | Read, update or delete an SMTP account |
| GET, POST | `instances/{instance_uuid}/mailboxes/` | List or create mailboxes |
| GET, PUT | `instances/{instance_uuid}/mailboxes/{mailbox_uuid}` | Read or update a mailbox |

## Instances

Set `domain`, `mode` and `version` at creation. `smtp_only` is the
default mode. A version with `supports_mailbox: true` supports both modes.
The version is a resource reference,
for example `/v1/types/mail/versions/{version_uuid}`. Update `cpu`, `ram`
(in MiB) and `disk_size` (in GiB) to resize an instance. The data disk
can grow. The mailbox CPU and memory minimums also apply on resize.

`status`, `ipsv4`, `endpoints`, `dkim_public_key` and `dkim_selector`
are read-only. In `mailbox` mode, `endpoints` contains `submission`,
`imap`, `caldav` and `inbound_relay`. In `smtp_only`, it contains
`submission`.

## Switch modes

Send `PUT /v1/types/mail/instances/INSTANCE_UUID` with `{"mode":"mailbox"}`
or `{"mode":"smtp_only"}`. Include `cpu` and `ram` in the same request if
the current VM needs more resources for `mailbox`. The VM applies the
change in place. Wait for `ACTIVE` before using the announced endpoints.

Postfix TX restarts and retains its queue, signing key and TLS material. SMTP
accounts work in both modes. In `smtp_only`, mailbox data stays on the
volume and account records stay in MetaPaaS. Mailbox login and inbound
delivery are paused. Switching back restores the mailboxes and their contents.
An external MX can queue and retry during the pause.

## SMTP accounts

Accounts supply submission credentials in either mode. Create one with
`username`, `password`, and the instance's `project_id` and `instance`
reference. The username is fixed at creation. Set `active: false` to
revoke authentication. The data plane applies changes asynchronously.

Use a plaintext password over HTTPS. For compatibility, `smtp_only` also
accepts a precomputed crypt hash in `password`, including SHA512-crypt
with the optional `{SHA512-CRYPT}` prefix. Use a precomputed hash if a
plaintext secret begins with `$` or a crypt scheme prefix. Send plaintext for accounts
created under a `mailbox` instance. Passwords are write-only, and
`password_hash` is hidden.

## Mailboxes

A mailbox belongs to the same project as its `mailbox` instance. For
example, send this body to the instance's `mailboxes/` collection.

```json
{
  "instance": "/v1/types/mail/instances/INSTANCE_UUID",
  "project_id": "PROJECT_UUID",
  "local_part": "alice",
  "owner_user_uuid": "USER_UUID",
  "aliases": ["sales"],
  "password": "REPLACE_WITH_A_GENERATED_PASSWORD"
}
```

`local_part` is fixed at creation. Choose local names using lowercase
letters, digits, underscores or hyphens. Start each name with a letter
or digit and use at most 64 characters. The primary name and aliases
must be unique among the instance's mailboxes and SMTP accounts. The
server computes the read-only `address` and `status`. Send a new
`password` to change it. Omit `password` on other updates.

Update `owner_user_uuid`, `aliases` or `active` on the mailbox resource.
An inactive mailbox retains its contents and continues to receive
mail. It loses SMTP, IMAP and CalDAV login access once reconciled.
