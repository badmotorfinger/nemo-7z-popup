#!/usr/bin/env bash
# Installer for the Nemo 7-Zip popup action.
#   ./install.sh              # install
#   ./install.sh --uninstall  # remove
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
POPUP_DIR="7zip-popup"
SUBMENU_UUID="7zip-submenu-badmotorfinger"

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }
die() { printf '\033[31mERR\033[0m %s\n' "$*" >&2; exit 1; }

install_deps() {
  local missing=()
  for pkg in "${APT_PACKAGES[@]}"; do
    dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed" || missing+=("$pkg")
  done
  [ "${#missing[@]}" -eq 0 ] && return

  say "Installing for the Nemo 7-Zip menu: ${missing[*]}"
  if [ "$(id -u)" -eq 0 ]; then
    apt-get update && apt-get install -y "${missing[@]}"
  else
    local p="[sudo] password for %p - to apt-install ${missing[*]} for the Nemo 7-Zip menu: "
    sudo -p "$p" apt-get update && sudo -p "$p" apt-get install -y "${missing[@]}"
  fi
}

install_action_files() {
  say "Copying action files to $ACTIONS_DIR"
  mkdir -p "$ACTIONS_DIR"

  # Stale sweep: drop old 7zip-*@badmotorfinger actions no longer in our set.
  shopt -s nullglob
  for existing in "$ACTIONS_DIR"/7zip-*@badmotorfinger.nemo_action; do
    name="$(basename "$existing")"
    printf '%s\n' "${ACTION_FILES[@]}" | grep -qxF "$name" || { rm -f "$existing"; say "removed stale $name"; }
  done
  shopt -u nullglob

  for f in "${ACTION_FILES[@]}"; do
    [ -f "$REPO_DIR/$f" ] || die "Missing source file: $f"
    install -m 0644 "$REPO_DIR/$f" "$ACTIONS_DIR/$f"
  done

  rm -rf "${ACTIONS_DIR:?}/$POPUP_DIR"
  cp -r "$REPO_DIR/$POPUP_DIR" "$ACTIONS_DIR/$POPUP_DIR"
  chmod +x "$ACTIONS_DIR/$POPUP_DIR"/*.py
}

merge_actions_tree() {
  say "Merging submenu entry into $TREE_FILE"
  mkdir -p "$(dirname "$TREE_FILE")"
  TREE_FILE="$TREE_FILE" SUBMENU_UUID="$SUBMENU_UUID" SRC="$REPO_DIR/actions-tree.json" python3 - <<'PY'
import json, os, sys
from pathlib import Path
target, src, sub = Path(os.environ["TREE_FILE"]), Path(os.environ["SRC"]), os.environ["SUBMENU_UUID"]
ours = next((e for e in json.loads(src.read_text()) if e.get("uuid") == sub), None)
if ours is None: sys.exit(f"ERR: {src} missing submenu uuid '{sub}'")
existing = json.loads(target.read_text()) if target.exists() and target.stat().st_size else []
if not isinstance(existing, list): sys.exit(f"ERR: {target} is not a JSON list")
existing = [e for e in existing if e.get("uuid") != sub] + [ours]
target.write_text(json.dumps(existing, indent=2) + "\n")
print(f"OK  wrote {target} ({len(existing)} top-level entries)")
PY
}

remove_from_actions_tree() {
  [ -f "$TREE_FILE" ] || return 0
  say "Removing submenu entry from $TREE_FILE"
  TREE_FILE="$TREE_FILE" SUBMENU_UUID="$SUBMENU_UUID" python3 - <<'PY'
import json, os
from pathlib import Path
target, sub = Path(os.environ["TREE_FILE"]), os.environ["SUBMENU_UUID"]
data = [e for e in json.loads(target.read_text()) if e.get("uuid") != sub]
target.write_text(json.dumps(data, indent=2) + "\n")
print(f"OK  wrote {target} ({len(data)} top-level entries)")
PY
}

uninstall_action_files() {
  say "Removing files from $ACTIONS_DIR"
  for f in "${ACTION_FILES[@]}"; do rm -f "$ACTIONS_DIR/$f"; done
  rm -rf "${ACTIONS_DIR:?}/$POPUP_DIR"
}

nemo_running() {
  pgrep -x nemo >/dev/null 2>&1 || pgrep -x nemo-desktop >/dev/null 2>&1
}

restart_nemo() {
  if ! nemo_running; then
    say "Nemo isn't running - start it (or log out/in) to pick up the new menu."
    return
  fi
  # nemo --quit only stops the file manager; nemo-desktop owns the desktop
  # menu and caches actions separately, so kill+relaunch it too.
  say "Restarting nemo and nemo-desktop"
  nemo --quit >/dev/null 2>&1 || true
  pkill -x nemo-desktop >/dev/null 2>&1 || true
  sleep 1
  (setsid nemo-desktop >/dev/null 2>&1 </dev/null &) || true
}

case "${1:-install}" in
  install)
    install_deps
    install_action_files
    merge_actions_tree
    restart_nemo
    say "Done. Right-click a file or folder in Nemo to use the 7-Zip actions."
    ;;
  --uninstall|uninstall)
    uninstall_action_files
    remove_from_actions_tree
    restart_nemo
    say "Uninstalled. (apt packages ${APT_PACKAGES[*]} left installed.)"
    ;;
  *)
    die "Unknown argument: $1   (use install or --uninstall)"
    ;;
esac
