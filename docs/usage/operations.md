# Data and certificates

[Русский](operations.ru.md)

## Persistent data in mailbox mode

The VM mounts a separate XFS data volume at `/persist`. Keep this
volume attached when replacing the root image. Preserve the entire
volume in backups, including permissions and ownership.

| Path | Contents |
| ---- | -------- |
| `/persist/mail/cyrus/` | Messages, calendars, local databases and Sieve data |
| `/persist/mail/postfix/` | Incoming mail queue |
| `/persist/mail/tx/` | Outgoing Postfix queue, DKIM key and scheduler credentials |
| `/persist/mail/control/` | Local recipient and sender lookups, password hashes and trusted MX IPs |
| `/persist/mail/rspamd/` | Rspamd work directory, including `rspamd.rrd`. Bind-mounted at `/var/lib/rspamd`. |
| `/persist/mail/valkey/` | Append-only data for Rspamd, including Bayes and scan history |
| `/persist/mail/tls/` | Certificates, private keys and the instance CA |
| `/persist/var/log/` | System logs, mounted at `/var/log` |

Runtime sockets and compiled Rspamd caches are recreated under
`/run` and `/var/cache`. MetaPaaS supplies the instance configuration,
and the data plane agent reconciles its credentials and recipient maps.
Back up the MetaPaaS database, including instances, SMTP accounts and mailboxes.

Before replacing the root image of an older mailbox VM, apply the
updated mailbox configuration on that VM while its old root is still
attached. This allows the configure service to migrate the previous
Rspamd work directory. Verify all three mounts before replacing the image.

```bash
mountpoint /persist
mountpoint /var/log
mountpoint /var/lib/rspamd
```

After replacement, verify the mounts again, check the mail services and
test submission, inbox access and delivery from an external MX. Deferred
mail on an external MX stays on that MX's own volume.

## Upgrade an older SMTP-only image

Before replacing an old root image, Core asks its agent to copy the keys
from `/etc/exim4/dkim/platform.private`, `/etc/exim4/exim.key` and
`/etc/exim4/exim.crt` to `/persist/mail` when present. Bootstrap also
imports available files from those paths and preserves any keys and
certificates already on the data volume.

The old Exim delivers its own pending mail. Core waits for its queue
to empty, then stops its listeners and rechecks the queue before
replacing the root image. The old Exim queue retains any frozen messages
while the update waits. Postfix has a separate queue format. The new
image starts with the prepared keys and restores SMTP logins from MetaPaaS.
The imported SMTP certificate initially serves its original name. If it
is the image-generated Exim certificate for the bare domain, distribute
`/persist/mail/tls/ca.crt` to SMTP clients before rotating it:

```bash
sudo /usr/local/lib/exordos-mail/mailbox-tls example.org /persist/mail/tls \
  --migrate-legacy-tx
```

The replacement covers `example.org` and `mail.example.org`. The command
reuses the TLS private key and saves the original certificate as
`/persist/mail/tls/tx-legacy.crt`. Update clients that pin the certificate
fingerprint when switching. Rotate operator-provided certificates through
their own certificate management process.

## Renew server certificates

Image-generated certificates cover `mail.<domain>`. RX and Cyrus share
`rx.crt`, and Postfix TX uses `tx.crt`. Distribute
`/persist/mail/tls/ca.crt` to clients and external MX nodes as their
trust anchor. Keep `ca.key` on the instance.

The `exordos-mail-tls-renew.timer` checks daily. It renews image-managed
server certificates within 30 days of expiry for another 90 days,
then restarts RX, TX and Cyrus to load them. Connections can be
interrupted during the restart. External MX queues retry temporary
delivery failures. Renew certificates provided by your organization
through its certificate management process.

```bash
systemctl list-timers exordos-mail-tls-renew.timer
sudo systemctl start exordos-mail-tls-renew.service
sudo journalctl -u exordos-mail-tls-renew.service -n 50
```

From the MX, verify the private RX certificate against the MX trust
bundle. Use the RX hostname and private IP configured on that MX.

```bash
openssl s_client -starttls smtp -connect 10.0.0.10:2525 \
  -servername mail.example.org -verify_hostname mail.example.org \
  -verify_return_error -CAfile /etc/postfix/tls/rx-ca.pem </dev/null
```

Routine renewal under the same CA requires no changes to MX, address,
SPF, DKIM or DMARC records. If you separately publish DANE TLSA records
that pin the renewed key or certificate, update them as part of renewal.

## Replace the instance CA

1. Generate the replacement CA and add its public certificate alongside
   the old trust anchor on each MX and client. On the MX, the bundle is
   `/etc/postfix/tls/rx-ca.pem`. Reload Postfix after changing its bundle.
2. Install the new `ca.crt` and its matching private `ca.key` in
   `/persist/mail/tls/`, preserving ownership and permissions. Run
   `exordos-mail-tls-renew.service` to reissue the server certificates.
3. Verify TLS from the MX and from clients, and check that queued mail
   reaches RX. Remove the old anchor after all services present the new chain.

For an older mailbox VM still using image-generated self-signed server
certificates, prepare its instance CA from the updated checkout on
the running VM before replacing its root image:

```bash
sudo bash exordos/images/mailbox_tls.sh example.org /persist/mail/tls --prepare-ca
```

Substitute the instance domain. Add the resulting `ca.crt` alongside
the existing trust entries on MX nodes and clients. The preparation
command keeps the certificates currently served by RX and TX. After the
update, verify the new chain and remove legacy trust entries after the
old certificates leave service.
