#!/usr/bin/env bash
# One-time server setup for the Mirqah committee console (safe to run again).
# Tested target: Ubuntu 24.04 (arm64 or amd64), e.g. Oracle Cloud Always Free in Jeddah/Riyadh.
#
#   git clone --depth 1 https://github.com/yyahmed82/tafsir-methods-index.git /tmp/mirqah-src
#   sudo MIRQAH_CONSOLE_HOST=console.example.com bash /tmp/mirqah-src/deploy/server/bootstrap.sh
#
# Optional: MIRQAH_BRANCH (default main), MIRQAH_REPO_URL, MIRQAH_TZ (default Asia/Riyadh),
#           MIRQAH_SKIP_FIRST_DEPLOY=1
# What it does: packages + cloudflared, a locked-down 'mirqah' user, /opt/mirqah layout,
# /etc/mirqah env files, systemd units (console, 2-minute auto-deploy, nightly backup),
# fail2ban + automatic security updates, then the first CI-gated deploy.
# It never opens a port: the console listens on 127.0.0.1 and Cloudflare Tunnel publishes it.
set -euo pipefail

SRC=$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)
CONSOLE_HOST=${MIRQAH_CONSOLE_HOST:?set MIRQAH_CONSOLE_HOST=console.<your-domain>}
REPO_URL=${MIRQAH_REPO_URL:-https://github.com/yyahmed82/tafsir-methods-index.git}
BRANCH=${MIRQAH_BRANCH:-main}
TZ_NAME=${MIRQAH_TZ:-Asia/Riyadh}
GH_REPO=$(printf '%s' "$REPO_URL" | sed -E 's#^https://github.com/##; s#\.git$##')

PREFIX=/opt/mirqah
ETC=/etc/mirqah
STATE=/var/lib/mirqah-deploy
APP_USER=mirqah

step() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m!! %s\033[0m\n' "$*"; }

[ "$(id -u)" -eq 0 ] || { echo "run with sudo" >&2; exit 1; }
[ -f "$SRC/deploy/server/mirqah-deploy" ] || { echo "run this from a clone of the repo" >&2; exit 1; }
case "$CONSOLE_HOST" in *.*) ;; *) echo "MIRQAH_CONSOLE_HOST must be a host name like console.example.com" >&2; exit 1 ;; esac

step "System packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git curl ca-certificates python3 python3-venv python3-pip sqlite3 rsync \
  fail2ban unattended-upgrades >/dev/null
python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit(f"Python 3.11+ needed, found {sys.version.split()[0]} — use Ubuntu 24.04")
PY

step "cloudflared (Cloudflare Tunnel connector)"
if ! command -v cloudflared >/dev/null 2>&1; then
  install -d -m 0755 /usr/share/keyrings
  curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg -o /usr/share/keyrings/cloudflare-main.gpg
  echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' \
    >/etc/apt/sources.list.d/cloudflared.list
  apt-get update -qq
  apt-get install -y -qq cloudflared >/dev/null
fi
cloudflared --version | head -n 1

step "Time zone $TZ_NAME"
timedatectl set-timezone "$TZ_NAME" 2>/dev/null || warn "could not set the time zone"

step "Service user and folders"
id "$APP_USER" >/dev/null 2>&1 ||
  useradd --system --home-dir /var/lib/mirqah --shell /usr/sbin/nologin "$APP_USER"
install -d -o root -g root -m 0755 "$PREFIX" "$PREFIX/bin" "$PREFIX/releases"
install -d -o "$APP_USER" -g "$APP_USER" -m 0700 /var/lib/mirqah
install -d -o root -g root -m 0700 "$STATE" /var/backups/mirqah
install -d -o root -g "$APP_USER" -m 0750 "$ETC"

step "Operator tools (mirqah, mirqah-deploy, mirqah-backup)"
for f in mirqah mirqah-deploy mirqah-backup envfile.py; do
  install -m 0755 "$SRC/deploy/server/$f" "$PREFIX/bin/$f"
done
ln -sfn "$PREFIX/bin/mirqah" /usr/local/bin/mirqah
ln -sfn "$PREFIX/bin/mirqah-deploy" /usr/local/bin/mirqah-deploy
ln -sfn "$PREFIX/bin/mirqah-backup" /usr/local/bin/mirqah-backup

