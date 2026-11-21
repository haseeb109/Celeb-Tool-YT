#!/usr/bin/env bash
# DocForge installer — macOS (Apple Silicon). Jo pehle se installed hai usay skip karta hai.
set -e
cd "$(dirname "$0")"
say(){ printf "\n\033[1;31m▶ %s\033[0m\n" "$1"; }

if ! command -v brew >/dev/null; then
  say "Homebrew install"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  eval "$(/opt/homebrew/bin/brew shellenv)"
fi
for pkg in ffmpeg yt-dlp uv; do
  if command -v "$pkg" >/dev/null; then echo "✔ $pkg"; else say "brew install $pkg"; brew install "$pkg"; fi
done
# Subtitles burn karne ke liye ffmpeg mein libass chahiye (Homebrew ffmpeg mein hota hai)
# HyperFrames (optional overlay engine) ke liye Node 22+
if ! command -v node >/dev/null; then say "brew install node (optional, HyperFrames ke liye)"; brew install node || true; fi

say "Python env (.venv)"
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
[ -f .env ] || { cp .env.example .env; echo "→ .env bana di, apni keys daal do"; }
mkdir -p assets/music assets/fonts jobs output
say "Check"
.venv/bin/python run.py doctor || true
echo -e "\nUI:   .venv/bin/python app.py\nCLI:  .venv/bin/python run.py run"
