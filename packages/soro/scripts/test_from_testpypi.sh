#!/usr/bin/env bash
# Build soro, upload to TestPyPI (optional), then install it into a clean venv
# and run the smoke test against the installed package.
#
#   scripts/test_from_testpypi.sh local              # build + test the wheel, no upload
#   scripts/test_from_testpypi.sh testpypi 0.1.0     # install that version from TestPyPI
#   EXTRAS=gemini,openai,webrtc scripts/test_from_testpypi.sh testpypi 0.1.0
#
# Upload itself (needs a TestPyPI token):  twine upload -r testpypi dist/*
set -euo pipefail

cd "$(dirname "$0")/.."
MODE="${1:-local}"
VERSION="${2:-}"
EXTRAS="${EXTRAS:-}"
VENV="$(mktemp -d)/venv"
SPEC="soro${EXTRAS:+[$EXTRAS]}"

python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip

if [ "$MODE" = "local" ]; then
  rm -rf dist
  "$VENV/bin/pip" install -q build twine
  "$VENV/bin/python" -m build -q
  "$VENV/bin/twine" check dist/*
  "$VENV/bin/pip" install -q "$SPEC @ file://$(ls -1 "$PWD"/dist/*.whl | head -1)"
else
  [ -n "$VERSION" ] || { echo "usage: $0 testpypi <version>"; exit 1; }
  # Dependencies (websockets, av, ...) are not on TestPyPI, so pull them from PyPI.
  "$VENV/bin/pip" install -q \
    --index-url https://test.pypi.org/simple/ \
    --extra-index-url https://pypi.org/simple/ \
    "$SPEC==$VERSION"
fi

# Run from a directory that does not contain the source tree.
cd "$(mktemp -d)"
"$VENV/bin/python" "$OLDPWD/scripts/smoke_test.py" ${EXTRAS:+--extras "$EXTRAS"}
"$VENV/bin/python" "$OLDPWD/examples/offline_note_taker.py"
"$VENV/bin/python" "$OLDPWD/examples/turn_detection.py"
echo "venv kept at $VENV"
