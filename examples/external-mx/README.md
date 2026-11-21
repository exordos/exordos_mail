# External MX with a persistent queue

Use a dedicated VM with Postfix and a local Rspamd Milter. Mount a persistent
volume at `/var/spool/postfix`. Accept incoming SMTP on TCP port 25 and limit
outgoing SMTP to the internal RX. Allow DNS and the selected Rspamd reputation
sources. Keep the RX listener on a private network reachable from the MX.

Set the MX hostname in `main.cf`. For each hosted domain, add the private RX
next hop in `transport`. Resolve the RX hostname to its private address, for
example using `/etc/hosts`. The name in `transport` must match the RX
certificate.

Install the external MX certificate and key as
`/etc/postfix/tls/fullchain.pem` and `/etc/postfix/tls/privkey.pem`. Install
the internal relay's trust anchor as `/etc/postfix/tls/rx-ca.pem`. For
image-generated certificates, copy `/persist/mail/tls/ca.crt` from RX. For
existing deployments with a self-signed `rx.crt`, prepare the new CA on RX
before updating the image. Run the updated script from the checkout with the
instance domain, for example
`sudo bash exordos/images/mailbox_tls.sh example.org /persist/mail/tls --prepare-ca`.
Add the generated `ca.crt` to the existing trust file on the MX and to any
clients that pinned the old certificate. This command leaves the current RX
and TX certificates in service.
Configure Rspamd to listen on `127.0.0.1:11332` in Milter mode. Enable
SPF, DKIM and DMARC. In `/etc/rspamd/local.d/dmarc.conf`, set
`actions { reject = "reject"; }` to enforce the sender's DMARC reject policy
before Postfix queues the message.

On the internal RX, put each MX's SMTP source IP as seen by RX on its own
line in `/persist/mail/control/trusted-mx`. Use individual addresses dedicated
to the MX. RX accepts SMTP with STARTTLS on its private listener and runs SPF,
DKIM and DMARC. For a configured MX, Rspamd gets the original sender IP from
the MX's Received header. For other peers, it uses the SMTP connection IP.
Restart `exordos-mail-rspamd.service` to load the updated list.

Install and load the configuration on a Debian MX as root. The systemd drop-in
blocks startup if the queue volume is missing.

```sh
install -m 0644 main.cf transport rx_reply_filter /etc/postfix/
install -D -m 0644 persistent-queue.conf \
  /etc/systemd/system/postfix@-.service.d/10-persistent-queue.conf
postmap hash:/etc/postfix/transport
postfix check
systemctl daemon-reload
systemctl restart postfix
```

The MX accepts recipients in the configured domains and queues their mail on
disk. Postfix retries the internal relay after a temporary failure. The
internal RX discards unknown recipients individually and delivers to the
known recipients of the same message. Unknown local recipients generate no
bounce during that delivery.

Monitor deferred mail with `postqueue -j`. Run `postqueue -f` to retry
immediately. Alert well before the five-day queue lifetime. To retain an item
during a prolonged outage, use `postsuper -h QUEUE_ID`. Use
`postsuper -H QUEUE_ID` after recovery, or `postsuper -r QUEUE_ID` after long
retention to requeue it. This MX sends only to its next hop. Returning DSNs
for expired messages requires a separately configured delivery path.
