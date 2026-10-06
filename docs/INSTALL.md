# التثبيت المحلي — Local install

مِرْقاة كاملة على جهاز واحد للتجربة والاختبار: **لوحة اللجنة** (FastAPI + SQLite) وقارئ محلي يخدمه المثبّت اليوم من `web/fahras.html` (تجربة الآيات الثلاث)،
ومعهما **محرّك ذكاء محلي** (Ollama) يُختار حجمه حسب ذاكرة الجهاز. لا مفاتيح، ولا خدمات خارجية، ولا شيء يخرج من الجهاز.
قارئ سورة النور العام: https://mirqah.app (إصلاح المثبّت المحلي لخدمة `site/` معلّق). اللوحة: https://console.mirqah.app — هذا الملف للتثبيت المحلي فقط.

The whole of Mirqah on one machine for trying and testing: the committee console, a local reader that today serves `web/fahras.html` (three-ayah pilot), and a local
AI engine sized to your RAM. No keys, no external services; nothing leaves the machine.
The public An-Nur reader is https://mirqah.app (installer fix to serve `site/` pending). Console: https://console.mirqah.app. For the production server (Cloudflare Tunnel, CI-gated deploys) see [`deploy/README.md`](../deploy/README.md).

## ١. أمر واحد / One command

```bash
curl -fsSL https://raw.githubusercontent.com/yyahmed82/tafsir-methods-index/main/install.sh | bash
```

Or from a clone (installs that clone in place):

```bash
git clone -b main https://github.com/yyahmed82/tafsir-methods-index.git mirqah
cd mirqah && ./install.sh
```

The installer shows a system check, asks for your e-mail (used only to sign in locally) and then runs eight steps
with a progress bar. A full log is kept in `/tmp/mirqah-install-<uid>.log` and copied to `.mirqah-local/install.log`.
Running it again is safe: it skips what is done, updates the code and restarts the services.

## ٢. الحد الأدنى / Minimum requirements

| | Minimum | Notes |
|---|---|---|
| System | Ubuntu 22.04+, Debian 12+, WSL2 (Ubuntu) or macOS 12+ | Other Linux: install `git`, `curl`, Python 3.11+ first |
| CPU | 2 cores | A GPU is optional (NVIDIA or Apple Silicon is used automatically) |
| Memory | 4 GB demo · 8 GB lite · 16 GB full | One model is in memory at a time |
| Disk | 3 GB demo · 8 GB lite · 22 GB full | Mostly the models |
| Network | during install only | GitHub, PyPI, ollama.com |
| Rights | `sudo` on Linux | Only for system packages and Ollama; Mirqah itself runs as you |

