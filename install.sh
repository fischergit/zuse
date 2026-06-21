#!/usr/bin/env bash
# ============================================================================
# Zuse Installer
# ============================================================================
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/fischergit/zuse/main/install.sh | bash
#   ./install.sh --dir ~/.zuse/zuse-agent --skip-setup
# ============================================================================

set -euo pipefail

if [ -n "${PYTHONPATH:-}" ]; then
  echo "⚠ Ignoring inherited PYTHONPATH during install"
  unset PYTHONPATH
fi
if [ -n "${PYTHONHOME:-}" ]; then
  echo "⚠ Ignoring inherited PYTHONHOME during install"
  unset PYTHONHOME
fi

GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

REPO_URL="${ZUSE_REPO_URL:-https://github.com/fischergit/zuse.git}"
ARCHIVE_URL_BASE="${ZUSE_ARCHIVE_URL_BASE:-https://github.com/fischergit/zuse/archive/refs/heads}"
BRANCH="${ZUSE_BRANCH:-main}"
INSTALL_DIR="${ZUSE_INSTALL_DIR:-$HOME/.zuse/zuse-agent}"
ZUSE_HOME="${ZUSE_HOME:-$HOME/.zuse}"
PYTHON_VERSION="${ZUSE_PYTHON_VERSION:-3.11}"
RUN_SETUP=true
SKIP_BROWSER=false
NON_INTERACTIVE=false
USE_CURRENT_DIR=false

log() { echo -e "${CYAN}→${NC} $*" >&2; }
ok() { echo -e "${GREEN}✓${NC} $*" >&2; }
warn() { echo -e "${YELLOW}⚠${NC} $*" >&2; }
err() { echo -e "${RED}✗${NC} $*" >&2; }

usage() {
  cat <<EOF
Zuse Installer

Usage: install.sh [OPTIONS]

Options:
  --dir PATH           Installation directory (default: ~/.zuse/zuse-agent)
  --repo URL           Git repository URL (default: $REPO_URL)
  --archive-base URL   Archive base URL for git-free installs
                       (default: $ARCHIVE_URL_BASE)
  --branch NAME        Git branch (default: main)
  --zuse-home PATH     Zuse data/config directory (default: ~/.zuse)
  --skip-setup         Do not run the setup wizard
  --skip-browser       Do not install Playwright Chromium
  --python VERSION     Python version to use/bootstrap with uv
                       (default: $PYTHON_VERSION; 3.11 avoids greenlet source builds)
  --non-interactive    Avoid prompts; create default config/env only
  --current-dir        Install from the directory containing this script
  -h, --help           Show this help
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dir) INSTALL_DIR="$2"; shift 2 ;;
    --repo) REPO_URL="$2"; shift 2 ;;
    --archive-base) ARCHIVE_URL_BASE="$2"; shift 2 ;;
    --branch) BRANCH="$2"; shift 2 ;;
    --zuse-home) ZUSE_HOME="$2"; shift 2 ;;
    --skip-setup) RUN_SETUP=false; shift ;;
    --skip-browser) SKIP_BROWSER=true; shift ;;
    --python) PYTHON_VERSION="$2"; shift 2 ;;
    --non-interactive) NON_INTERACTIVE=true; shift ;;
    --current-dir) USE_CURRENT_DIR=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) err "Unknown option: $1"; usage; exit 1 ;;
  esac
done

print_banner() {
  echo ""
  echo -e "${BOLD}${CYAN}┌──────────────────────────────────────────────┐${NC}"
  echo -e "${BOLD}${CYAN}│              Zuse Installer                  │${NC}"
  echo -e "${BOLD}${CYAN}└──────────────────────────────────────────────┘${NC}"
  echo ""
}

python_matches_version() {
  local py="$1"
  "$py" - "$PYTHON_VERSION" <<'PY' >/dev/null 2>&1
import sys
want = tuple(int(p) for p in sys.argv[1].split('.')[:2])
have = sys.version_info[:2]
raise SystemExit(0 if have == want else 1)
PY
}

