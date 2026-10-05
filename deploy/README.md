# Deploying مِرْقاة — public site + committee console

```
                     Cloudflare (edge in Riyadh / Jeddah / Dammam, HTTPS, WAF)
                     │                                   │
  https://<domain> ──┤ Cloudflare Pages                  │ Cloudflare Tunnel (outbound only)
  public reader      │ builds web/ from main             │
                     │                                   ▼
                     │               https://console.<domain> → Ubuntu server in KSA
                     │               cloudflared → 127.0.0.1:8800 → mirqah-console (FastAPI + SQLite)
                     │               mirqah-deploy.timer: every 2 min, pull main → wait for green CI
                     │                                    → new release → health check → or roll back
  Mac (Ollama) ── runs the AI committee, commits outputs on a branch → PR → CI → merge → both sites update
```

- **Public site** (`web/`, no login): Cloudflare Pages, rebuilt on every merge to `main`, with a preview link for each PR.
- **Committee console** (login by e-mail code, plus an optional view-only button for judges): one small
  Ubuntu 24.04 server. It opens **no ports**: `cloudflared` dials out to Cloudflare and the console listens on localhost only.
- **Deploys are pull-based.** The server reads the public repo; GitHub never holds a server key.
  A commit goes live only if the CI check `test` passed, its import check passed and `/api/public`
  answers with the new release. Otherwise the server stays on (or goes back to) the last good release.
- **AI runs stay on the Mac** (Ollama). The server shows and reviews results; its release folders are read-only.

## First-time setup

| # | Where | What |
|---|---|---|
| 1 | Cloudflare | Account, domain (Registrar, ~$10/yr), SSL "Always Use HTTPS", min TLS 1.2 |
| 2 | Cloudflare Pages | Connect the GitHub repo · production branch `main` · build command *(empty)* · output `web` · custom domain `<domain>` |
| 3 | Oracle Cloud (or any Ubuntu 24.04 VM) | Region Jeddah or Riyadh · Ampere A1 (2 OCPU / 12 GB, Always Free) · paste the SSH public key |
| 4 | Brevo (or Gmail app password) | Verify the domain (DNS records in Cloudflare) · create an SMTP key |
| 5 | Cloudflare Zero Trust → Networks → Tunnels | Create a tunnel · copy its token · public hostname `console.<domain>` → `http://localhost:8800` |
| 6 | Server | Run the bootstrap block below |
| 7 | Cloudflare → Security → WAF | Rate-limiting rule: host `console.<domain>`, path starts with `/api/auth/` (free plan: 1 rule) |

**Server block** (run on the server after `ssh ubuntu@<server-ip>`; edit the first four lines):

```bash
bash <<'EOF'
set -euo pipefail
DOMAIN="example.com"
ADMIN_EMAIL="you@example.com"
ADMIN_NAME="Your name"
SMTP_LOGIN="xxxxxx@smtp-brevo.com"
sudo apt-get update -qq && sudo apt-get install -y -qq git
rm -rf /tmp/mirqah-src && git clone -q --depth 1 https://github.com/yyahmed82/tafsir-methods-index.git /tmp/mirqah-src
sudo MIRQAH_CONSOLE_HOST="console.$DOMAIN" bash /tmp/mirqah-src/deploy/server/bootstrap.sh
read -rsp "Cloudflare tunnel token: " CF_TOKEN </dev/tty; echo
sudo cloudflared service install "$CF_TOKEN"; unset CF_TOKEN
sudo mirqah set-env MIRQAH_SMTP_PASSWORD
sudo mirqah settings-set smtp mode=smtp host=smtp-relay.brevo.com port=587 security=starttls \
  username="$SMTP_LOGIN" from_email="noreply@$DOMAIN" from_name="مِرْقاة"
sudo mirqah settings-set security show_mock_code=false
sudo mirqah create-user --email "$ADMIN_EMAIL" --name "$ADMIN_NAME" --role super_admin
sudo mirqah mail-test --to "$ADMIN_EMAIL"
sudo mirqah status
EOF
```

## Everyday operations (on the server)

