#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
#  مِرْقاة · Mirqah — local installer
#  Committee console + public reader + (optional) a local AI engine, on one machine.
#  Ubuntu / Debian (incl. WSL2) and macOS. Safe to run again: it resumes and updates.
#
#    curl -fsSL https://raw.githubusercontent.com/yyahmed82/tafsir-methods-index/install/local/install.sh | bash
#    ./install.sh --help
# ──────────────────────────────────────────────────────────────────────────────
set -Eeuo pipefail

INSTALLER_VERSION="1.0.0"
REPO_URL="${MIRQAH_REPO_URL:-https://github.com/yyahmed82/tafsir-methods-index.git}"
BRANCH="${MIRQAH_BRANCH:-install/local}"
DIR="${MIRQAH_DIR:-$HOME/mirqah}"
TIER="auto"
PORT=8800
READER_PORT=8080
BIND="127.0.0.1"
ADMIN_EMAIL="${MIRQAH_ADMIN_EMAIL:-}"
ADMIN_NAME="${MIRQAH_ADMIN_NAME:-}"
DEMO_MONTHS=12
ASSUME_YES=0
START=1
CHECK_ONLY=0
WITH_TESTS=0
DIR_GIVEN=0
OLLAMA_URL="http://127.0.0.1:11434"

# AI tiers: one model in memory at a time (the console runs one step at a time)
FULL_MODELS=("qwen2.5:14b" "gemma3:12b")   # ~17 GB download — same as the team's engine
LITE_MODELS=("qwen2.5:3b" "gemma3:1b")     # ~2.7 GB download — for 8 GB laptops
FULL_MIN_MB=15000; LITE_MIN_MB=7000; DEMO_MIN_MB=3500
FULL_DISK_GB=22;   LITE_DISK_GB=8;   DEMO_DISK_GB=3

usage() {
  cat <<EOF
Mirqah local installer v$INSTALLER_VERSION

Usage: install.sh [options]

  --tier auto|full|lite|none  AI engine size (default: auto, picked from your RAM and disk)
                              full  qwen2.5:14b + gemma3:12b   needs 16 GB RAM, 22 GB disk
                              lite  qwen2.5:3b  + gemma3:1b    needs  8 GB RAM,  8 GB disk
                              none  no AI engine; console runs on the simulated (demo) year
  --dir PATH                  install folder (default: ~/mirqah)
  --branch NAME               git branch to install (default: $BRANCH)
  --port N                    console port (default: 8800)
  --reader-port N             public reader port (default: 8080)
  --bind ADDR                 listen address (default: 127.0.0.1; 0.0.0.0 = whole network)
  --email ADDR --name "NAME"  the local super admin (default: admin@mirqah.local)
  --demo-months N             size of the simulated year (3-18, default 12)
  --with-tests                run the test suite after installing
  --no-start                  install only, do not start the services
  --check                     only check this machine against the minimum requirements
  -y, --yes                   no questions, accept the defaults
  --uninstall                 stop everything and remove the install folder
  -h, --help                  this help

After install: mirqah-local start|stop|status|logs|open|update|uninstall
EOF
}

# ── arguments ────────────────────────────────────────────────────────────────
need_val() { [ $# -ge 2 ] && [ -n "$2" ] || { echo "missing value for $1" >&2; exit 2; }; }
UNINSTALL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --tier) need_val "$@"; TIER=$2; shift 2 ;;            --tier=*) TIER=${1#*=}; shift ;;
    --dir) need_val "$@"; DIR=$2; DIR_GIVEN=1; shift 2 ;;  --dir=*) DIR=${1#*=}; DIR_GIVEN=1; shift ;;
    --branch) need_val "$@"; BRANCH=$2; shift 2 ;;         --branch=*) BRANCH=${1#*=}; shift ;;
    --port) need_val "$@"; PORT=$2; shift 2 ;;             --port=*) PORT=${1#*=}; shift ;;
    --reader-port) need_val "$@"; READER_PORT=$2; shift 2 ;; --reader-port=*) READER_PORT=${1#*=}; shift ;;
    --bind) need_val "$@"; BIND=$2; shift 2 ;;             --bind=*) BIND=${1#*=}; shift ;;
    --email) need_val "$@"; ADMIN_EMAIL=$2; shift 2 ;;     --email=*) ADMIN_EMAIL=${1#*=}; shift ;;
    --name) need_val "$@"; ADMIN_NAME=$2; shift 2 ;;       --name=*) ADMIN_NAME=${1#*=}; shift ;;
    --demo-months) need_val "$@"; DEMO_MONTHS=$2; shift 2 ;; --demo-months=*) DEMO_MONTHS=${1#*=}; shift ;;
    --with-tests) WITH_TESTS=1; shift ;;
    --no-start) START=0; shift ;;
    --check) CHECK_ONLY=1; shift ;;
    -y|--yes) ASSUME_YES=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
  esac
