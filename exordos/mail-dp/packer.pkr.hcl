variable "genesis_iso" {
  type    = string
  default = "https://repo.exordos.com/genesis/latest/genesis.iso"
}

variable "output_name" {
  type    = string
  default = "exordos-metapaas-mail-dp"
}

source "qemu" "mail_dp" {
  iso_url           = var.genesis_iso
  iso_checksum      = "none"
  disk_size         = "10G"
  memory            = 1024
  cpus              = 2
  accelerator       = "none"
  headless          = true
  qemu_binary       = "qemu-system-x86_64"
  format            = "qcow2"
  output_directory  = "output"
  output_name       = var.output_name
  disk_compression  = true
  disk_interface    = "virtio"
  net_device        = "virtio-net"

  ssh_username      = "root"
  ssh_password      = "exordos"
  ssh_timeout       = "10m"
  shutdown_command  = "shutdown -P now"

  http_directory    = "."
  http_port_min     = 8000
  http_port_max     = 8100

  # Inline boot commands to disable plymouth and start SSH early
  boot_command = [
    "e<wait>",
    "<Home>",
    "<End> nomodeset",
    "<F10>"
  ]
  boot_wait = "5s"
}

build {
  sources = [
    "source.qemu.mail_dp"
  ]

  # Update system packages
  provisioner "shell" {
    inline = [
      "apt-get update",
      "apt-get upgrade -y",
      "apt-get install -y postfix dovecot-core dovecot-imapd dovecot-pop3d amavisd-new clamav clamav-daemon spamassassin",
      "systemctl enable postfix",
      "systemctl enable dovecot",
      "systemctl enable clamav-daemon",
      "systemctl enable spamassassin"
    ]
  }

  # Create basic Postfix configuration
  provisioner "file" {
    content = <<-EOL
      # Mail server basic config (customized per instance via cloud-init)
      myhostname = mail.example.local
      mydomain = example.local
      myorigin = $mydomain
      mydestination = $myhostname, localhost.$mydomain, localhost, $mydomain
      inet_interfaces = all
      inet_protocols = all
      mynetworks = 127.0.0.0/8 [::ffff:127.0.0.0]/104 [::1]/128
      relayhost =
      alias_database = hash:/etc/aliases
      alias_maps = hash:/etc/aliases
    EOL
    destination = "/etc/postfix/main.cf.template"
  }

  # Create health check script
  provisioner "file" {
    content = <<-EOL
      #!/bin/bash
      # Health check endpoint script
      # Returns service status on stdout

      echo "mail-server"

      # Check if Postfix is running
      systemctl is-active postfix > /dev/null 2>&1 && echo "postfix=ok" || echo "postfix=down"

      # Check if Dovecot is running
      systemctl is-active dovecot > /dev/null 2>&1 && echo "dovecot=ok" || echo "dovecot=down"

      # Check port 25 (SMTP)
      nc -z localhost 25 > /dev/null 2>&1 && echo "smtp=ok" || echo "smtp=down"

      # Check port 143 (IMAP)
      nc -z localhost 143 > /dev/null 2>&1 && echo "imap=ok" || echo "imap=down"
    EOL
    destination = "/usr/local/bin/mail-health-check"
  }

  provisioner "shell" {
    inline = [
      "chmod +x /usr/local/bin/mail-health-check"
    ]
  }

  # Create systemd service for health check HTTP endpoint
  provisioner "file" {
    content = <<-EOL
      [Unit]
      Description=Mail Server Health Check HTTP Endpoint
      After=network.target

      [Service]
      Type=simple
      ExecStart=/bin/bash -c 'while true; do echo -e \"HTTP/1.1 200 OK\\r\\nContent-Type: text/plain\\r\\n\\r\\n$(mail-health-check)\" | nc -l -p 8080; done'
      Restart=always
      StandardOutput=journal
      StandardError=journal

      [Install]
      WantedBy=multi-user.target
    EOL
    destination = "/etc/systemd/system/mail-health-endpoint.service"
  }

  provisioner "shell" {
    inline = [
      "systemctl daemon-reload",
      "systemctl enable mail-health-endpoint"
    ]
  }

  # Cleanup
  provisioner "shell" {
    inline = [
      "apt-get clean",
      "apt-get autoclean",
      "apt-get autoremove -y",
      "find /tmp -type f -delete",
      "find /var/tmp -type f -delete"
    ]
  }
}
