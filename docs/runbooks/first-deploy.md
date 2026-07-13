# Runbook — First deploy to a fresh VPS

Step-by-step for bringing YuPay live on a new Ubuntu 24.04 server.
This is the one-time bootstrap. Subsequent releases are described in
[`deploy.md`](deploy.md).

Target: **yupay.uz**, single VPS (≥ 4 vCPU / 8 GB RAM / 80 GB NVMe).

---

## 0. Prerequisites checklist

On your laptop:

- [ ] You own the domain `yupay.uz` (managed at your registrar).
- [ ] You have an SSH keypair (`~/.ssh/id_ed25519`).
- [ ] You have a Cloudflare R2 bucket (for backups) — bucket name + access key + secret.
- [ ] You have a Telegram bot token from `@BotFather`.
- [ ] You have an `age` keypair for backup encryption (`age-keygen -o ~/yupay-backup.key`).
      Public line goes to the server; **private line stays on your laptop**.
- [ ] (Optional) Sentry project + DSN.

On the VPS provider's panel:

- [ ] Ubuntu 24.04 image, ≥ 4 vCPU / 8 GB RAM / 80 GB NVMe.
- [ ] Public IPv4 address known.
- [ ] Provider snapshot/backup tier enabled.

---

## 1. DNS records

At your domain registrar (`yupay.uz`), point at the VPS public IP:

| Type | Name       | Value      | TTL |
| ---- | ---------- | ---------- | --- |
| A    | `@` (apex) | `<VPS_IP>` | 300 |
| A    | `www`      | `<VPS_IP>` | 300 |
| A    | `app`      | `<VPS_IP>` | 300 |
| A    | `admin`    | `<VPS_IP>` | 300 |
| A    | `api`      | `<VPS_IP>` | 300 |
| A    | `grafana`  | `<VPS_IP>` | 300 |

Wait until propagation finishes (usually 1–10 minutes):

```bash
dig +short yupay.uz @1.1.1.1
dig +short app.yupay.uz @1.1.1.1
dig +short api.yupay.uz @1.1.1.1
```

All six must answer with `<VPS_IP>` before Caddy can fetch certs.

---

## 2. Initial server setup

SSH in as `root` (or the provider-default user with `sudo`):

```bash
ssh root@<VPS_IP>

# Create a non-root deploy user.
adduser --disabled-password --gecos "" deploy
usermod -aG sudo deploy
mkdir -p /home/deploy/.ssh
cp ~/.ssh/authorized_keys /home/deploy/.ssh/
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys

# Lock down ssh: disable password login, root login, change to deploy.
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart ssh

# Basic firewall (Ubuntu UFW).
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
```

Re-login as `deploy@yupay.uz` (or whatever DNS you set) and never use
`root` again.

Install Docker + Docker Compose plugin:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg git rsync rclone
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu noble stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker deploy
newgrp docker  # or log out + back in
docker version
docker compose version
```

---

## 3. Clone the repository

Anywhere the deploy user owns — no root-owned path is needed, and every path in
`docker-compose.prod.yml` is relative to the checkout. On the current VPS it is
`~/opt/yupay`.

```bash
install -d ~/opt && cd ~/opt
git clone git@github.com:<your-org>/yupay.git
cd ~/opt/yupay
git checkout main   # or the tagged release you want to ship
```

Use a **read-only deploy key** for that clone (GitHub → Settings → Deploy keys),
so a compromised box cannot push to the repository.

---

## 4. Configure secrets

They live in `secrets/` inside the checkout — git-ignored via `/secrets/`, and
mounted by relative path (`env_file: ./secrets/api.env`). Owned by the deploy
user, so editing them needs no `sudo`.

```bash
cd ~/opt/yupay
install -d -m 0700 secrets