Python 3.11+ is used if present; otherwise the installer fetches a private Python 3.12 with
[uv](https://docs.astral.sh/uv/) without touching the system Python. All Python packages go into `.venv/`.

Check a machine without installing anything:

```bash
bash install.sh --check
```

## ٣. مستويات الذكاء / AI tiers

The tier is picked from your memory and free disk; force one with `--tier`.

| Tier | RAM | Classifier | Verifier | Download | Good for |
|---|---|---|---|---|---|
| `full` | 16 GB | `qwen2.5:14b` | `gemma3:12b` | ~17 GB | Same model tags the team runs (نفس وسوم النماذج) — not a claim that tagging results match |
| `lite` | 8 GB | `qwen2.5:3b` | `gemma3:1b` | ~2.7 GB | Laptops; the full workflow runs, tagging quality is lower |
| `none` | 4 GB | — | — | 0 | Small VMs; the console runs on the simulated year (demo mode) |

The deterministic checker, the committee chair and the human review never need a model, so every tier shows the
whole workflow. Small models fail more steps (bad JSON, timeouts): the console retries them and they show as
"failed" — that is expected on `lite`, and the reason the specialist always decides.

## ٤. بعد التثبيت / After install

| What | Where |
|---|---|
| Committee console (local) | http://localhost:8800 — sign in with your e-mail; mail is in **mock mode**, so the one-time code appears on the screen |
| Local reader (today) | http://localhost:8080/fahras.html (`web/` pilot; public An-Nur reader: https://mirqah.app — installer code fix pending) |
| Demo data | Top bar → **Live \| Demo** → Demo: a generated year of committee work (not results) |
| Run the committee | Tasks → new task on the sample ayah 24:35 (needs tier `lite` or `full`) |

Control the services with `mirqah-local` (installed in `~/.local/bin`, also at `scripts/mirqah-local`):

```bash
mirqah-local status        # what runs, with links
mirqah-local logs console  # or: reader, ollama
mirqah-local stop
mirqah-local start
mirqah-local open          # open the console in the browser
mirqah-local update        # pull the latest code, reinstall packages, restart
mirqah-local uninstall     # stop and delete the install folder (asks first)
```

## ٥. على خادم عبر SSH / On a server over SSH

Everything listens on `127.0.0.1` by default. Install on the server, then open a tunnel from your laptop:

```bash
ssh -N -L 8800:127.0.0.1:8800 -L 8080:127.0.0.1:8080 you@server
```

and use http://localhost:8800 and http://localhost:8080/fahras.html on the laptop.
To expose it on a private network instead, install with `--bind 0.0.0.0` (the console still needs a sign-in;
turn off "show the code on screen" in Settings → Security before anyone else can reach it).

## ٦. الخيارات / Options

| Option | Default | Meaning |
|---|---|---|
| `--tier auto\|full\|lite\|none` | `auto` | AI engine size |
| `--dir PATH` | `~/mirqah` | Install folder (ignored when run from inside a clone) |
| `--branch NAME` | `main` | Branch to clone |
| `--port N` / `--reader-port N` | `8800` / `8080` | Console and reader ports |
| `--bind ADDR` | `127.0.0.1` | Listen address |
| `--email ADDR` `--name "NAME"` | `admin@mirqah.local` | The local super admin (also a specialist, so you can try reviews) |
| `--demo-months N` | `12` | Size of the simulated year |
| `--with-tests` | off | Run `pytest` after installing |
| `--no-start` | off | Install only |
| `--check` | off | System check only |
| `-y`, `--yes` | off | No questions (for scripts and CI) |
| `--uninstall` | | Same as `mirqah-local uninstall` |

Environment overrides: `MIRQAH_REPO_URL`, `MIRQAH_BRANCH`, `MIRQAH_DIR`, `MIRQAH_ADMIN_EMAIL`, `MIRQAH_ADMIN_NAME`,
`NO_COLOR=1` (plain output), `MIRQAH_ASCII=1` (no Unicode art).

## ٧. حل المشكلات / Troubleshooting

| Symptom | Fix |
|---|---|
| A step shows ✖ | The last lines of the log are printed under it; the full log is in `/tmp/mirqah-install-<uid>.log`. Fix the cause and run the installer again. |
| "Port 8800 is already in use" | `--port 8810` (and `--reader-port 8090`) |
| Console says the model engine is offline | `mirqah-local logs ollama`, then `mirqah-local restart`. Check: `curl http://127.0.0.1:11434/api/version` |
| Model download stops | Run the installer again — Ollama resumes partial downloads |
| macOS asks for "Command Line Tools" | Accept the system window, wait for it to finish, run the installer again |
| WSL2 without systemd | Fine: the installer starts `ollama serve` itself and `mirqah-local` manages it |
| Start from scratch | `mirqah-local uninstall`, then install again. Console data only: delete `console/var/` |

## ٨. ما الذي يُثبَّت أين / What goes where

| Path | What |
|---|---|
| `~/mirqah/` (or your clone) | The code |
| `~/mirqah/.venv/` | Python packages |
| `~/mirqah/console/var/` | Console database, demo database, secret key, mock outbox |
| `~/mirqah/.mirqah-local/` | Install settings, pids and logs |
| `~/.local/bin/mirqah-local` | Link to the control script |
| Ollama (system) | `/usr/local/bin/ollama` + models in `/usr/share/ollama/.ollama` (Linux) or `~/.ollama` (macOS) — kept on uninstall; remove models with `ollama rm <model>` |
