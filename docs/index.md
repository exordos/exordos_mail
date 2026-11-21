# Exordos Mail

[Русский](index.ru.md)

Mail is the `mailaas` element for MetaPaaS. It provisions one VM per instance.
Both modes use the same image. Use the default `smtp_only` mode for application SMTP relay. Choose `mailbox`
for receiving mail, authenticated submission, IMAP and CalDAV.

## Architecture

The MetaPaaS control plane stores instances, image versions, SMTP accounts
and mailbox metadata. It provisions the VM through Core. The data plane
agent reconciles accounts, aliases and credentials on that VM. Postfix TX handles submission in both modes and uses a dedicated Dovecot
authentication socket. In `mailbox`, the following
components run as systemd services on the same VM.

- Postfix RX accepts the configured domain on private TCP port 2525 with
  STARTTLS. It sends messages to Cyrus over a local LMTP socket.
- Rspamd checks SPF, DKIM, DMARC and spam for incoming mail. It keeps
  Bayes and scan history data in a local Valkey store.
- Cyrus provides IMAP and CalDAV and stores messages and calendars on
  the data volume. Cyrus uses local databases and files.
- Postfix TX uses an independent queue and a dedicated mail owner. It authenticates submission on port 587,
  checks the envelope sender and `From` against the account's allowed
  addresses, and signs outgoing messages with DKIM.

```text
Internet senders -> external MX:25 -> private RX:2525 -> Cyrus
                                      |
                                      +-> Rspamd -> Valkey

Mail clients -> TX:587 -> recipient MX (external domains)
                    |
                    +-> private RX:2525 (local domain)
Mail clients -> Cyrus:993 (IMAP), Cyrus:8443 (CalDAV)
```

Operators can place the public MX on a separate provider or network. Each MX
has its own disk queue and retries when the mailbox VM is unreachable.
This keeps incoming mail queued during a mailbox VM outage. Mailbox access
and submission still depend on the availability of that VM.

- [Deployment and DNS](usage/deployment.md)
- [External MX configuration and retry](usage/external-mx.md)
- [Persistence and certificate rotation](usage/operations.md)
- [Control plane API](api/reference.md)
- [Development guide](developers/guide.md)
