#!/bin/bash
# ============================================================
#  KIRO AI - Auto Installer v3.0
#  Supports: Ubuntu, Debian, CentOS, RHEL, AlmaLinux, Rocky,
#            Amazon Linux, Arch Linux (all versions)
#  Architecture: x86_64, ARM64
# ============================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║        KIRO AI - Auto Installer v3.0                 ║${NC}"
echo -e "${CYAN}║        Ubuntu/Debian/CentOS/RHEL/Alma/Rocky/Arch     ║${NC}"
echo -e "${CYAN}║        x86_64 & ARM64 supported                      ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════╝${NC}"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Detect Architecture ────────────────────────────────────
ARCH=$(uname -m)
echo -e "${YELLOW}[1/9] Detecting system...${NC}"

if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS_NAME="${NAME:-Unknown}"
    OS_ID="${ID:-unknown}"
    OS_VER="${VERSION_ID:-unknown}"
    echo -e "  ${GREEN}✓${NC} OS: $OS_NAME ($OS_ID $OS_VER)"
else
    OS_ID="unknown"
    OS_NAME="Unknown"
    echo -e "  ${YELLOW}⚠${NC} OS not detected via os-release"
fi

echo -e "  ${GREEN}✓${NC} Architecture: $ARCH"

# Detect package manager
if command -v apt-get &>/dev/null; then
    PKG_MAN="apt"
elif command -v dnf &>/dev/null; then
    PKG_MAN="dnf"
elif command -v yum &>/dev/null; then
    PKG_MAN="yum"
elif command -v pacman &>/dev/null; then
    PKG_MAN="pacman"
elif command -v apk &>/dev/null; then
    PKG_MAN="apk"
else
    echo -e "  ${RED}✗${NC} No supported package manager found!"
    echo -e "  Supported: apt, dnf, yum, pacman, apk"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} Package Manager: $PKG_MAN"

# Helper: install packages based on detected package manager
sys_install() {
    if [ "$PKG_MAN" = "apt" ]; then
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$@" 2>/dev/null
    elif [ "$PKG_MAN" = "dnf" ]; then
        dnf install -y -q "$@" 2>/dev/null
    elif [ "$PKG_MAN" = "yum" ]; then
        yum install -y -q "$@" 2>/dev/null
    elif [ "$PKG_MAN" = "pacman" ]; then
        pacman -S --noconfirm --quiet "$@" 2>/dev/null
    elif [ "$PKG_MAN" = "apk" ]; then
        apk add --quiet "$@" 2>/dev/null
    fi
}

# ── Update System ──────────────────────────────────────────
echo -e "${YELLOW}[2/9] Updating system packages...${NC}"
if [ "$PKG_MAN" = "apt" ]; then
    apt-get update -qq 2>/dev/null || true
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq wget curl gnupg2 ca-certificates apt-transport-https 2>/dev/null || true
elif [ "$PKG_MAN" = "dnf" ] || [ "$PKG_MAN" = "yum" ]; then
    $PKG_MAN makecache -q 2>/dev/null || true
    $PKG_MAN install -y -q wget curl gnupg2 ca-certificates 2>/dev/null || true
elif [ "$PKG_MAN" = "pacman" ]; then
    pacman -Sy --noconfirm 2>/dev/null || true
    pacman -S --noconfirm wget curl gnupg ca-certificates 2>/dev/null || true
elif [ "$PKG_MAN" = "apk" ]; then
    apk update --quiet 2>/dev/null || true
    apk add --quiet wget curl gnupg ca-certificates 2>/dev/null || true
fi
echo -e "  ${GREEN}✓${NC} System updated"

# ── Install Python ─────────────────────────────────────────
echo -e "${YELLOW}[3/9] Installing Python & pip...${NC}"

# Map Python package names per OS
if [ "$PKG_MAN" = "apt" ]; then
    sys_install python3 python3-pip python3-dev python3-venv
elif [ "$PKG_MAN" = "dnf" ] || [ "$PKG_MAN" = "yum" ]; then
    sys_install python3 python3-pip python3-devel
elif [ "$PKG_MAN" = "pacman" ]; then
    sys_install python python-pip
elif [ "$PKG_MAN" = "apk" ]; then
    sys_install python3 py3-pip python3-dev
fi

# Verify Python
if command -v python3 &>/dev/null; then
    PYTHON_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
    echo -e "  ${GREEN}✓${NC} Python $PYTHON_VER"