done
case "$TIER" in auto|full|lite|none) ;; *) echo "--tier must be auto, full, lite or none" >&2; exit 2 ;; esac
case "$PORT$READER_PORT$DEMO_MONTHS" in *[!0-9]*) echo "ports and --demo-months must be numbers" >&2; exit 2 ;; esac
DIR=${DIR/#\~/$HOME}

# ── terminal look ────────────────────────────────────────────────────────────
TTY=0; [ -t 1 ] && [ -z "${NO_COLOR:-}" ] && [ "${TERM:-dumb}" != dumb ] && TTY=1
# Unicode art unless the terminal is a bare Linux console (or MIRQAH_ASCII=1)
UTF=1; { [ "${TERM:-}" = linux ] || [ -n "${MIRQAH_ASCII:-}" ]; } && UTF=0
case "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" in
  *[Uu][Tt][Ff]-8*|*[Uu][Tt][Ff]8*) ;;
  *) if [ "$(uname -s)" = Linux ] && locale -a 2>/dev/null | grep -qix 'c.utf-\{0,1\}8'; then export LC_CTYPE=C.UTF-8; fi ;;
esac
if [ $TTY = 1 ]; then
  R=$'\e[0m'; B=$'\e[1m'
  GRN=$'\e[38;5;42m'; RED=$'\e[38;5;203m'; YEL=$'\e[38;5;221m'
  TEAL=$'\e[38;5;37m'; GOLD=$'\e[38;5;179m'; MUT=$'\e[38;5;245m'; CLR=$'\e[2K'
else
  R=; B=; GRN=; RED=; YEL=; TEAL=; GOLD=; MUT=; CLR=
fi
if [ $UTF = 1 ]; then
  OK="✔"; NO="✖"; WARN="⚠"; DOT="◆"; ARROW="▸"; BAR_ON="━"; BAR_OFF="─"
  SPIN=("⠋" "⠙" "⠹" "⠸" "⠼" "⠴" "⠦" "⠧" "⠇" "⠏")
else
  OK="ok"; NO="x"; WARN="!"; DOT="*"; ARROW=">"; BAR_ON="#"; BAR_OFF="-"
  SPIN=("|" "/" "-" "\\")
fi

TOTAL_STEPS=8
STEP_NO=0
T0=$SECONDS
LOG="${TMPDIR:-/tmp}/mirqah-install-$(id -u).log"
{ : >"$LOG"; } 2>/dev/null || LOG="$HOME/mirqah-install.log"
echo "Mirqah installer v$INSTALLER_VERSION — $(date)" >"$LOG"

say()  { printf '%s\n' "$*"; }
info() { printf '      %s%s%s\n' "$MUT" "$*" "$R"; }
ok()   { printf '    %s%s%s %s %s%s%s\n' "$GRN" "$OK" "$R" "$1" "$MUT" "${2:-}" "$R"; }
warn() { printf '    %s%s %s%s\n' "$YEL" "$WARN" "$*" "$R"; }
die()  {
  printf '\n    %s%s %s%s\n' "$RED" "$NO" "$*" "$R"
  printf '      %sFull log: %s%s\n' "$MUT" "$LOG" "$R"
  printf '      %sFix the cause and run the installer again — it picks up where it stopped.%s\n\n' "$MUT" "$R"
  exit 1
}
trap 'die "Stopped at line $LINENO (exit $?)."' ERR
trap 'printf "%s\n" "$R"; exit 130' INT

bar() { # bar <done> <total> <width>
  local done=$1 total=$2 width=${3:-28} n i out=""
  n=$(( done * width / total ))
  for ((i = 0; i < width; i++)); do
    if [ $i -lt $n ]; then out+="$BAR_ON"; else out+="$BAR_OFF"; fi
  done
  printf '%s%s%s' "$GOLD" "${out:0:$n}" "$R$MUT${out:$n}$R"
}