setenv() { printf '%s\n' "$3" | python3 "$PREFIX/bin/envfile.py" set "$1" "$2"; }

step "Environment files in $ETC"
if [ ! -f "$ETC/mirqah.env" ]; then
  install -o root -g "$APP_USER" -m 0640 /dev/null "$ETC/mirqah.env"
  cat >"$ETC/mirqah.env" <<'ENV'
# Mirqah console — server environment (root:mirqah 0640). Secrets live only in this file.
MIRQAH_ENV="production"
MIRQAH_PROXY="cloudflare"
MIRQAH_ALLOWED_HOSTS="console.example.com"
MIRQAH_REPO_ROOT="/opt/mirqah/current"
MIRQAH_VAR_DIR="/var/lib/mirqah"
MIRQAH_WORK_ROOT="/var/lib/mirqah/work"
# set with:  sudo mirqah set-env MIRQAH_SMTP_PASSWORD
# MIRQAH_SMTP_PASSWORD=""
# only if the team approves hosted model runs:  sudo mirqah set-env LLM_API_KEY
# LLM_API_KEY=""
ENV
fi
setenv "$ETC/mirqah.env" MIRQAH_ALLOWED_HOSTS "$CONSOLE_HOST"
if [ ! -f "$ETC/deploy.env" ]; then
  install -o root -g root -m 0600 /dev/null "$ETC/deploy.env"
  cat >"$ETC/deploy.env" <<'ENV'
# mirqah-deploy settings (root only)
REPO_URL="https://github.com/yyahmed82/tafsir-methods-index.git"
BRANCH="main"
GH_REPO="yyahmed82/tafsir-methods-index"
REQUIRED_CHECK="test"
KEEP_RELEASES="5"
# optional: a Discord channel webhook for deploy messages (paste it yourself)
# DISCORD_WEBHOOK_URL=""
# optional: off-site backups with rclone, e.g. "r2:mirqah-backups"
# RCLONE_REMOTE=""
ENV
fi
setenv "$ETC/deploy.env" REPO_URL "$REPO_URL"
setenv "$ETC/deploy.env" BRANCH "$BRANCH"
setenv "$ETC/deploy.env" GH_REPO "$GH_REPO"
chown root:"$APP_USER" "$ETC/mirqah.env" && chmod 0640 "$ETC/mirqah.env"
chown root:root "$ETC/deploy.env" && chmod 0600 "$ETC/deploy.env"

step "systemd units"
for u in mirqah-console.service mirqah-deploy.service mirqah-deploy.timer mirqah-backup.service mirqah-backup.timer; do
  install -m 0644 "$SRC/deploy/systemd/$u" "/etc/systemd/system/$u"
done
systemctl daemon-reload
systemctl enable mirqah-console.service >/dev/null

step "SSH protection and automatic security updates"
systemctl enable --now fail2ban >/dev/null 2>&1 || warn "fail2ban did not start"
cat >/etc/apt/apt.conf.d/20auto-upgrades <<'APT'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT
if sshd -T 2>/dev/null | grep -qi '^passwordauthentication yes'; then
  warn "SSH still accepts passwords. Keys only is safer: set PasswordAuthentication no in /etc/ssh/sshd_config.d/"
fi

if [ "${MIRQAH_SKIP_FIRST_DEPLOY:-0}" != "1" ]; then
  step "First deploy of $BRANCH (waits up to 15 min for the CI check)"
  "$PREFIX/bin/mirqah-deploy" run --wait 900 || warn "first deploy did not finish — see the lines above"
fi

step "Timers: auto-deploy every 2 minutes, backup nightly at 03:15"
systemctl enable --now mirqah-deploy.timer mirqah-backup.timer >/dev/null

step "Done"
"$PREFIX/bin/mirqah-deploy" status || true
cat <<EOF

Next (see deploy/README.md):
  1. Cloudflare Tunnel:  sudo cloudflared service install <TOKEN>
     public hostname  $CONSOLE_HOST  ->  http://localhost:8800
  2. Mail:  sudo mirqah set-env MIRQAH_SMTP_PASSWORD   then   sudo mirqah settings-set smtp mode=smtp ...
  3. First admin:  sudo mirqah create-user --email you@example.com --name "Your name" --role super_admin
EOF