# Copy templates from the repo:
cp infra/secrets-example/*.env secrets/

# Edit each file and replace every "CHANGE_ME":
$EDITOR secrets/postgres.env
$EDITOR secrets/postgres-exporter.env
$EDITOR secrets/api.env
$EDITOR secrets/web.env
$EDITOR secrets/miniapp.env
$EDITOR secrets/grafana.env
$EDITOR secrets/backup.env

# Lock down permissions.
chmod 600 secrets/*.env

# Sanity check — must return nothing:
grep -RIn 'CHANGE_ME' secrets/
```

See `infra/secrets-example/README.md` for how to generate JWT
keypair, Grafana bcrypt hash, AGE recipient, etc.

---

## 5. Set up R2 remote for backups

```bash
# On the host, one-time:
rclone config
# new remote → name "r2" → type "s3" → provider "Cloudflare" → paste
# the R2 access key, secret, and endpoint URL.
rclone mkdir r2:yupay-backups
rclone lsd r2:                    # smoke-test
```

The backup container reads `~/.config/rclone/rclone.conf` from the
host via a future bind-mount; for now it inherits the host's rclone
config because the container shares the host's network and home dir
when run as `root`.

---

## 6. Bring the stack up

```bash
cd ~/opt/yupay

# Pull pre-built images from GHCR — the build workflow pushes :main on every
# push to main, and tagged releases land as :v1.2.3.
export IMAGE_TAG=main   # or the desired tag
docker compose -f docker-compose.prod.yml pull

# Apply migrations in a one-shot container.
docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head

# Start everything.
docker compose -f docker-compose.prod.yml up -d --remove-orphans
docker compose -f docker-compose.prod.yml ps
```

Watch logs of the slowest starters (Caddy fetches certs on first
request):

```bash
docker compose -f docker-compose.prod.yml logs -f caddy
# Look for: "certificate obtained successfully" — once for each domain.
```

---

## 7. Smoke tests

```bash
# Public storefront
curl -fsS -o /dev/null -w "%{http_code}\n" https://yupay.uz/   # 200
# Mini App entry
curl -fsS -o /dev/null -w "%{http_code}\n" https://app.yupay.uz/   # 200
# Admin SPA
curl -fsS -o /dev/null -w "%{http_code}\n" https://admin.yupay.uz/   # 200
# API liveness + readiness
curl -fsS https://api.yupay.uz/healthz   # {"status":"ok"}
curl -fsS https://api.yupay.uz/readyz    # {"status":"ready"}
# Prometheus metrics scrape (from inside the host only — public should 4xx)
docker compose -f docker-compose.prod.yml exec api curl -fsS http://localhost:8000/metrics | head -5
```

Open in a browser:

- https://yupay.uz/ — storefront landing
- https://app.yupay.uz/ — mini app shell
- https://admin.yupay.uz/ — admin login screen
- https://grafana.yupay.uz/ — basic-auth prompt → grafana login (creds from `grafana.env`)

---

## 8. Hook up the Telegram bot

```bash
# Long-polling already runs inside the bot container. Verify with:
docker compose -f docker-compose.prod.yml logs --tail=20 bot
# Should print: "bot.started" then "Start polling".
```

On `@BotFather` set the user-facing strings (texts live in
`docs/onboarding/bot-copy.md` — three languages):

- `/setname` → `YuPay — Пополнение, Игры, Сервисы`
- `/setabout` → from `bot-copy.md` § About
- `/setdescription` → from `bot-copy.md` § Description
- `/setuserpic` → upload `logo/bot-avatar-512.png`
- `/setdomain` → `yupay.uz` (so Telegram Login widget works on the storefront)
- `/setmenubutton` → enable a menu button → label "🚀 YuPay" → URL
  `https://app.yupay.uz` (opens the Mini App from the chat menu).

Then test by sending `/start` to your bot from your personal account.
Bot should reply with the localised welcome + inline mini-app button.

---

## 9. Enable the nightly backup

The backup container is `restart: "no"` — it runs once on demand. Wire
it to a host crontab:

```bash
sudo crontab -e
# Add (3 AM UTC = 8 AM Tashkent):
0 3 * * * cd ~/opt/yupay && docker compose -f docker-compose.prod.yml run --rm backup >> /var/log/yupay-backup.log 2>&1
```

Trigger one manual run to verify the pipeline end-to-end:

```bash
cd ~/opt/yupay
docker compose -f docker-compose.prod.yml run --rm backup
# Then on your laptop:
rclone ls r2:yupay-backups/$(date -u +%Y-%m-%d)/
```

---

## 10. (Optional) Sentry & log shipping

If you set `SENTRY_DSN` in `api.env`, `_init_sentry` in
`apps/api/src/yupay/bootstrap.py` activates the SDK on next restart.
Trigger a test error:

```bash
docker compose -f docker-compose.prod.yml exec api \
  python -c "raise RuntimeError('sentry-smoke-test')"
```

It should appear in the Sentry UI within a minute.

Loki + Promtail are already collecting container logs; check Grafana
→ Explore → Loki and try `{container=~"yupay-prod-.*"}`.

---

## Done

You should now have:

- Six subdomains live with valid Let's Encrypt certs.
- API responding to `/healthz` + `/readyz`.
- Mini App opening from the bot's `/start` button.
- Nightly Postgres backup encrypted to R2.
- Grafana dashboards (API · Overview, Infra · Overview) auto-provisioned.
- Prometheus alerts wired (API 5xx, queue backlog, disk low, host mem low).

Next operational tasks live in `docs/runbooks/`:

- routine deploys → [deploy.md](deploy.md)
- secret rotation → [rotate-secrets.md](rotate-secrets.md)
- backup restore drill → [restore-from-backup.md](restore-from-backup.md)