step() {
  STEP_NO=$((STEP_NO + 1))
  local pct=$(( (STEP_NO - 1) * 100 / TOTAL_STEPS ))
  printf '\n  %s%s%s %sStep %d/%d%s  %s%s%s\n' "$GOLD" "$DOT" "$R" "$B" "$STEP_NO" "$TOTAL_STEPS" "$R" "$B" "$1" "$R"
  printf '    %s %s%3d%%%s\n' "$(bar $((STEP_NO - 1)) $TOTAL_STEPS 40)" "$MUT" "$pct" "$R"
  printf '\n== Step %d/%d: %s\n' "$STEP_NO" "$TOTAL_STEPS" "$1" >>"$LOG"
}

# run "label" command... — spinner + elapsed time, output into the log
run() {
  local label=$1 start=$SECONDS rc=0 i=0 pid
  shift
  printf '\n-- %s\n$ %s\n' "$label" "$*" >>"$LOG"
  if [ $TTY = 1 ]; then
    ( "$@" ) >>"$LOG" 2>&1 </dev/null &
    pid=$!
    while kill -0 "$pid" 2>/dev/null; do
      printf '\r%s    %s%s%s %s %s%ds%s' "$CLR" "$TEAL" "${SPIN[i % ${#SPIN[@]}]}" "$R" "$label" "$MUT" $((SECONDS - start)) "$R"
      i=$((i + 1))
      sleep 0.1
    done
    if wait "$pid"; then rc=0; else rc=$?; fi
    printf '\r%s' "$CLR"
  else
    if ( "$@" ) >>"$LOG" 2>&1 </dev/null; then rc=0; else rc=$?; fi
  fi
  if [ $rc -eq 0 ]; then
    ok "$label" "$((SECONDS - start))s"
  else
    printf '    %s%s %s%s %s(exit %d)%s\n' "$RED" "$NO" "$label" "$R" "$MUT" "$rc" "$R"
    tail -n 15 "$LOG" | sed 's/^/      │ /'
    trap - ERR
    die "\"$label\" failed."
  fi
}

ask() { # ask "question" default -> REPLY
  REPLY=$2
  if [ $ASSUME_YES = 0 ] && [ -r /dev/tty ] && { : </dev/tty; } 2>/dev/null; then
    printf '    %s?%s %s %s[%s]%s ' "$TEAL" "$R" "$1" "$MUT" "$2" "$R" >/dev/tty
    IFS= read -r REPLY </dev/tty || REPLY=$2
    [ -n "$REPLY" ] || REPLY=$2
  fi
}