| Task | Command |
|---|---|
| Deploy | Merge a PR into `main`. Live within ~2 minutes of CI turning green. |
| What is live / waiting | `sudo mirqah status` |
| Logs | `sudo mirqah logs 200` |
| Deploy now (still CI-gated) | `sudo mirqah-deploy run --wait 600` |
| Deploy the head even if CI is red/pending | `sudo mirqah-deploy run --force` |
| Roll back | `sudo mirqah-deploy rollback` (or `rollback <release>` from `mirqah-deploy releases`) |
| Add a teammate | `sudo mirqah create-user --email … --name "…" --role committee_operator` (or `specialist`, `viewer`; several: `--role super_admin,specialist` — an existing user gains these roles) |
| Review workflow, reminders, retries, publishing | see [docs/WORKFLOW.md](../docs/WORKFLOW.md); times in Settings → Workflow and → Reports |
| Published snapshot (what mirqah.app may show) | `curl -s https://console.<domain>/public/v1/manifest.json` |
| Judges' view-only button | `sudo mirqah guest on` · after judging `sudo mirqah guest off` |
| Rotate the SMTP key | `sudo mirqah set-env MIRQAH_SMTP_PASSWORD` |
| Hosted model key (team decision first) | `sudo mirqah set-env LLM_API_KEY` |
| Backup now / list | `sudo mirqah-backup` · `sudo mirqah-backup list` (nightly at 03:15, 14 days kept) |
| Model link check | `sudo mirqah llm-probe` |
| Demo data (simulated year) | `sudo mirqah demo-seed --months 12` · `sudo mirqah demo-status` · `sudo mirqah demo-clear` |
| Deploy messages in Discord | add `DISCORD_WEBHOOK_URL="…"` to `/etc/mirqah/deploy.env` |

Layout: releases in `/opt/mirqah/releases/<time>-<sha>`, live one at `/opt/mirqah/current`, state (DB, key)
in `/var/lib/mirqah`, secrets in `/etc/mirqah/mirqah.env` (root:mirqah 0640), deploy history in
`/var/lib/mirqah-deploy/history`.

## Connect the AI (models stay on the Mac, private link)

The server never runs the models. It calls Ollama on the team Mac through **Tailscale** (WireGuard,
free): nothing is opened to the internet, and Ollama keeps listening on the Mac's localhost only.

| Where | Once |
|---|---|
| Mac | Install Tailscale (`brew install --cask tailscale`), open it, sign in. Keep Ollama running with both models. |
| Mac | Publish Ollama to your tailnet only: `tailscale serve --bg --tcp 11434 tcp://localhost:11434` |
| Server | `curl -fsSL https://tailscale.com/install.sh \| sh` then `sudo tailscale up --hostname mirqah-console` (open the printed link, approve) |
| Server | `sudo mirqah settings-set llm base_url=http://<mac-tailscale-name>:11434` then `sudo mirqah llm-probe` |

Runs write `moves/`, `verified/`, `committee/` in the run workspace `/var/lib/mirqah/work`
(`MIRQAH_WORK_ROOT`), which `mirqah-deploy` refreshes from every release without deleting run outputs
(`sudo mirqah-deploy sync-work` refreshes it by hand). To bring results into git, on the Mac:
`bash deploy/mac/pull-runs.sh` → review → commit on a branch → PR. While the Mac sleeps the dashboard
says "engine offline", review and reports keep working, and new model runs are refused (packet checks still run).
Keep the Mac awake during demos: `caffeinate -dimsu`.

## Security checklist

- No inbound ports besides SSH (key only); the console binds 127.0.0.1; Cloudflare terminates HTTPS.
- `MIRQAH_ENV=production`: codes are never shown on screen, cookies are `Secure; HttpOnly; SameSite=Strict`,
  HSTS is on, unknown `Host` headers get 421, the visitor IP comes from `CF-Connecting-IP` (rate limits and audit log).
- The outbox keeps sent sign-in mail with the code masked.
- Guests are capped to view permissions in code, whatever role their row has; deactivate the guest user to cut them off.
- systemd sandbox: read-only system and releases, private /tmp, no new privileges, only `/var/lib/mirqah` writable.
- fail2ban for SSH, unattended security upgrades, nightly DB backups.
- Secrets live only in `/etc/mirqah/*.env` on the server — never in git, chat or CI.

## Fallback: run the console on the Mac

If no server is available, the same tunnel can point at the Mac (it must stay awake and online):

```bash
brew install cloudflared
sudo cloudflared service install <TOKEN>     # tunnel hostname → http://localhost:8800
caffeinate -dimsu &
MIRQAH_ENV=production MIRQAH_PROXY=cloudflare MIRQAH_ALLOWED_HOSTS=console.<domain> python -m console
```

## Troubleshooting

| Symptom | Check |
|---|---|
| New commit not live | `sudo mirqah status` → "CI: pending" (wait) / "marked bad" (fix and merge again, or `run --force`) |
| 421 "unknown host" | `MIRQAH_ALLOWED_HOSTS` in `/etc/mirqah/mirqah.env` must equal the tunnel hostname; then `sudo mirqah restart` |
| 502 / 1033 from Cloudflare | `systemctl status cloudflared` and `sudo mirqah status` |
| Codes not arriving | `sudo mirqah mail-test --to you@…`; Brevo sender/domain verified; check spam |
| Restore a backup | see the header of `deploy/server/mirqah-backup` |
