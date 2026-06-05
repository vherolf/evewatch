#!/usr/bin/env bash
# evewatch installer / updater
# Usage (one-liner):
#   curl -fsSL https://raw.githubusercontent.com/vherolf/evewatch/main/install.sh | bash
# Or download and run directly:
#   bash install.sh

set -euo pipefail

REPO_RAW="https://raw.githubusercontent.com/vherolf/evewatch/main"
INSTALL_DIR="$(pwd)"
CONFIG_FILE="$HOME/.evewatch.json"

# ── colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}[evewatch]${NC} $*"; }
success() { echo -e "${GREEN}[evewatch]${NC} $*"; }
warn()    { echo -e "${YELLOW}[evewatch]${NC} $*"; }
die()     { echo -e "${RED}[evewatch] ERROR:${NC} $*" >&2; exit 1; }

# ── dependency checks ─────────────────────────────────────────────────────────
command -v python3 >/dev/null 2>&1 || die "python3 not found. Install Python 3.10 or newer."
command -v curl    >/dev/null 2>&1 || die "curl not found."

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}{sys.version_info.minor}")')
(( PYTHON_VERSION >= 310 )) || die "Python 3.10+ required (found $(python3 --version))."

# ── download project files ────────────────────────────────────────────────────
info "Installing into: $INSTALL_DIR"

for FILE in evewatch.py requirements.txt; do
    info "Downloading $FILE ..."
    curl -fsSL "$REPO_RAW/$FILE" -o "$INSTALL_DIR/$FILE"
done

success "Files downloaded."

# ── virtual environment ───────────────────────────────────────────────────────
VENV_DIR="$INSTALL_DIR/venv"

if [[ -d "$VENV_DIR" ]]; then
    info "Updating existing virtual environment ..."
else
    info "Creating virtual environment ..."
    python3 -m venv "$VENV_DIR"
fi

info "Installing dependencies ..."
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"
success "Dependencies installed."

# ── first-run: config setup ───────────────────────────────────────────────────
if [[ ! -f "$CONFIG_FILE" ]]; then
    info "Creating config file: $CONFIG_FILE"

    cat > "$CONFIG_FILE" <<'EOF'
{
  "client_id":    "",
  "character_id": 0,
  "watch_jumps":  5,
  "usernames":    ["YourCharacterName"],
  "token":        {}
}
EOF

    echo ""
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}  First-time setup — you need two things:${NC}"
    echo ""
    echo -e "  ${CYAN}1. ESI Client ID${NC}"
    echo "     → Go to:  https://developers.eveonline.com"
    echo "     → Log in and click 'Create New Application'"
    echo "     → Name: anything you like (e.g. evewatch)"
    echo "     → Connection Type: Authentication & API Access"
    echo "     → Scope:    esi-location.read_location.v1"
    echo "     → Callback: http://localhost:8765/callback"
    echo "     → Save and copy the Client ID into \"client_id\""
    echo ""
    echo -e "  ${CYAN}2. Character ID${NC}"
    echo "     → In the EVE client: Esc → About → copy the Character ID number"
    echo "     → Or look yourself up on:  https://zkillboard.com"
    echo "     → Paste the number (no quotes) into \"character_id\""
    echo ""
    echo -e "  ${CYAN}3. Your character name${NC}"
    echo "     → Put your in-game name in the \"usernames\" list"
    echo "     → This triggers an alert when someone mentions you in chat"
    echo ""
    echo -e "  ${CYAN}4. watch_jumps${NC}"
    echo "     → How many jumps around you to watch for hostiles (default: 5)"
    echo ""
    echo "  Leave \"token\" as {} — it is filled in automatically on first login."
    echo ""
    echo -e "${YELLOW}  Config file: $CONFIG_FILE${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    # open in the best available editor
    EDITOR_CMD=""
    for candidate in "$EDITOR" nano vim vi; do
        if [[ -n "$candidate" ]] && command -v "$candidate" >/dev/null 2>&1; then
            EDITOR_CMD="$candidate"
            break
        fi
    done

    if [[ -n "$EDITOR_CMD" ]]; then
        info "Opening config in $EDITOR_CMD — fill in your credentials, save, then run evewatch."
        "$EDITOR_CMD" "$CONFIG_FILE"
    else
        warn "No terminal editor found. Edit $CONFIG_FILE manually before running."
    fi
else
    info "Config already exists at $CONFIG_FILE — skipping first-run setup."
fi

# ── done ──────────────────────────────────────────────────────────────────────
echo ""
success "Installation complete."
echo ""
echo -e "  To run:   ${CYAN}$VENV_DIR/bin/python $INSTALL_DIR/evewatch.py${NC}"
echo -e "  Or add an alias to your shell config:"
echo -e "  ${CYAN}alias evewatch='$VENV_DIR/bin/python $INSTALL_DIR/evewatch.py'${NC}"
echo ""
