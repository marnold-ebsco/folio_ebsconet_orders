#!/usr/bin/env bash
# Install the EBSCONET -> FOLIO orders tool from an unpacked bundle.
#
#   ./install.sh [--prefix DIR] [--python PYTHON]
#
# Default prefix is ~/ebsconet. Layout:
#   PREFIX/app/      application code (replaced on every install/upgrade)
#   PREFIX/venv/     virtualenv with the dependencies
#   PREFIX/work/     your working folder: config, .ini files and out/ live here
#                    (the config is seeded once and never overwritten)
#   PREFIX/bin/ebsconet   command wrapper; also linked into ~/.local/bin
# Re-running upgrades the code and dependencies and leaves PREFIX/work alone.
set -euo pipefail

PREFIX="$HOME/ebsconet"
PYTHON="${PYTHON:-python3}"
while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX="$2"; shift 2 ;;
        --python) PYTHON="$2"; shift 2 ;;
        -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

HERE="$(cd "$(dirname "$0")" && pwd)"

"$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null || {
    echo "Python 3.12 or newer is required (found: $("$PYTHON" -V 2>&1))." >&2
    echo "Pass --python /path/to/python3.12 if it is installed elsewhere." >&2
    exit 1
}

mkdir -p "$PREFIX/bin" "$PREFIX/work"

# Code: replace wholesale so removed files do not linger.
rm -rf "$PREFIX/app"
cp -r "$HERE/app" "$PREFIX/app"

# Virtualenv + dependencies from the bundled wheelhouse. PyPI is only a fallback
# for a wheel that does not match this machine's platform.
[ -x "$PREFIX/venv/bin/python" ] || "$PYTHON" -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/python" -m pip install --quiet --upgrade \
    --find-links "$HERE/wheelhouse" -r "$PREFIX/app/requirements.txt"
# The loader is reinstalled every time so changed code under an unchanged version
# number cannot be skipped by pip.
"$PREFIX/venv/bin/python" -m pip install --quiet --force-reinstall --no-deps \
    --no-index --find-links "$HERE/wheelhouse" folio_orders_loader

# Seed the working folder once.
[ -e "$PREFIX/work/ebsconet_config.json" ] || \
    cp "$PREFIX/app/ebsconet_config.json" "$PREFIX/work/ebsconet_config.json"
[ -e "$PREFIX/work/sample.ini" ] || cp "$PREFIX/app/sample.ini" "$PREFIX/work/sample.ini"

# Wrapper: runs from the caller's current folder, so relative config/.ini/out paths
# behave as documented. Use it from PREFIX/work (or any folder holding your config).
cat > "$PREFIX/bin/ebsconet" <<EOF
#!/usr/bin/env bash
export PYTHONPATH="$PREFIX/app\${PYTHONPATH:+:\$PYTHONPATH}"
exec "$PREFIX/venv/bin/python" "$PREFIX/app/ebsconet.py" "\$@"
EOF
chmod +x "$PREFIX/bin/ebsconet"
mkdir -p "$HOME/.local/bin"
ln -sf "$PREFIX/bin/ebsconet" "$HOME/.local/bin/ebsconet"

echo "Installed $(cat "$PREFIX/app/VERSION") to $PREFIX"
echo "Next:  cd $PREFIX/work"
echo "       cp sample.ini <tenant>.ini   # fill in; never commit or copy credentials around"
echo "       ebsconet --help              # (add ~/.local/bin to PATH if not found)"