elif command -v python &>/dev/null; then
    # Arch Linux: python is python3
    ln -sf "$(which python)" /usr/local/bin/python3 2>/dev/null || true
    PYTHON_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
    echo -e "  ${GREEN}✓${NC} Python $PYTHON_VER"
else
    echo -e "  ${RED}✗${NC} Python installation failed!"
    exit 1
fi

# Ensure pip works
if ! python3 -m pip --version &>/dev/null; then
    echo -e "  ${YELLOW}⚠${NC} pip not working, installing ensurepip..."
    python3 -m ensurepip --upgrade 2>/dev/null || true
fi
echo -e "  ${GREEN}✓${NC} pip ready"

# ── Install Chrome ─────────────────────────────────────────
echo -e "${YELLOW}[4/9] Installing Google Chrome...${NC}"

# Detect Chrome binary (check all possible names)
CHROME_BIN=""
for cb in google-chrome-stable google-chrome chromium-browser chromium; do
    if command -v "$cb" &>/dev/null; then
        CHROME_BIN="$cb"
        break
    fi
done

if [ -n "$CHROME_BIN" ]; then
    CHROME_VER=$("$CHROME_BIN" --version 2>/dev/null | sed 's/[^0-9.]//g' | cut -d. -f1)
    echo -e "  ${GREEN}✓${NC} Browser already installed: $CHROME_BIN v$CHROME_VER"