python_is_supported() {
  local py="$1"
  "$py" <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if (3, 10) <= sys.version_info[:2] < (3, 13) else 1)
PY
}

find_python() {
  # Prefer the requested Python line (default 3.11). Very new macOS/Python
  # versions can force packages such as greenlet to build from source, which
  # fails on machines without Xcode/CLT. Python 3.11 has broad prebuilt wheels.
  for cmd in python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
      local py
      py="$(command -v "$cmd")"
      if python_matches_version "$py"; then
        echo "$py"
        return 0
      fi
    fi
  done
  return 1
}

find_supported_python() {
  for cmd in python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
      local py
      py="$(command -v "$cmd")"
      if python_is_supported "$py"; then
        echo "$py"
        return 0
      fi
    fi
  done
  return 1
}

find_uv() {
  if command -v uv >/dev/null 2>&1; then
    command -v uv
  elif [ -x "$HOME/.local/bin/uv" ]; then
    echo "$HOME/.local/bin/uv"
  elif [ -x "$HOME/.cargo/bin/uv" ]; then
    echo "$HOME/.cargo/bin/uv"
  else
    return 1
  fi
}

install_uv() {
  local uv_installer uv_log
  uv_installer="$(mktemp 2>/dev/null || echo "/tmp/zuse-uv-installer.$$.sh")"
  uv_log="$(mktemp 2>/dev/null || echo "/tmp/zuse-uv-install.$$.log")"
  log "Installing uv to bootstrap missing dependencies"
  if command -v curl >/dev/null 2>&1; then
    if ! curl -LsSf https://astral.sh/uv/install.sh -o "$uv_installer" 2>"$uv_log"; then
      err "Failed to download uv installer."
      sed 's/^/    /' "$uv_log" >&2 || true
      rm -f "$uv_installer" "$uv_log"
      return 1
    fi
  elif command -v python3 >/dev/null 2>&1; then
    python3 - https://astral.sh/uv/install.sh "$uv_installer" <<'PY'
import sys
from urllib.request import urlopen
url, target = sys.argv[1], sys.argv[2]
with urlopen(url, timeout=60) as response, open(target, "wb") as out:
    out.write(response.read())
PY
  else
    err "Need curl to bootstrap uv when Python is missing."
    rm -f "$uv_installer" "$uv_log"
    return 1
  fi
  if ! sh "$uv_installer" >>"$uv_log" 2>&1; then
    err "Failed to install uv."
    sed 's/^/    /' "$uv_log" >&2 || true
    rm -f "$uv_installer" "$uv_log"
    return 1
  fi
  rm -f "$uv_installer" "$uv_log"
  find_uv
}

ensure_uv() {
  find_uv || install_uv
}

ensure_python() {
  local py uv_cmd
  py="$(find_python || true)"
  if [ -n "$py" ]; then
    echo "$py"
    return 0
  fi

  py="$(find_supported_python || true)"
  if [ -n "$py" ]; then
    warn "Found $($py --version 2>&1), but installing Python $PYTHON_VERSION to avoid source builds for binary packages"
  else
    warn "Python $PYTHON_VERSION not found; installing it with uv (no xcrun required)"
  fi
  uv_cmd="$(ensure_uv)" || return 1
  "$uv_cmd" python install "$PYTHON_VERSION"
  # --system avoids resolving to a project-local .venv interpreter. Without it,
  # `uv python find` returns ./.venv/bin/python3 when run from an install dir
  # that already has a venv; create_venv then deletes that very interpreter.
  "$uv_cmd" python find --system "$PYTHON_VERSION"
}

