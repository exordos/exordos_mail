# Deploy Exordos Mail

[Русский](deployment.ru.md)

## Install the element

Run this command on a Realm with MetaPaaS installed. Add `-v VERSION` to
install a specific element build.

```bash
exordos e e install mailaas
```

Wait for the element to become `ACTIVE`. MetaPaaS registers the Mail API
and the available data plane images.

## Create an instance

Both modes use the `exim4_1` image version.

| Mode | Minimum vCPU | Minimum RAM | Minimum data disk |
| ---- | ------------ | ----------- | ----------------- |
| `smtp_only` | 1 | 512 MiB | 8 GiB |
| `mailbox` | 2 | 1024 MiB | 8 GiB |

Use 2048 MiB RAM as a starting point for `mailbox`. Size the data disk for
mailbox contents and mail queues. The example uses a 20 GiB data disk.

Set `MAIL_API` to the MetaPaaS base URL with the `/v1/types/mail` suffix
and set `TOKEN` to your API token. Use HTTPS when sending credentials.
List the available image versions and use the UUID of `exim4_1`.

```bash
curl --fail-with-body "$MAIL_API/versions/" -H "Authorization: Bearer $TOKEN"
```

Save the body below as `instance.json` and replace `PROJECT_UUID` and
`VERSION_UUID`. For send-only service, set `mode` to `smtp_only` or omit it.
The domain is set at creation.

```json
{
  "name": "mail-prod",
  "project_id": "PROJECT_UUID",
  "mode": "mailbox",
  "domain": "example.org",
  "cpu": 2,
  "ram": 2048,
  "disk_size": 20,
  "version": "/v1/types/mail/versions/VERSION_UUID"
}
```

```bash
curl --fail-with-body "$MAIL_API/instances/" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  --data-binary @instance.json
```

Set `INSTANCE_UUID` from the response. Poll the instance until its status is
`ACTIVE`. The response provides connection details in `endpoints` and the
DKIM record in `dkim_selector` and `dkim_public_key`.

```bash
curl --fail-with-body "$MAIL_API/instances/$INSTANCE_UUID" \
  -H "Authorization: Bearer $TOKEN" |
  jq '{status, endpoints, dkim_selector, dkim_public_key}'
```

## Create a mailbox or SMTP account

Send a mailbox request to `POST /v1/types/mail/instances/INSTANCE_UUID/mailboxes/`
with `local_part` (for example `alice`), `owner_user_uuid` and `password`.
Optional `aliases` contains local names such as `sales`. Use the same
`project_id` as the instance. Wait for the mailbox to become `ACTIVE`
before connecting.

For sending only, create an account at
`POST /v1/types/mail/instances/INSTANCE_UUID/accounts/` with `username`
(for example `app`) and `password`. Use the instance's project. Store
passwords securely and pass them only when creating an account or changing
its password. See the [API reference](../api/reference.md).

## Connect clients

Use the hostname in `endpoints`. The example instance returns
`mail.example.org`. Configure clients to trust the instance CA. See [certificate operations](operations.md).

| Protocol | Connection | Mailbox username |
| -------- | ---------- | ---------------- |
| SMTP submission | TCP 587 with STARTTLS | Full primary email address, such as `alice@example.org` |
| IMAP | TCP 993 with implicit TLS | Local part, such as `alice` |
| CalDAV | `https://mail.example.org:8443/dav/calendars/` | Local part, such as `alice` |

An SMTP account in `smtp_only` authenticates on port 587 with STARTTLS
using `username@domain`, such as `app@example.org`. SMTP-only also
accepts implicit TLS on port 465.

## Publish DNS records

| Record | Name | Value |
| ------ | ---- | ----- |
| A | `mail.example.org` | IPv4 address reachable by mail clients. Add AAAA if the services are available through an IPv6 frontend. |
| SPF TXT | `example.org` | Authorize the actual public TX source IP. For a single IPv4 sender, use `v=spf1 ip4:TX_PUBLIC_IP -all`. Include any other authorized senders. |
| DKIM TXT | `<dkim_selector>._domainkey.example.org` | Value from `dkim_public_key`. The default selector is `platform`. Split long TXT data into strings of up to 255 bytes in the same record. |
| DMARC TXT | `_dmarc.example.org` | Start with `v=DMARC1; p=none` while checking alignment and choose the enforcement policy for the domain. |
| PTR | Public TX IP | The SMTP hostname, with a matching forward address. Configure this at the IP provider. |
| MX | `example.org` | Public inbound MX hostnames and their priorities, for `mailbox` mode. Publish A or AAAA for each MX you advertise. |

Use the actual egress IP in SPF and PTR when TX sits behind NAT. The
public MX IPs can differ from the TX egress IP. Set up each
[external MX](external-mx.md) before advertising it in DNS.
