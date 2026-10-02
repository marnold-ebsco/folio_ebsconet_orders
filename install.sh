#!/usr/bin/env bash
# install.sh -- fetch and set up the EBSCONET -> FOLIO orders tool without cloning.
#
# Downloads the application pinned to one commit SHA (tests, dev docs and tooling
# are left out), builds a venv, and installs the pinned folio_orders_loader. Needs
# only curl, tar and Python 3.12+ (no git). Safe to re-run: with no flags it checks
# for a newer commit and upgrades in place, replacing app/ and leaving work/
# (config, .ini, out/) alone. The venv is reused unless the interpreter changes or
# --recreate-venv is passed.
#
# Both repos are public, so no token is needed. If they are ever made private
# again, set GITHUB_TOKEN (read access to folio_ebsconet_orders and
# folio_orders_loader); it is only sent to github.com. Unauthenticated GitHub API
# calls are limited to 60 per hour per IP.
#
# Usage:
#   curl -fsSL \
#     https://raw.githubusercontent.com/marnold-ebsco/folio_ebsconet_orders/main/install.sh | bash -s -- [options]
#   ./install.sh [options]
#
# Options:
#   --dir PATH         Install location (default: ./ebsconet in the current directory;
#                      use --dir . to install directly into it)
#   --python NAME      Python interpreter, 3.12+ (default: python3)
#   --ref REF          Branch or tag to install from (default: main)
#   --recreate-venv    Delete and rebuild the venv even if one exists
#   --check            Only report whether an update is available; change nothing
#   -h, --help         Show this help
#
# Layout under --dir:
#   app/             application code (replaced on every install/upgrade)
#   venv/            virtualenv with the dependencies
#   work/            your working folder: config, .ini files and out/ live here
#                    (config is seeded once and never overwritten)
#   bin/ebsconet     command wrapper; also linked into ~/.local/bin

set -euo pipefail

REPO="marnold-ebsco/folio_ebsconet_orders"
INSTALL_DIR="$PWD/ebsconet"
PYTHON="${PYTHON:-python3}"
REF="main"
RECREATE_VENV=0
CHECK_ONLY=0

VERSION_MARKER=".ebsconet_install_version"
INTERPRETER_MARKER=".ebsconet_interpreter"

usage() {
  sed -n '/^# Usage:/,/^set -euo/p' "$0" | sed '$d; s/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir|--prefix) INSTALL_DIR="$2"; shift 2 ;;
    --python) PYTHON="$2"; shift 2 ;;
    --ref) REF="$2"; shift 2 ;;
    --recreate-venv) RECREATE_VENV=1; shift ;;
    --check) CHECK_ONLY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

# The command wrapper embeds INSTALL_DIR, so it must be absolute (e.g. --dir .).
INSTALL_DIR="$(realpath -m "$INSTALL_DIR")"

need() {
  command -v "$1" >/dev/null 2>&1 || { echo "Error: '$1' is required but not found on PATH." >&2; exit 1; }
}
need curl
need tar
need "$PYTHON"

"$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null || {
  echo "Error: Python 3.12 or newer is required (found: $("$PYTHON" -V 2>&1))." >&2
  echo "Pass --python /path/to/python3.12 if it is installed elsewhere." >&2
  exit 1
}

"$PYTHON" -c 'import venv, ensurepip' 2>/dev/null || {
  echo "Error: this Python cannot create virtual environments (venv/ensurepip missing)." >&2
  echo "On Debian/Ubuntu install it with:  sudo apt install python3-venv" >&2
  echo "(or python3.12-venv for a specific version), then re-run this script." >&2
  exit 1
}

# curl against api.github.com, authenticated when GITHUB_TOKEN is set.
gh_curl() {
  local auth=()
  [[ -n "${GITHUB_TOKEN:-}" ]] && auth=(-H "Authorization: Bearer ${GITHUB_TOKEN}")
  curl -fsSL "${auth[@]}" -H "Accept: application/vnd.github+json" "$@"
}

resolve_sha() {
  gh_curl "https://api.github.com/repos/$1/commits/$2" \
    | "$PYTHON" -c "import json,sys; print(json.load(sys.stdin)['sha'])"
}


