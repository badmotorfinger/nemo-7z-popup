#!/usr/bin/env bash
# Installer for the Nemo 7-Zip popup action.
#
# Usage:
#   ./install.sh              # install
#   ./install.sh --uninstall  # remove
#
# Installs apt dependencies, copies the Nemo action files into
# ~/.local/share/nemo/actions/, merges the "7-Zip" submenu entry
# into ~/.config/nemo/actions-tree.json, and restarts Nemo.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
ACTIONS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/nemo/actions"
TREE_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/nemo/actions-tree.json"

APT_PACKAGES=(p7zip-full python3-gi gir1.2-gtk-3.0)

ACTION_FILES=(
  "7zip-add-to-archive@badmotorfinger.nemo_action"
  "7zip-quick-add-single-file@badmotorfinger.nemo_action"
  "7zip-quick-add-single-dir@badmotorfinger.nemo_action"
  "7zip-quick-add-multi@badmotorfinger.nemo_action"
)
SCRIPT_DIR_NAME="7zip-popup"
SUBMENU_UUID="7zip-submenu-badmotorfinger"

BOLD='\033[1m'; GREEN='\033[32m'; YELLOW='\033[33m'; RED='\033[31m'; RESET='\033[0m'
say()  { printf "${BOLD}==>${RESET} %s\n" "$*"; }
ok()   { printf "${GREEN}OK${RESET}  %s\n" "$*"; }
warn() { printf "${YELLOW}!!${RESET}  %s\n" "$*"; }
die()  { printf "${RED}ERR${RESET} %s\n" "$*" >&2; exit 1; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Required command '$1' not found in PATH."
}

is_pkg_installed() {
  dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q "install ok installed"
}

install_deps() {
  require_cmd dpkg-query
  require_cmd apt-get

  local missing=()
  for pkg in "${APT_PACKAGES[@]}"; do
    if is_pkg_installed "$pkg"; then
      ok "$pkg already installed"
    else
      missing+=("$pkg")
    fi
  done

  if [ "${#missing[@]}" -eq 0 ]; then
    return
  fi

  say "The following packages need to be installed via apt: ${missing[*]}"
  printf "    %s — provides the 7z command used to create archives\n" "p7zip-full"
  printf "    %s — Python GObject bindings (needed by the GTK dialogs)\n" "python3-gi"
  printf "    %s — GTK 3 typelib (needed by the GTK dialogs)\n" "gir1.2-gtk-3.0"
  printf "\nYou will be prompted for your sudo password to install them.\n\n"

  if [ "$(id -u)" -eq 0 ]; then
    apt-get update
    apt-get install -y "${missing[@]}"
  else
    local prompt="[sudo] password for %p — needed to apt-install ${missing[*]} for the Nemo 7-Zip menu: "
    sudo -p "$prompt" apt-get update
    sudo -p "$prompt" apt-get install -y "${missing[@]}"
  fi
}

