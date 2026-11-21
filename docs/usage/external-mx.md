# External MX

[Русский](external-mx.ru.md)

Deploy one or more dedicated Postfix MX nodes. Each node needs a public
TCP port 25, a local Rspamd Milter, a persistent volume mounted at
`/var/spool/postfix` and private connectivity to the instance's
`inbound_relay` on port 2525. Keep that RX port on the private network.
Each MX can run in a different network or cloud if it has that route.

## Configure the next hop

Use the sample configuration to route each hosted domain to the private
RX address. Resolve the next-hop name privately and match it to the
RX certificate name (`mail.<domain>` by default). The MX offers STARTTLS
to senders and requires verified TLS to RX. Copy the RX CA certificate
to the MX trust file `/etc/postfix/tls/rx-ca.pem`. See the
[Postfix example and installation commands](https://github.com/exordos/exordos_mail/tree/master/examples/external-mx).

Configure SPF, DKIM and DMARC at the MX. On RX, put each MX's source
IP as seen by RX on its own line in `/persist/mail/control/trusted-mx`.
Use dedicated source IPs and restart `exordos-mail-rspamd.service` to
reload the list. RX runs its own SPF, DKIM and DMARC checks and enforces the sender's DMARC reject policy. For a trusted
MX, Rspamd uses the original sender IP from the MX's `Received` header
for SPF. For other peers it uses the SMTP connection IP.

The MX accepts recipients in the configured domains with no recipient
list. RX delivers to known local recipients and silently discards
unknown local recipients individually, including messages with a mix
of known and unknown recipients.

## Queue and retry

The sample reserves 1 GiB of free space on the queue volume, accepts
messages up to 25 MiB and retries queued mail for up to five days.
Postfix starts with a five-minute retry backoff and increases it up to
one hour. Every MX has its own independent queue.

- Use `postqueue -j` to inspect deferred mail and monitor its age, queue
  size and disk usage on each node.
- Run `postqueue -f` on each MX after RX recovers to request immediate retry.
- For an outage approaching the queue lifetime, use `postsuper -h QUEUE_ID`
  to hold selected messages. Use `postsuper -H QUEUE_ID` after recovery, or
  `postsuper -r QUEUE_ID` after a long hold to requeue the message.

The sample permits delivery to the internal RX only. Returning delivery
status notifications to remote senders requires an additional route.
Check queueing and recovery before publishing MX records. From a private
test sender, deliver to a known mailbox while RX is unavailable, check
that the message appears in the deferred queue, and verify delivery to
the mailbox after RX recovers.