echo "Resolving latest commit for ${REPO}@${REF}..."
REMOTE_SHA="$(resolve_sha "$REPO" "$REF")"
echo "Latest commit: ${REMOTE_SHA}"

LOCAL_SHA=""
[[ -f "${INSTALL_DIR}/${VERSION_MARKER}" ]] && LOCAL_SHA="$(cat "${INSTALL_DIR}/${VERSION_MARKER}")"

if [[ -n "$LOCAL_SHA" && "$LOCAL_SHA" == "$REMOTE_SHA" ]]; then
  echo "Already up to date (${LOCAL_SHA})."
  if [[ "$CHECK_ONLY" -eq 1 ]]; then exit 0; fi
elif [[ -n "$LOCAL_SHA" ]]; then
  echo "Update available: ${LOCAL_SHA} -> ${REMOTE_SHA}"
  if [[ "$CHECK_ONLY" -eq 1 ]]; then exit 0; fi
else
  echo "No existing install found at ${INSTALL_DIR}; installing fresh."
  if [[ "$CHECK_ONLY" -eq 1 ]]; then exit 0; fi
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "Fetching application pinned to ${REMOTE_SHA}..."
gh_curl "https://api.github.com/repos/${REPO}/tarball/${REMOTE_SHA}" -o "$TMP/app.tar.gz"
mkdir -p "$TMP/app"
# Same files the old bundle shipped: no tests, tooling or dev-only docs.
tar -xzf "$TMP/app.tar.gz" -C "$TMP/app" --strip-components=1 \
  --exclude='*/tests' --exclude='*/packaging' --exclude='*/.flake8' \
  --exclude='*/requirements-dev.txt' --exclude='*/HANDOFF.md' \
  --exclude='*/EBSCOnet.code-workspace' --exclude='*/install.sh'
echo "${REMOTE_SHA}" > "$TMP/app/VERSION"

mkdir -p "${INSTALL_DIR}/bin" "${INSTALL_DIR}/work"
echo "Installing application code..."
rm -rf "${INSTALL_DIR}/app"
cp -r "$TMP/app" "${INSTALL_DIR}/app"

# The loader is pinned in requirements.txt as git+ssh; fetch the same tag as a
# tarball over HTTPS instead so neither git nor an SSH key is needed.
LOADER_SPEC="$(grep -E '^folio_orders_loader[[:space:]]*@' "${INSTALL_DIR}/app/requirements.txt" | head -n1)"
[[ -n "$LOADER_SPEC" ]] || { echo "Error: folio_orders_loader pin not found in requirements.txt." >&2; exit 1; }
read -r LOADER_REPO LOADER_TAG < <(
  printf '%s\n' "$LOADER_SPEC" \
    | sed -E 's|.*github\.com[:/]([^@]+)\.git@(.+)$|\1 \2|; s|.*github\.com[:/]([^@ ]+)@(.+)$|\1 \2|'
)
grep -vE '^folio_orders_loader[[:space:]]*@' "${INSTALL_DIR}/app/requirements.txt" > "$TMP/requirements.txt"

echo "Fetching folio_orders_loader ${LOADER_TAG}..."
gh_curl "https://api.github.com/repos/${LOADER_REPO}/tarball/${LOADER_TAG}" -o "$TMP/loader.tar.gz"

VENV_DIR="${INSTALL_DIR}/venv"
PREV_INTERPRETER=""
[[ -f "${INSTALL_DIR}/${INTERPRETER_MARKER}" ]] && PREV_INTERPRETER="$(cat "${INSTALL_DIR}/${INTERPRETER_MARKER}")"
if [[ -n "$PREV_INTERPRETER" && "$PREV_INTERPRETER" != "$PYTHON" ]]; then
  echo "Interpreter changed (${PREV_INTERPRETER} -> ${PYTHON}); rebuilding venv."
  RECREATE_VENV=1
fi
if [[ "$RECREATE_VENV" -eq 1 && -d "$VENV_DIR" ]]; then
  rm -rf "$VENV_DIR"
fi

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  echo "Creating venv at ${VENV_DIR}..."
  "$PYTHON" -m venv "$VENV_DIR"
else
  echo "Reusing existing venv at ${VENV_DIR}."