install_action_files() {
  say "Copying action files to $ACTIONS_DIR"
  mkdir -p "$ACTIONS_DIR"

  # Sweep any stale 7zip-*@badmotorfinger.nemo_action files from previous
  # installs that no longer match the current ACTION_FILES list (e.g. files
  # that were renamed or split between versions).
  shopt -s nullglob
  for existing in "$ACTIONS_DIR"/7zip-*@badmotorfinger.nemo_action; do
    name="$(basename "$existing")"
    keep=0
    for f in "${ACTION_FILES[@]}"; do
      [ "$f" = "$name" ] && { keep=1; break; }
    done
    if [ "$keep" -eq 0 ]; then
      rm -f "$existing"
      warn "removed stale $name"
    fi
  done
  shopt -u nullglob

  for f in "${ACTION_FILES[@]}"; do
    [ -f "$REPO_DIR/$f" ] || die "Missing source file: $f"
    install -m 0644 "$REPO_DIR/$f" "$ACTIONS_DIR/$f"
    ok "installed $f"
  done

  rm -rf "$ACTIONS_DIR/$SCRIPT_DIR_NAME"
  cp -r "$REPO_DIR/$SCRIPT_DIR_NAME" "$ACTIONS_DIR/$SCRIPT_DIR_NAME"
  shopt -s nullglob
  for f in "$ACTIONS_DIR/$SCRIPT_DIR_NAME"/*.py "$ACTIONS_DIR/$SCRIPT_DIR_NAME"/*.sh; do
    chmod +x "$f"
  done
  shopt -u nullglob
  ok "installed $SCRIPT_DIR_NAME/"
}

merge_actions_tree() {
  say "Merging submenu entry into $TREE_FILE"
  mkdir -p "$(dirname "$TREE_FILE")"

  require_cmd python3

  TREE_FILE="$TREE_FILE" \
  SUBMENU_UUID="$SUBMENU_UUID" \
  NEW_TREE_JSON="$REPO_DIR/actions-tree.json" \
  python3 - <<'PY'
import json, os, sys
from pathlib import Path

target  = Path(os.environ["TREE_FILE"])
new_src = Path(os.environ["NEW_TREE_JSON"])
sub_id  = os.environ["SUBMENU_UUID"]

new_entries = json.loads(new_src.read_text())
our_entry   = next((e for e in new_entries if e.get("uuid") == sub_id), None)
if our_entry is None:
    sys.exit(f"ERR: {new_src} did not contain submenu uuid '{sub_id}'")

if target.exists() and target.stat().st_size > 0:
    existing = json.loads(target.read_text())
    if not isinstance(existing, list):
        sys.exit(f"ERR: {target} is not a JSON list")
    existing = [e for e in existing if e.get("uuid") != sub_id]
else:
    existing = []

existing.append(our_entry)
target.write_text(json.dumps(existing, indent=2) + "\n")
print(f"OK  wrote {target} ({len(existing)} top-level entries)")
PY
}

nemo_running() {
  # File-manager window
  pgrep -x nemo >/dev/null 2>&1 && return 0
  pidof nemo >/dev/null 2>&1 && return 0
  # Desktop daemon (handles desktop right-click menu, almost always running)
  pgrep -x nemo-desktop >/dev/null 2>&1 && return 0
  pidof nemo-desktop >/dev/null 2>&1 && return 0
  # Fallback: scan ps for either
  local comms
  comms="$(ps -e -o comm= 2>/dev/null)" || comms=""
  grep -Fxq nemo <<<"$comms" && return 0
  grep -Fxq nemo-desktop <<<"$comms" && return 0
  return 1
}

restart_nemo() {
  if ! nemo_running; then
    warn "Nemo doesn't appear to be running."
    warn "Start it (or log out/in) to pick up the new menu."
    return
  fi

  say "Restarting Nemo and nemo-desktop"
  # nemo --quit only quits the file-manager process. nemo-desktop is a
  # separate binary that owns the desktop right-click menu and caches the
  # action set independently, so it needs an explicit kill+relaunch.
  nemo --quit >/dev/null 2>&1 || true
  pkill -x nemo-desktop >/dev/null 2>&1 || true
  sleep 1
  (setsid nemo-desktop >/dev/null 2>&1 < /dev/null &) || true
  ok "Restarted. Open a new Nemo window to see the menu in file lists,"
  ok "or right-click on the desktop for the menu there."
}

uninstall_action_files() {
  say "Removing files from $ACTIONS_DIR"
  for f in "${ACTION_FILES[@]}"; do
    if [ -e "$ACTIONS_DIR/$f" ]; then
      rm -f "$ACTIONS_DIR/$f"
      ok "removed $f"
    fi
  done
  if [ -d "$ACTIONS_DIR/$SCRIPT_DIR_NAME" ]; then
    rm -rf "$ACTIONS_DIR/$SCRIPT_DIR_NAME"
    ok "removed $SCRIPT_DIR_NAME/"
  fi
}

remove_from_actions_tree() {
  [ -f "$TREE_FILE" ] || return 0
  say "Removing submenu entry from $TREE_FILE"
  TREE_FILE="$TREE_FILE" SUBMENU_UUID="$SUBMENU_UUID" python3 - <<'PY'
import json, os
from pathlib import Path
target = Path(os.environ["TREE_FILE"])
sub_id = os.environ["SUBMENU_UUID"]
data = json.loads(target.read_text())
data = [e for e in data if e.get("uuid") != sub_id]
target.write_text(json.dumps(data, indent=2) + "\n")
print(f"OK  wrote {target} ({len(data)} top-level entries)")
PY
}

case "${1:-install}" in
  install)
    install_deps
    install_action_files
    merge_actions_tree
    restart_nemo
    say "Done. Right-click a file/folder in Nemo → '7-Zip' submenu."
    ;;
  --uninstall|uninstall)
    uninstall_action_files
    remove_from_actions_tree
    restart_nemo
    say "Uninstalled. (apt packages ${APT_PACKAGES[*]} were left installed.)"
    ;;
  *)
    die "Unknown argument: $1   (use install or --uninstall)"
    ;;
esac
