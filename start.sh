#!/usr/bin/env bash
# Celeb Tool YT launcher — terminal mein sirf:  celeb
cd "$(dirname "$0")"
PY=.venv/bin/python
open_tool(){ echo "▶ Tool khul raha hai… (band karne ke liye Ctrl+C)"; $PY app.py; }
update_tool(){
  echo "▶ Update…"
  git pull --ff-only || { echo "✖ Update fail"; return 1; }
  uv pip install --python $PY -r requirements.txt -q && echo "✔ Updated"
}
case "$1" in
  open) open_tool; exit;;
  update) update_tool; exit;;
  run) $PY run.py run; exit;;
esac
echo ""
echo "  🎬 Celeb Tool YT"
echo "  ─────────────────────────"
echo "  1) Open tool (GUI)"
echo "  2) Update tool"
echo "  3) Update + Open"
echo "  4) Queue chalao bina GUI (bulk, terminal mein)"
echo "  5) System check (doctor)"
echo "  6) Exit"
echo ""
read -r -p "  Number chuno [1]: " c
case "${c:-1}" in
  1) open_tool;;
  2) update_tool;;
  3) update_tool && open_tool;;
  4) $PY run.py run;;
  5) $PY run.py doctor;;
  *) exit 0;;
esac