else
    echo -e "  ${YELLOW}  Installing Chrome...${NC}"

    # Install Chrome dependencies per OS
    if [ "$PKG_MAN" = "apt" ]; then
        # Try multiple dependency name variants (Ubuntu 24.04 uses libasound2t64)
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
            libgtk-3-0 libgbm1 libnss3 libxss1 libasound2 libxshmfence1 \
            libatk1.0-0 libatk-bridge2.0-0 libcups2 libdbus-1-3 \
            libdrm2 libxcomposite1 libxdamage1 libxrandr2 libxfixes3 \
            libxkbcommon0 libpango-1.0-0 libcairo2 libasound2t64 \
            xdg-utils 2>/dev/null || \
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
            libgtk-3-0 libgbm-dev libnss3 libxss1 libasound2 \
            xdg-utils 2>/dev/null || \
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
            libgtk-3-0 libnss3 xdg-utils 2>/dev/null || true
    elif [ "$PKG_MAN" = "dnf" ] || [ "$PKG_MAN" = "yum" ]; then
        sys_install gtk3 libXScrnSaver alsa-lib pango nss atk at-spi2-atk cups-libs libdrm libxkbcommon libXcomposite libXdamage libXrandr libXfixes
    elif [ "$PKG_MAN" = "pacman" ]; then
        sys_install gtk3 nss alsa-lib libxss
    elif [ "$PKG_MAN" = "apk" ]; then
        sys_install chromium nss freetype harfbuzz
    fi

    # Download Chrome based on architecture
    if [ "$ARCH" = "x86_64" ] || [ "$ARCH" = "amd64" ]; then
        if [ "$PKG_MAN" = "apt" ]; then
            wget -q -O /tmp/chrome.deb "https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb" 2>/dev/null
            if [ -f /tmp/chrome.deb ]; then
                dpkg -i /tmp/chrome.deb 2>/dev/null || DEBIAN_FRONTEND=noninteractive apt-get install -f -y -qq 2>/dev/null || true
                rm -f /tmp/chrome.deb
            fi
        elif [ "$PKG_MAN" = "dnf" ] || [ "$PKG_MAN" = "yum" ]; then
            wget -q -O /tmp/chrome.rpm "https://dl.google.com/linux/direct/google-chrome-stable_current_x86_64.rpm" 2>/dev/null
            if [ -f /tmp/chrome.rpm ]; then
                $PKG_MAN localinstall -y -q /tmp/chrome.rpm 2>/dev/null || true
                rm -f /tmp/chrome.rpm
            fi
        elif [ "$PKG_MAN" = "pacman" ]; then
            sys_install google-chrome
        elif [ "$PKG_MAN" = "apk" ]; then
            sys_install chromium
        fi
    elif [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
        # ARM: use Chromium (Chrome doesn't have official ARM builds for Linux)
        echo -e "  ${YELLOW}  ARM detected, installing Chromium...${NC}"
        if [ "$PKG_MAN" = "apt" ]; then
            sys_install chromium-browser chromium || sys_install chromium
        elif [ "$PKG_MAN" = "dnf" ] || [ "$PKG_MAN" = "yum" ]; then
            sys_install chromium
        elif [ "$PKG_MAN" = "pacman" ]; then
            sys_install chromium
        elif [ "$PKG_MAN" = "apk" ]; then
            sys_install chromium
        fi
    fi

    # Verify Chrome installed
    for cb in google-chrome-stable google-chrome chromium-browser chromium; do
        if command -v "$cb" &>/dev/null; then
            CHROME_BIN="$cb"
            CHROME_VER=$("$CHROME_BIN" --version 2>/dev/null | sed 's/[^0-9.]//g' | cut -d. -f1)
            echo -e "  ${GREEN}✓${NC} Browser installed: $CHROME_BIN v$CHROME_VER"
            break
        fi
    done

    if [ -z "$CHROME_BIN" ]; then
        echo -e "  ${RED}✗${NC} Chrome/Chromium installation failed!"
        echo -e "  ${YELLOW}  Manual install: https://www.google.com/chrome/${NC}"
    fi
fi

# ── Install Xvfb, Tesseract, FFmpeg ────────────────────────
echo -e "${YELLOW}[5/9] Installing Xvfb, Tesseract OCR, FFmpeg & Flac...${NC}"

if [ "$PKG_MAN" = "apt" ]; then
    sys_install xvfb tesseract-ocr ffmpeg flac
elif [ "$PKG_MAN" = "dnf" ] || [ "$PKG_MAN" = "yum" ]; then
    # Enable EPEL & RPM Fusion for ffmpeg
    $PKG_MAN install -y -q epel-release 2>/dev/null || true
    $PKG_MAN localinstall -y -q "https://download1.rpmfusion.org/free/el/rpmfusion-free-release-$(rpm -E %rhel 2>/dev/null || echo 9).noarch.rpm" 2>/dev/null || true
    sys_install xorg-x11-server-Xvfb tesseract ffmpeg flac
elif [ "$PKG_MAN" = "pacman" ]; then
    sys_install xorg-server-xvfb tesseract ffmpeg flac
elif [ "$PKG_MAN" = "apk" ]; then
    sys_install xvfb tesseract-ocr ffmpeg flac
fi

# Verify
if command -v Xvfb &>/dev/null; then
    echo -e "  ${GREEN}✓${NC} Xvfb"
else
    echo -e "  ${YELLOW}⚠${NC} Xvfb not found (may need manual install)"
fi
if command -v tesseract &>/dev/null; then
    echo -e "  ${GREEN}✓${NC} Tesseract: $(tesseract --version 2>&1 | head -1)"
else
    echo -e "  ${YELLOW}⚠${NC} Tesseract not found"
fi
if command -v ffmpeg &>/dev/null; then
    echo -e "  ${GREEN}✓${NC} FFmpeg: $(ffmpeg -version 2>&1 | head -1)"
else
    echo -e "  ${YELLOW}⚠${NC} FFmpeg not found"
fi

# ── Install Python Packages ────────────────────────────────
echo -e "${YELLOW}[6/9] Installing Python packages...${NC}"

# Detect if pip supports --break-system-packages
PIP_FLAGS=""
if python3 -m pip install --help 2>/dev/null | grep -q "break-system-packages"; then
    PIP_FLAGS="--break-system-packages"
fi

# Install packages one by one with proper error handling
PIP_PACKAGES="undetected-chromedriver selenium httpx pyvirtualdisplay Pillow ddddocr pytesseract rich SpeechRecognition pydub"

for pkg in $PIP_PACKAGES; do
    echo -ne "  Installing ${pkg}..."
    # Try multiple strategies
    python3 -m pip install $PIP_FLAGS --ignore-installed "$pkg" 2>/dev/null || \
    python3 -m pip install $PIP_FLAGS "$pkg" 2>/dev/null || \
    python3 -m pip install --user "$pkg" 2>/dev/null || \
    pip3 install $PIP_FLAGS "$pkg" 2>/dev/null || \
    pip3 install "$pkg" 2>/dev/null || true
    echo -e " ${GREEN}✓${NC}"
done

echo -e "  ${GREEN}✓${NC} All Python packages installed"

# ── Verify & Auto-Fix ──────────────────────────────────────
echo -e "${YELLOW}[7/9] Verifying installations...${NC}"

# Map: import_test | pip_package_name
VERIFY_LIST=(
    "import undetected_chromedriver|undetected-chromedriver"
    "import selenium|selenium"
    "import httpx|httpx"
    "from pyvirtualdisplay import Display|pyvirtualdisplay"
    "import ddddocr|ddddocr"
    "import pytesseract|pytesseract"
    "from PIL import Image|Pillow"
    "from rich.console import Console|rich"
    "import speech_recognition|SpeechRecognition"
    "from pydub import AudioSegment|pydub"
)

FAILED_COUNT=0
for entry in "${VERIFY_LIST[@]}"; do
    IMPORT_TEST="${entry%%|*}"
    PIP_NAME="${entry##*|}"
    if python3 -c "$IMPORT_TEST" 2>/dev/null; then
        echo -e "  ${GREEN}✓${NC} $PIP_NAME"
    else
        echo -e "  ${YELLOW}⚠${NC} $PIP_NAME missing - auto-fixing..."
        python3 -m pip install $PIP_FLAGS --ignore-installed "$PIP_NAME" 2>/dev/null || \
        python3 -m pip install $PIP_FLAGS "$PIP_NAME" 2>/dev/null || \
        pip3 install "$PIP_NAME" 2>/dev/null || true
        if python3 -c "$IMPORT_TEST" 2>/dev/null; then
            echo -e "  ${GREEN}✓${NC} $PIP_NAME (fixed)"
        else
            echo -e "  ${RED}✗${NC} $PIP_NAME - FAILED"
            FAILED_COUNT=$((FAILED_COUNT + 1))
        fi
    fi
done

# ── Verify System Binaries ─────────────────────────────────
echo ""
echo -e "${YELLOW}[8/9] Verifying system binaries...${NC}"

if [ -n "$CHROME_BIN" ]; then
    echo -e "  ${GREEN}✓${NC} Browser: $CHROME_BIN"
else
    echo -e "  ${RED}✗${NC} No browser found"
    FAILED_COUNT=$((FAILED_COUNT + 1))
fi

if command -v tesseract &>/dev/null; then
    echo -e "  ${GREEN}✓${NC} Tesseract OCR"
else
    echo -e "  ${RED}✗${NC} Tesseract OCR not found"
    FAILED_COUNT=$((FAILED_COUNT + 1))
fi

if command -v Xvfb &>/dev/null; then
    echo -e "  ${GREEN}✓${NC} Xvfb (Virtual Display)"
else
    echo -e "  ${RED}✗${NC} Xvfb not found"
    FAILED_COUNT=$((FAILED_COUNT + 1))
fi

if command -v ffmpeg &>/dev/null; then
    echo -e "  ${GREEN}✓${NC} FFmpeg (Audio CAPTCHA)"
else
    echo -e "  ${YELLOW}⚠${NC} FFmpeg not found (audio CAPTCHA disabled)"
fi

# ── Final Report ───────────────────────────────────────────
echo -e "${YELLOW}[9/9] Final report...${NC}"
echo ""

if [ "$FAILED_COUNT" -eq 0 ]; then
    echo -e "${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║          ✓ ALL CHECKS PASSED                        ║${NC}"
    echo -e "${GREEN}║          Ready to run kiro.py                       ║${NC}"
    echo -e "${GREEN}╠══════════════════════════════════════════════════════╣${NC}"
    echo -e "${GREEN}║                                                      ║${NC}"
    echo -e "${GREEN}║  Run:  python3 kiro.py                               ║${NC}"
    echo -e "${GREEN}║                                                      ║${NC}"
    echo -e "${GREEN}║  Examples:                                           ║${NC}"
    echo -e "${GREEN}║    python3 kiro.py              # All accounts       ║${NC}"
    echo -e "${GREEN}║    python3 kiro.py 5            # 5 accounts         ║${NC}"
    echo -e "${GREEN}║    python3 kiro.py all 3        # 3 threads          ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
else
    echo -e "${YELLOW}╔══════════════════════════════════════════════════════╗${NC}"
    echo -e "${YELLOW}║    ⚠ $FAILED_COUNT ISSUE(S) DETECTED                      ║${NC}"
    echo -e "${YELLOW}║    Script may still work with reduced functionality ║${NC}"
    echo -e "${YELLOW}╠══════════════════════════════════════════════════════╣${NC}"
    echo -e "${YELLOW}║                                                      ║${NC}"
    echo -e "${YELLOW}║  Run:  python3 kiro.py                               ║${NC}"
    echo -e "${YELLOW}║                                                      ║${NC}"
    echo -e "${YELLOW}║  If errors occur, check: kiro.log                   ║${NC}"
    echo -e "${YELLOW}╚══════════════════════════════════════════════════════╝${NC}"
fi

echo ""
