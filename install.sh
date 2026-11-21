#!/usr/bin/env bash
# DocForge installer — macOS (Apple Silicon). Jo pehle se installed hai usay skip karta hai.
set -e
set -o pipefail
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

# Local vision model (style analysis) — free, 16GB RAM par chal jata hai
if ! command -v ollama >/dev/null; then say "brew install ollama"; brew install ollama || true; fi
if command -v ollama >/dev/null; then
  (brew services start ollama >/dev/null 2>&1 || (ollama serve >/dev/null 2>&1 &)); sleep 3
  ollama list | grep -q "qwen2.5vl:7b" || { say "ollama pull qwen2.5vl:7b (~6GB, ek dafa)"; ollama pull qwen2.5vl:7b || true; }
fi

say "Python env (.venv)"
[ -x .venv/bin/python ] || uv venv --python 3.12 .venv
export UV_HTTP_TIMEOUT=300
# Core packages — inke baghair tool nahi chalta. Network toote to 3 dafa retry.
for i in 1 2 3; do
  uv pip install --python .venv/bin/python -r requirements.txt && break
  echo "⚠ download fail (internet?) — retry $i/3 in 10s"; sleep 10
  [ $i = 3 ] && { echo "✖ Core install fail. Internet check karke ./install.sh dobara chalao."; exit 1; }
done
# Optional: mlx-whisper (clip edges word-level precise; torch ~ bara download). Fail ho to tool phir bhi chalta hai.
uv pip install --python .venv/bin/python mlx-whisper || echo "⚠ mlx-whisper install nahi hua (optional) — baad mein: uv pip install --python .venv/bin/python mlx-whisper"
[ -f .env ] || { cp .env.example .env; echo "→ .env bana di, apni keys daal do"; }
mkdir -p assets/music assets/fonts jobs output
# Terminal command:  celeb
LINE="alias celeb='$(pwd)/start.sh'"
grep -q "alias celeb=" ~/.zshrc 2>/dev/null || { echo "$LINE" >> ~/.zshrc; echo "✔ 'celeb' command add (naya terminal kholo)"; }
say "Check"
.venv/bin/python run.py doctor || true
echo -e "\nAb naya Terminal kholo aur likho:  celeb"
