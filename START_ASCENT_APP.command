#!/bin/bash
cd "$(dirname "$0")"

echo "========================================"
echo "   ASCENT PDP REPORT GENERATOR"
echo "========================================"
echo ""

PYTHON="$(command -v python3)"
if [ -z "$PYTHON" ]; then
  echo "Python 3 is not installed."
  echo "Install Python 3, then double-click this file again."
  read -p "Press Enter to close..."
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "First-time setup: creating the app environment..."
  "$PYTHON" -m venv .venv || {
    echo "Could not create the Python environment."
    read -p "Press Enter to close..."
    exit 1
  }
fi

source .venv/bin/activate

if ! python -c "import streamlit" >/dev/null 2>&1; then
  echo "First-time setup: installing the app..."
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt || {
    echo ""
    echo "Installation failed. Please take a screenshot of this window."
    read -p "Press Enter to close..."
    exit 1
  }
fi

echo ""
echo "Opening Ascent PDP Report Generator..."
echo "Keep this window open while you use the app."
echo ""
python -m streamlit run app.py