banner() {
  local art=(
"███╗   ███╗██╗██████╗  ██████╗  █████╗ ██╗  ██╗"
"████╗ ████║██║██╔══██╗██╔═══██╗██╔══██╗██║  ██║"
"██╔████╔██║██║██████╔╝██║   ██║███████║███████║"
"██║╚██╔╝██║██║██╔══██╗██║▄▄ ██║██╔══██║██╔══██║"
"██║ ╚═╝ ██║██║██║  ██║╚██████╔╝██║  ██║██║  ██║"
"╚═╝     ╚═╝╚═╝╚═╝  ╚═╝ ╚══▀▀═╝ ╚═╝  ╚═╝╚═╝  ╚═╝"
  )
  local stairs=(
"                                              ▁▁╱"
"                                         ▁▁╱"
"                                    ▁▁╱"
  )
  local shades=(30 36 37 73 179 178)
  local delay=0; [ $TTY = 1 ] && delay=0.035
  say ""
  if [ $UTF = 1 ]; then
    for i in 0 1 2; do printf '  %s%s%s\n' "$MUT" "${stairs[$i]}" "$R"; sleep $delay; done
    for i in "${!art[@]}"; do
      if [ $TTY = 1 ]; then printf '  \e[38;5;%sm%s\e[0m\n' "${shades[$i]}" "${art[$i]}"; else printf '  %s\n' "${art[$i]}"; fi
      sleep $delay
    done
  else
    say "  M I R Q A H"
  fi
  say ""
  printf '  %sمِرْقاة%s  %s·%s  %sTafsir Methods Index%s  %s·%s  Islamic AI Challenge 2026, Track 4\n' "$GOLD$B" "$R" "$MUT" "$R" "$B" "$R" "$MUT" "$R"
  local tag="The AI orders the text; it never writes a letter of it."
  if [ $TTY = 1 ]; then
    printf '  %s' "$MUT"
    for ((i = 0; i < ${#tag}; i++)); do printf '%s' "${tag:$i:1}"; sleep 0.008; done
    printf '%s\n' "$R"
  else
    say "  $tag"
  fi
  printf '  %sinstaller v%s · branch %s · log %s%s\n' "$MUT" "$INSTALLER_VERSION" "$BRANCH" "$LOG" "$R"
}

# ── helpers ──────────────────────────────────────────────────────────────────
have() { command -v "$1" >/dev/null 2>&1; }
SUDO=""
if [ "$(id -u)" -ne 0 ] && have sudo; then SUDO="sudo"; fi
SUDO_KEEPALIVE=""
sudo_ready() { # ask for the password once, in the foreground, then keep it warm
  [ -n "$SUDO" ] || { [ "$(id -u)" -eq 0 ] && return 0; die "This step needs root and sudo is not installed."; }
  [ -n "$SUDO_KEEPALIVE" ] && return 0
  info "Administrator rights are needed for system packages (sudo)."
  sudo -v </dev/tty 2>/dev/tty || sudo -v || die "sudo was refused."
  ( while kill -0 $$ 2>/dev/null; do sudo -n true 2>/dev/null; sleep 50; done ) &
  SUDO_KEEPALIVE=$!
}
cleanup() { [ -n "$SUDO_KEEPALIVE" ] && kill "$SUDO_KEEPALIVE" 2>/dev/null; return 0; }
trap cleanup EXIT

wait_http() { # wait_http URL seconds
  local url=$1 n=${2:-30}
  for ((k = 0; k < n * 2; k++)); do curl -fsS -m 2 -o /dev/null "$url" 2>/dev/null && return 0; sleep 0.5; done
  return 1
}

# ── uninstall ────────────────────────────────────────────────────────────────
if [ $UNINSTALL = 1 ]; then
  [ -x "$DIR/scripts/mirqah-local" ] || { echo "No Mirqah install found in $DIR (use --dir)." >&2; exit 1; }
  exec "$DIR/scripts/mirqah-local" uninstall
fi

# If this script sits inside a clone, install that clone in place.
SELF="${BASH_SOURCE[0]:-}"
if [ -n "$SELF" ] && [ -f "$SELF" ] && [ $DIR_GIVEN = 0 ]; then
  SELF_DIR=$(cd "$(dirname "$SELF")" && pwd)
  [ -f "$SELF_DIR/console/app.py" ] && DIR=$SELF_DIR
fi

banner

# ══ 1. System check ══════════════════════════════════════════════════════════
step "Checking this machine"
OS=$(uname -s); ARCH=$(uname -m); OS_NAME="$OS"; PKG=""
case "$OS" in
  Linux)
    # shellcheck disable=SC1091
    [ -r /etc/os-release ] && OS_NAME=$(. /etc/os-release && echo "${PRETTY_NAME:-Linux}")
    grep -qi microsoft /proc/version 2>/dev/null && OS_NAME="$OS_NAME (WSL2)"
    have apt-get && PKG=apt
    RAM_MB=$(awk '/MemTotal/ {printf "%d", $2 / 1024}' /proc/meminfo)
    CPUS=$(nproc 2>/dev/null || echo 1)
    ;;
  Darwin)
    OS_NAME="macOS $(sw_vers -productVersion 2>/dev/null)"
    PKG=brew
    RAM_MB=$(( $(sysctl -n hw.memsize) / 1048576 ))
    CPUS=$(sysctl -n hw.ncpu)
    ;;
  *) die "Unsupported system: $OS. Use Ubuntu/Debian, WSL2 or macOS." ;;
esac
probe=$DIR; while [ ! -d "$probe" ]; do probe=$(dirname "$probe"); done
DISK_GB=$(df -Pk "$probe" | awk 'NR==2 {printf "%d", $4 / 1048576}')
GPU="none (CPU only: fine, just slower)"
if have nvidia-smi; then
  GPU=$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | head -n 1 || true)
  [ -n "$GPU" ] || GPU="NVIDIA (driver not answering)"
elif [ "$OS" = Darwin ] && [ "$ARCH" = arm64 ]; then
  GPU="Apple Silicon (Metal, shared memory)"
fi
RAM_GB=$(awk -v m="$RAM_MB" 'BEGIN {printf "%.1f", m / 1024}')

if [ "$TIER" = auto ]; then
  if [ "$RAM_MB" -ge $FULL_MIN_MB ] && [ "$DISK_GB" -ge $FULL_DISK_GB ]; then TIER=full
  elif [ "$RAM_MB" -ge $LITE_MIN_MB ] && [ "$DISK_GB" -ge $LITE_DISK_GB ]; then TIER=lite
  else TIER=none; fi
  TIER_WHY="picked from your memory and disk"
else
  TIER_WHY="chosen with --tier"
