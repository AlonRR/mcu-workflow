#!/bin/sh
# mcu-workflow bootstrap installer (POSIX: bash/zsh, Git-Bash, WSL, macOS, Linux).
#
# One-liner:
#   curl -fsSL https://raw.githubusercontent.com/AlonRR/mcu-workflow/main/install.sh | sh
#
# It installs uv (a standalone binary - no Python needed), uses uv to get a
# Python, clones this repo, runs `mcuflow doctor --fix` (which provisions the
# Python deps into a project .venv plus Docker/usbipd/the ESP-IDF cage image on
# supported hosts), and adds `mcuflow` to your PATH.
#
# Override the source repo or install location:
#   MCUFLOW_REPO=https://github.com/you/fork.git MCUFLOW_HOME=~/tools/mcuflow sh install.sh
set -eu

REPO="${MCUFLOW_REPO:-https://github.com/AlonRR/mcu-workflow.git}"
DEST="${MCUFLOW_HOME:-$HOME/mcu-workflow}"
PYVER="3.12"

say() { printf '\033[1;36m[mcuflow]\033[0m %s\n' "$1"; }

# 1. uv (standalone; installs without Python).
if ! command -v uv >/dev/null 2>&1; then
  say "installing uv ..."
  curl -fsSL https://astral.sh/uv/install.sh | sh
fi
# Make uv visible in this shell whether it landed in ~/.local/bin or ~/.cargo/bin.
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

# 2. A managed Python (used only to bootstrap; the tool then builds its own .venv).
say "ensuring Python $PYVER ..."
uv python install "$PYVER" >/dev/null 2>&1 || true

# 3. Fetch the repo (git if available, else a source tarball).
if [ -d "$DEST/.git" ]; then
  say "updating existing checkout at $DEST ..."
  git -C "$DEST" pull --ff-only || true
elif command -v git >/dev/null 2>&1; then
  say "cloning into $DEST ..."
  git clone --depth 1 "$REPO" "$DEST"
else
  say "git not found - downloading source archive ..."
  mkdir -p "$DEST"
  curl -fsSL "${REPO%.git}/archive/refs/heads/main.tar.gz" \
    | tar -xz -C "$DEST" --strip-components=1
fi

# 4. Provision everything via the tool's own self-install.
say "provisioning prerequisites (doctor --fix) ..."
uv run --no-project --python "$PYVER" -- \
  python "$DEST/src/mcuflow/mcuflow.py" doctor --fix || \
  say "doctor --fix reported issues (often just Docker needing a manual start) - re-run 'mcuflow doctor --fix' after."

# 5. Put mcuflow on PATH for future shells.
BIN="$DEST/bin"
case ":$PATH:" in
  *":$BIN:"*) ;;
  *)
    added=0
    for rc in "$HOME/.profile" "$HOME/.bashrc" "$HOME/.zshrc"; do
      [ -f "$rc" ] || continue
      if ! grep -q 'mcu-workflow/bin' "$rc" 2>/dev/null; then
        printf '\n# mcu-workflow\nexport PATH="%s:$PATH"\n' "$BIN" >> "$rc"
        added=1
      fi
    done
    [ "$added" = 1 ] || say "add to PATH manually: export PATH=\"$BIN:\$PATH\""
    ;;
esac

say "done. Open a new terminal (or 'source ~/.profile'), then run:  mcuflow doctor"