create_venv() {
  local py="$1"
  # Guard against deleting the interpreter we're about to use: if $py lives
  # inside the .venv we're about to remove, re-resolve to a managed Python.
  case "$py" in
    "$PWD/.venv/"*|.venv/*)
      warn "Interpreter $py is inside the target .venv; re-resolving"
      UV_CMD="$(ensure_uv)" || return 1
      "$UV_CMD" python install "$PYTHON_VERSION"
      py="$("$UV_CMD" python find --system "$PYTHON_VERSION")"
      ;;
  esac
  rm -rf .venv
  if "$py" -m venv .venv >/dev/null 2>&1; then
    ok "Virtual environment created with stdlib venv"
    return 0
  fi

  warn "python -m venv failed; creating virtual environment with uv"
  UV_CMD="$(ensure_uv)" || return 1
  "$UV_CMD" venv .venv --python "$py" --seed
}

ensure_path_line() {
  local rc="$1"
  local line="$2"
  mkdir -p "$(dirname "$rc")"
  touch "$rc"
  if ! grep -Fqx "$line" "$rc"; then
    printf '\n%s\n' "$line" >> "$rc"
    ok "Updated $rc"
  fi
}

copy_tree() {
  local src="$1"
  local dst="$2"
  rm -rf "$dst"
  mkdir -p "$dst"
  (cd "$src" && tar -cf - .) | (cd "$dst" && tar -xf -)
}

download_archive() {
  local url="$1"
  local target="$2"
  if command -v curl >/dev/null 2>&1; then
    curl -fL "$url" -o "$target"
  elif command -v python3 >/dev/null 2>&1; then
    python3 - "$url" "$target" <<'PY'
import sys
from urllib.request import urlopen
url, target = sys.argv[1], sys.argv[2]
with urlopen(url, timeout=60) as response, open(target, "wb") as out:
    out.write(response.read())
PY
  else
    err "Need curl or python3 to download Zuse without git."
    return 1
  fi
}

install_from_archive() {
  local archive_url="${ARCHIVE_URL_BASE%/}/${BRANCH}.tar.gz"
  local tmp_dir archive root_dir
  tmp_dir="$(mktemp -d 2>/dev/null || mktemp -d -t zuse-install)"
  archive="$tmp_dir/zuse.tar.gz"
  log "Downloading Zuse archive without git: $archive_url"
  download_archive "$archive_url" "$archive"
  tar -xzf "$archive" -C "$tmp_dir"
  root_dir="$(find "$tmp_dir" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  if [ -z "$root_dir" ] || [ ! -f "$root_dir/pyproject.toml" ]; then
    err "Downloaded archive does not look like the Zuse repository."
    rm -rf "$tmp_dir"
    exit 1
  fi
  copy_tree "$root_dir" "$INSTALL_DIR"
  rm -rf "$tmp_dir"
}

install_shell_snippets() {
  local bin_dir="$HOME/.local/bin"
  mkdir -p "$bin_dir"
  ln -sfn "$INSTALL_DIR/.venv/bin/zuse" "$bin_dir/zuse"
  ln -sfn "$INSTALL_DIR/.venv/bin/zuse-web" "$bin_dir/zuse-web"
  ln -sfn "$INSTALL_DIR/.venv/bin/zuse-setup" "$bin_dir/zuse-setup"
  ln -sfn "$INSTALL_DIR/.venv/bin/zuse-telegram" "$bin_dir/zuse-telegram"
  ln -sfn "$INSTALL_DIR/.venv/bin/zuse-whatsapp" "$bin_dir/zuse-whatsapp"

  local rc="$HOME/.zshrc"
  [ -n "${ZSH_VERSION:-}" ] || [ -f "$HOME/.zshrc" ] || rc="$HOME/.bashrc"
  ensure_path_line "$rc" 'export PATH="$HOME/.local/bin:$PATH"'
  ensure_path_line "$rc" '[ -f "$HOME/.zuse/env" ] && source "$HOME/.zuse/env"'
}

print_banner
mkdir -p "$ZUSE_HOME"
export ZUSE_HOME

if [ "$USE_CURRENT_DIR" = true ]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  INSTALL_DIR="$SCRIPT_DIR"
  log "Installing from current directory: $INSTALL_DIR"
elif [ -d "$INSTALL_DIR/.git" ] && command -v git >/dev/null 2>&1; then
  log "Updating existing checkout in $INSTALL_DIR"
  if git -C "$INSTALL_DIR" fetch --depth 1 origin "$BRANCH" && \
     git -C "$INSTALL_DIR" checkout "$BRANCH" && \
     git -C "$INSTALL_DIR" pull --ff-only origin "$BRANCH"; then
    ok "Repository updated via git"
  else
    warn "Git update failed; falling back to archive download (no xcrun required)"
    install_from_archive
  fi
else
  log "Installing Zuse to $INSTALL_DIR"
  if command -v git >/dev/null 2>&1; then
    if git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"; then
      ok "Repository cloned via git"
    else
      warn "Git clone failed; falling back to archive download (no xcrun required)"
      install_from_archive
    fi
  else
    warn "git not found; using archive download (no xcrun required)"
    install_from_archive
  fi
fi

cd "$INSTALL_DIR"

PYTHON_BIN="$(ensure_python || true)"
if [ -z "$PYTHON_BIN" ]; then
  err "Could not find or install Python $PYTHON_VERSION. Install Python manually and rerun install.sh."
  exit 1
fi
ok "Python found: $($PYTHON_BIN --version 2>&1)"

log "Creating virtual environment"
create_venv "$PYTHON_BIN"
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel

log "Installing Zuse"
EXTRAS="mac,browser,whatsapp"

install_editable() {
  # --only-binary=greenlet forbids compiling greenlet (pulled in transitively
  # by playwright) from source. On a Python/platform without a prebuilt
  # greenlet wheel this fails fast with a clean resolver error instead of
  # invoking the C compiler, which needs Xcode CLT and otherwise dies with
  # "failed building wheel for greenlet". The clean failure lets us fall back
  # to a uv-managed Python that does have wheels.
  python -m pip install --only-binary=greenlet -e ".[${EXTRAS}]"
}

if ! install_editable; then
  warn "Install failed — no prebuilt greenlet wheel for this Python/platform; retrying on uv-managed Python $PYTHON_VERSION"
  deactivate 2>/dev/null || true
  UV_CMD="$(ensure_uv)" || exit 1
  "$UV_CMD" python install "$PYTHON_VERSION"
  PYTHON_BIN="$($UV_CMD python find --system "$PYTHON_VERSION")"
  create_venv "$PYTHON_BIN"
  # shellcheck disable=SC1091
  source .venv/bin/activate
  python -m pip install --upgrade pip setuptools wheel
  if ! install_editable; then
    err "greenlet has no prebuilt wheel even on Python $PYTHON_VERSION on this platform."
    err "Install Xcode Command Line Tools ('xcode-select --install') and rerun install.sh."
    exit 1
  fi
fi
ok "Zuse package installed"

if [ "$SKIP_BROWSER" = false ]; then
  if python -c 'import playwright' >/dev/null 2>&1; then
    log "Installing Playwright Chromium"
    python -m playwright install chromium || warn "Playwright Chromium install failed; browser tools can be installed later"
  fi
fi

install_shell_snippets

if [ "$RUN_SETUP" = true ]; then
  log "Running Zuse setup wizard"
  if [ "$NON_INTERACTIVE" = true ] || [ ! -t 0 ]; then
    zuse-setup --non-interactive
  else
    zuse-setup
  fi
fi

ok "Installation complete"
echo ""
echo "Commands:"
echo "  zuse          Terminal REPL"
echo "  zuse-web      WebGUI"
echo "  zuse-setup    Setup wizard"
echo "  zuse-whatsapp WhatsApp bridge"
echo "  zuse-telegram Telegram bot"
echo ""
echo "If your shell does not find zuse yet, run: source ~/.zshrc"