fi
case "$TIER" in
  full) MODELS=("${FULL_MODELS[@]}"); NEED_MB=$FULL_MIN_MB; NEED_GB=$FULL_DISK_GB; TIER_DESC="full — ${FULL_MODELS[0]} + ${FULL_MODELS[1]} (~17 GB download)" ;;
  lite) MODELS=("${LITE_MODELS[@]}"); NEED_MB=$LITE_MIN_MB; NEED_GB=$LITE_DISK_GB; TIER_DESC="lite — ${LITE_MODELS[0]} + ${LITE_MODELS[1]} (~2.7 GB download)" ;;
  none) MODELS=(); NEED_MB=$DEMO_MIN_MB; NEED_GB=$DEMO_DISK_GB; TIER_DESC="none — no AI engine; the console runs on the simulated year" ;;
esac

mark() { if [ "$1" = 1 ]; then printf '%s%s%s' "$GRN" "$OK" "$R"; elif [ "$1" = 2 ]; then printf '%s%s%s' "$YEL" "$WARN" "$R"; else printf '%s%s%s' "$RED" "$NO" "$R"; fi; }
row() { printf '    %s %-11s %-38s %s%s%s\n' "$(mark "$1")" "$2" "$3" "$MUT" "$4" "$R"; }
os_ok=1; [ -z "$PKG" ] && [ "$OS" = Linux ] && os_ok=2
cpu_ok=1; [ "$CPUS" -lt 2 ] && cpu_ok=2
ram_ok=1; [ "$RAM_MB" -lt "$NEED_MB" ] && ram_ok=2; [ "$RAM_MB" -lt $DEMO_MIN_MB ] && ram_ok=0
disk_ok=1; [ "$DISK_GB" -lt "$NEED_GB" ] && disk_ok=0
say ""
printf '      %s%-11s %-38s%s %s%s%s\n' "$B" "What" "This machine" "$R" "$MUT" "Minimum" "$R"
row $os_ok   "System"  "$OS_NAME ($ARCH)"   "Ubuntu 22.04+/Debian 12+, WSL2, macOS 12+"
row $cpu_ok  "CPU"     "$CPUS cores"          "2 cores"
row $ram_ok  "Memory"  "$RAM_GB GB"           "4 GB demo · 8 GB lite · 16 GB full"
row $disk_ok "Disk"    "$DISK_GB GB free"     "3 GB demo · 8 GB lite · 22 GB full"
row 1        "GPU"     "$GPU"                 "optional"
row 1        "Network" "needed during install" "GitHub, PyPI, ollama.com"
port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }
ours() { [ -f "$DIR/.mirqah-local/$1.pid" ] && kill -0 "$(cat "$DIR/.mirqah-local/$1.pid")" 2>/dev/null; }
if port_busy "$PORT" && ! ours console; then die "Port $PORT is already in use by another program. Pick another: --port 8810"; fi
if port_busy "$READER_PORT" && ! ours reader; then die "Port $READER_PORT is already in use by another program. Pick another: --reader-port 8090"; fi
row 1 "Ports" "$PORT (console), $READER_PORT (reader)" "two free ports"
say ""
printf '    %sAI tier:%s %s%s%s  %s(%s)%s\n' "$B" "$R" "$GOLD" "$TIER_DESC" "$R" "$MUT" "$TIER_WHY" "$R"
[ $ram_ok = 0 ] && die "Less than 4 GB of memory: too small even for the demo."
[ $disk_ok = 0 ] && die "Not enough free disk for the '$TIER' tier ($NEED_GB GB needed, $DISK_GB GB free). Free space or use --tier lite/none."
[ $ram_ok = 2 ] && warn "Below the memory advised for the '$TIER' tier — models will be slow or may fail. Consider --tier lite or none."
[ "$OS" = Linux ] && [ -z "$PKG" ] && warn "No apt-get: install git, curl, python3 (3.11+) yourself; the rest is automatic."

if [ $CHECK_ONLY = 1 ]; then
  say ""; ok "Check finished" "nothing was installed"; say ""; exit 0
fi

say ""
info "Install folder : $DIR"
info "Console        : http://$BIND:$PORT   ·   Public reader: http://$BIND:$READER_PORT"
if [ -z "$ADMIN_EMAIL" ]; then ask "Your e-mail for signing in to the console (stays on this machine)" "admin@mirqah.local"; ADMIN_EMAIL=$REPLY; fi
if [ -z "$ADMIN_NAME" ]; then ask "Your name" "Local admin"; ADMIN_NAME=$REPLY; fi
case "$ADMIN_EMAIL" in *@*.*) ;; *) die "'$ADMIN_EMAIL' is not an e-mail address." ;; esac
ask "Start the installation? (Y/n)" "Y"
case "$REPLY" in [Nn]*) say ""; info "Nothing was changed."; exit 0 ;; esac