fi
echo "${PYTHON}" > "${INSTALL_DIR}/${INTERPRETER_MARKER}"

echo "Installing dependencies..."
"${VENV_DIR}/bin/python" -m pip install --quiet --upgrade pip
"${VENV_DIR}/bin/python" -m pip install --quiet -r "$TMP/requirements.txt"
# Always reinstalled so changed code under an unchanged version number is not skipped.
"${VENV_DIR}/bin/python" -m pip install --quiet --force-reinstall --no-deps "$TMP/loader.tar.gz"

# Seed the working folder once; never overwrite the user's copies.
[[ -e "${INSTALL_DIR}/work/ebsconet_config.json" ]] || \
  cp "${INSTALL_DIR}/app/ebsconet_config.json" "${INSTALL_DIR}/work/ebsconet_config.json"
[[ -e "${INSTALL_DIR}/work/sample.ini" ]] || \
  cp "${INSTALL_DIR}/app/sample.ini" "${INSTALL_DIR}/work/sample.ini"

# Wrapper: runs from the caller's current folder, so relative config/.ini/out paths
# behave as documented. Use it from work/ (or any folder holding your config).
cat > "${INSTALL_DIR}/bin/ebsconet" <<EOF
#!/usr/bin/env bash
export PYTHONPATH="${INSTALL_DIR}/app\${PYTHONPATH:+:\$PYTHONPATH}"
exec "${VENV_DIR}/bin/python" "${INSTALL_DIR}/app/ebsconet.py" "\$@"
EOF
chmod +x "${INSTALL_DIR}/bin/ebsconet"
# Interactive helper that builds work/ebsconet_config.json from the tenant's real codes.
cat > "${INSTALL_DIR}/bin/ebsconet-configure" <<EOF
#!/usr/bin/env bash
exec "${VENV_DIR}/bin/python" "${INSTALL_DIR}/app/bin/ebsconet_configure.py" "\$@"
EOF
chmod +x "${INSTALL_DIR}/bin/ebsconet-configure"
mkdir -p "$HOME/.local/bin"
ln -sf "${INSTALL_DIR}/bin/ebsconet" "$HOME/.local/bin/ebsconet"
ln -sf "${INSTALL_DIR}/bin/ebsconet-configure" "$HOME/.local/bin/ebsconet-configure"

# Put ~/.local/bin on PATH for future shells (idempotent), and tell the user if the
# current shell needs a reload.
PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'
PATH_NOTE=""
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *)
    for rc in "$HOME/.bashrc" "$HOME/.profile"; do
      [[ -f "$rc" ]] || continue
      grep -qF "$PATH_LINE" "$rc" || printf '\n# added by ebsconet install.sh\n%s\n' "$PATH_LINE" >> "$rc"
    done
    [[ -f "$HOME/.bashrc" || -f "$HOME/.profile" ]] || \
      printf '%s\n' "$PATH_LINE" > "$HOME/.profile"
    PATH_NOTE="  source ~/.bashrc               # or open a new shell, so ebsconet is on PATH"
    ;;
esac

echo "${REMOTE_SHA}" > "${INSTALL_DIR}/${VERSION_MARKER}"

# $0 is "bash" when run via `curl | bash -s --`, so it is not a usable path to
# re-invoke -- fall back to re-fetching via curl in that case.
case "$0" in
  *install.sh) RERUN_CMD="$0" ;;
  *) RERUN_CMD="curl -fsSL https://raw.githubusercontent.com/${REPO}/main/install.sh | bash -s --" ;;
esac

cat <<EOF

Done. ebsconet (commit ${REMOTE_SHA:0:12}, loader ${LOADER_TAG}) is ready at:
  ${INSTALL_DIR}

Configure and run:
  cd "${INSTALL_DIR}/work"
  cp sample.ini <tenant>.ini     # fill in; never commit or copy credentials around
${PATH_NOTE}
  ebsconet-configure             # pick the tenant's real codes for ebsconet_config.json
  ebsconet --help

Check for updates later without changing anything:
  ${RERUN_CMD} --dir "${INSTALL_DIR}" --check

Apply an update in place (work/ is left alone):
  ${RERUN_CMD} --dir "${INSTALL_DIR}"
EOF