# ══ 2. System packages ═══════════════════════════════════════════════════════
step "System packages"
if [ "$OS" = Linux ] && [ "$PKG" = apt ]; then
  missing=()
  for p in git curl ca-certificates python3 python3-venv sqlite3 zstd; do
    dpkg -s "$p" >/dev/null 2>&1 || missing+=("$p")
  done
  if [ ${#missing[@]} -gt 0 ]; then
    sudo_ready
    run "Refreshing package lists" $SUDO env DEBIAN_FRONTEND=noninteractive apt-get update -qq
    run "Installing ${missing[*]}" $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${missing[@]}"
  else
    ok "git, curl, python3, sqlite3 already installed"
  fi
elif [ "$OS" = Darwin ]; then
  if ! xcode-select -p >/dev/null 2>&1 || ! have git; then
    warn "Apple's command line tools are needed (git). A system window will open."
    xcode-select --install 2>/dev/null || true
    die "Finish the Command Line Tools install, then run this installer again."
  fi
  ok "Command line tools and git present"
  have brew && ok "Homebrew present" || info "No Homebrew — not required."
else
  for t in git curl python3; do have "$t" || die "Please install '$t' first."; done
  ok "git, curl, python3 present"
fi
have curl || die "curl is required."
have git || die "git is required."

# ══ 3. Python 3.11+ ══════════════════════════════════════════════════════════
step "Python runtime (3.11 or newer)"
PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if have "$c" && "$c" -c 'import sys, venv, ensurepip; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PY=$(command -v "$c"); break
  fi
done
UV=""
for u in uv "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do have "$u" && { UV=$(command -v "$u"); break; }; done
if [ -n "$PY" ]; then
  ok "Using $("$PY" -V 2>&1)" "$PY"
else
  info "No Python 3.11+ here — fetching a private copy with uv (does not touch the system Python)."
  if [ -z "$UV" ]; then
    get_uv() {
      curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh ||
        python3 -m pip install --user --break-system-packages uv ||
        python3 -m pip install --user uv
    }
    run "Installing uv (Python manager)" get_uv
    for u in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do [ -x "$u" ] && UV=$u; done
    [ -n "$UV" ] || die "uv could not be installed."
  fi
  run "Installing Python 3.12 with uv" "$UV" python install 3.12
  ok "Python 3.12 ready (managed by uv)"
fi

# ══ 4. Source code ═══════════════════════════════════════════════════════════
step "Getting the Mirqah source"
if [ -f "$DIR/console/app.py" ] && git -C "$DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if [ -n "$(git -C "$DIR" status --porcelain --untracked-files=no 2>/dev/null)" ]; then
    warn "Local changes in $DIR — keeping your version (no update)."
  elif [ "${SELF_DIR:-}" = "$DIR" ]; then
    ok "Installing this clone in place" "$(git -C "$DIR" rev-parse --abbrev-ref HEAD) @ $(git -C "$DIR" rev-parse --short HEAD)"
  else
    update_src() {
      git -C "$DIR" fetch -q --depth 1 origin "$BRANCH" &&
        git -C "$DIR" checkout -q -B "$BRANCH" FETCH_HEAD
    }
    run "Updating $DIR to the latest $BRANCH" update_src
  fi
elif [ -e "$DIR" ] && [ -n "$(ls -A "$DIR" 2>/dev/null)" ]; then
  die "$DIR exists and is not a Mirqah clone. Pick another folder with --dir."
else
  mkdir -p "$(dirname "$DIR")"
  run "Cloning $BRANCH into $DIR" git clone -q --depth 1 --branch "$BRANCH" "$REPO_URL" "$DIR"
fi
ok "Source at $DIR" "$(git -C "$DIR" log -1 --format='%h · %cs · %s' | cut -c1-60)"
STATE="$DIR/.mirqah-local"
mkdir -p "$STATE"
cd "$DIR"

# ══ 5. Python packages ═══════════════════════════════════════════════════════
step "Python packages (isolated in .venv)"
VENV="$DIR/.venv"; VPY="$VENV/bin/python"
REQS=(-r "$DIR/requirements.txt" -r "$DIR/console/requirements.txt" httpx pytest)
if [ -x "$VPY" ] && "$VPY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
  ok "Re-using $VENV"
elif [ -n "$PY" ]; then
  run "Creating the virtual environment" "$PY" -m venv "$VENV"
else
  run "Creating the virtual environment" "$UV" venv -q --python 3.12 "$VENV"
fi
if [ -n "$UV" ]; then
  run "Installing packages (FastAPI, Uvicorn, jsonschema …)" "$UV" pip install -q --python "$VPY" "${REQS[@]}"
else
  run "Upgrading pip" "$VPY" -m pip install -q --upgrade pip
  run "Installing packages (FastAPI, Uvicorn, jsonschema …)" "$VPY" -m pip install -q "${REQS[@]}"
fi
run "Checking the console imports" "$VPY" -c 'import fastapi, uvicorn, jsonschema; import console.app'
ok "$("$VPY" -V) in $VENV"

# ══ 6. AI engine ═════════════════════════════════════════════════════════════
step "AI engine (Ollama, tier: $TIER)"
OLLAMA=""
find_ollama() {
  OLLAMA=""
  if have ollama; then OLLAMA=$(command -v ollama)
  elif [ -x /Applications/Ollama.app/Contents/Resources/ollama ]; then OLLAMA=/Applications/Ollama.app/Contents/Resources/ollama
  elif [ -x "$HOME/Applications/Ollama.app/Contents/Resources/ollama" ]; then OLLAMA="$HOME/Applications/Ollama.app/Contents/Resources/ollama"
  fi
  [ -n "$OLLAMA" ]
}
if [ "$TIER" = none ]; then
  ok "Skipped" "tier none — switch later with: ./install.sh --tier lite"
else
  if find_ollama; then
    ok "Ollama present" "$("$OLLAMA" --version 2>/dev/null | tail -n 1)"
  elif [ "$OS" = Linux ]; then
    sudo_ready
    get_ollama() { curl -fsSL https://ollama.com/install.sh | sh; }
    run "Installing Ollama (official script)" get_ollama
    find_ollama || die "Ollama did not install."
  else
    if have brew; then
      run "Installing Ollama with Homebrew" brew install ollama
    else
      get_ollama_mac() {
        local dest=/Applications; [ -w "$dest" ] || { dest="$HOME/Applications"; mkdir -p "$dest"; }
        curl -fsSL -o "$STATE/Ollama-darwin.zip" https://ollama.com/download/Ollama-darwin.zip &&
          ditto -x -k "$STATE/Ollama-darwin.zip" "$dest" && rm -f "$STATE/Ollama-darwin.zip"
      }
      run "Downloading Ollama for macOS" get_ollama_mac
    fi
    find_ollama || die "Ollama did not install."
  fi

  if curl -fsS -m 3 "$OLLAMA_URL/api/version" >/dev/null 2>&1; then
    ok "Ollama is answering on $OLLAMA_URL"
  else
    if [ "$OS" = Linux ] && have systemctl && systemctl list-unit-files ollama.service >/dev/null 2>&1 &&
       $SUDO systemctl start ollama 2>/dev/null; then
      :
    elif [ "$OS" = Darwin ] && [[ "$OLLAMA" == *Ollama.app* ]]; then
      open -ga Ollama 2>/dev/null || true
    else
      nohup "$OLLAMA" serve >>"$STATE/ollama.log" 2>&1 &
      echo $! >"$STATE/ollama.pid"
    fi
    run "Starting the Ollama server" wait_http "$OLLAMA_URL/api/version" 40
  fi

  for m in "${MODELS[@]}"; do
    if "$OLLAMA" list 2>/dev/null | awk 'NR > 1 {print $1}' | grep -qx "$m"; then
      ok "Model $m already downloaded"
    else
      printf '    %s%s%s Downloading model %s%s%s\n' "$TEAL" "$ARROW" "$R" "$B" "$m" "$R"
      if [ $TTY = 1 ]; then
        "$OLLAMA" pull "$m" || die "Could not download $m (network?)."
      else
        run "Downloading model $m" "$OLLAMA" pull "$m"
      fi
      ok "Model $m ready"
    fi
  done
fi

# ══ 7. Configure the console ═════════════════════════════════════════════════
step "Configuring the committee console"
cd "$DIR"
cons() { "$VPY" -m console "$@"; }
if [ "$TIER" != none ]; then
  run "AI models → ${MODELS[0]} (classifier) + ${MODELS[1]} (verifier)" \
    cons settings-set llm base_url="$OLLAMA_URL" classifier_model="${MODELS[0]}" verifier_model="${MODELS[1]}"
fi
run "Console link → http://localhost:$PORT" cons settings-set general console_url="http://localhost:$PORT"
run "Super admin → $ADMIN_EMAIL" cons create-user --email "$ADMIN_EMAIL" --name "$ADMIN_NAME" --role super_admin,specialist
if [ -s "$DIR/console/var/demo.db" ]; then
  ok "Simulated year already built" "rebuild: .venv/bin/python -m console demo-seed"
else
  run "Building the simulated year ($DEMO_MONTHS months, demo mode)" cons demo-seed --months "$DEMO_MONTHS"
fi
cat >"$STATE/env" <<EOF
# written by install.sh — read by scripts/mirqah-local
PORT=$PORT
READER_PORT=$READER_PORT
BIND=$BIND
TIER=$TIER
MODELS="${MODELS[*]:-}"
OLLAMA_URL=$OLLAMA_URL
OLLAMA_BIN="${OLLAMA:-}"
ADMIN_EMAIL=$ADMIN_EMAIL
EOF
chmod +x "$DIR/scripts/mirqah-local"
mkdir -p "$HOME/.local/bin" && ln -sfn "$DIR/scripts/mirqah-local" "$HOME/.local/bin/mirqah-local"
ok "Control command installed" "mirqah-local → $DIR/scripts/mirqah-local"
if [ $WITH_TESTS = 1 ]; then
  run "Running the test suite (pytest)" "$VPY" -m pytest -q -x
fi

# ══ 8. Start ═════════════════════════════════════════════════════════════════
step "Starting Mirqah"
if [ $START = 1 ]; then
  run "Starting the console and the reader" "$DIR/scripts/mirqah-local" restart --quiet
  run "Console health check" wait_http "http://127.0.0.1:$PORT/api/public" 30
  run "Reader health check" wait_http "http://127.0.0.1:$READER_PORT/fahras.html" 15
  if [ "$TIER" != none ]; then
    if cons llm-probe >>"$LOG" 2>&1; then ok "Console sees the AI engine"; else warn "Console could not reach the AI engine yet — see: mirqah-local logs ollama"; fi
  fi
else
  ok "Not started (--no-start)" "run: mirqah-local start"
fi
cp "$LOG" "$STATE/install.log" 2>/dev/null || true

# ══ done ═════════════════════════════════════════════════════════════════════
ELAPSED=$((SECONDS - T0))
HOST_HINT=$(hostname 2>/dev/null || echo this-host)
printf '\n    %s %s100%%%s\n' "$(bar 1 1 40)" "$MUT" "$R"
say ""
printf '  %s%s Mirqah is ready%s  %s(%dm %02ds)%s\n' "$GRN$B" "$OK" "$R" "$MUT" $((ELAPSED / 60)) $((ELAPSED % 60)) "$R"
say ""
L="$MUT│$R"
printf '  %s %s%-18s%s http://localhost:%s\n' "$L" "$B" "Committee console" "$R" "$PORT"
printf '  %s %-18s sign in with %s%s%s — mail is in mock mode,\n' "$L" "" "$GOLD" "$ADMIN_EMAIL" "$R"
printf '  %s %-18s so the one-time code appears on the screen.\n' "$L" ""
printf '  %s %s%-18s%s http://localhost:%s/fahras.html\n' "$L" "$B" "Public reader" "$R" "$READER_PORT"
printf '  %s %s%-18s%s %s\n' "$L" "$B" "AI tier" "$R" "$TIER_DESC"
printf '  %s %s%-18s%s Live | Demo switch in the top bar → Demo shows a simulated year\n' "$L" "$B" "Try first" "$R"
say ""
printf '  %sOn a server over SSH? Open a tunnel from your laptop, then use the links above:%s\n' "$MUT" "$R"
printf '    ssh -N -L %s:127.0.0.1:%s -L %s:127.0.0.1:%s %s@%s\n' "$PORT" "$PORT" "$READER_PORT" "$READER_PORT" "${USER:-you}" "$HOST_HINT"
say ""
printf '  %sManage:%s mirqah-local status · logs · stop · start · open · update · uninstall\n' "$B" "$R"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) printf '  %s(add ~/.local/bin to PATH, or run %s/scripts/mirqah-local)%s\n' "$MUT" "$DIR" "$R" ;; esac
printf '  %sDocs:%s %s/docs/INSTALL.md\n\n' "$B" "$R" "$DIR"
