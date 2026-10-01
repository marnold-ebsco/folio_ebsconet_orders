#!/usr/bin/env bash
# Build a self-contained install bundle (run on the dev machine, not the EC2).
#
#   packaging/make_bundle.sh            -> dist/ebsconet-<version>.tar.gz
#
# The bundle holds the committed application files (git archive, so no .ini files,
# out/ or tests), a wheelhouse of every dependency (including folio_orders_loader,
# fetched with your SSH key here), and install.sh. The EC2 needs only Python 3.12+,
# not git, an SSH key or a clone of the repo.
set -euo pipefail
shopt -s extglob nullglob

cd "$(dirname "$0")/.."
PY="${PYTHON:-.venv/bin/python}"
VERSION="$(git describe --tags --always --dirty)"
NAME="ebsconet-${VERSION}"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

mkdir -p "$STAGE/$NAME/app" "$STAGE/$NAME/wheelhouse" dist

# Application files: tracked files only, minus tests, tooling and dev-only docs.
git archive HEAD | tar -x -C "$STAGE/$NAME/app" \
    --exclude='tests' --exclude='packaging' --exclude='.flake8' \
    --exclude='requirements-dev.txt' --exclude='HANDOFF.md' \
    --exclude='EBSCOnet.code-workspace'
echo "$VERSION" > "$STAGE/$NAME/app/VERSION"

# Dependencies as wheels (builds the git-hosted loader into a wheel as well).
"$PY" -m pip download --quiet -r requirements.txt -d "$STAGE/$NAME/wheelhouse"
for sdist in "$STAGE/$NAME"/wheelhouse/*.@(tar.gz|zip); do
    [ -e "$sdist" ] || continue
    "$PY" -m pip wheel --quiet --no-deps -w "$STAGE/$NAME/wheelhouse" "$sdist"
    rm -f "$sdist"
done

# The loader is installed from its bundled wheel, not from git, on the EC2.
LOADER_WHL="$(basename "$(ls "$STAGE/$NAME"/wheelhouse/folio_orders_loader-*.whl)")"
LOADER_VER="$(echo "$LOADER_WHL" | cut -d- -f2)"
sed -i -E "s|^folio_orders_loader @.*|folio_orders_loader==$LOADER_VER|" "$STAGE/$NAME/app/requirements.txt"

cp packaging/install.sh "$STAGE/$NAME/install.sh"
chmod +x "$STAGE/$NAME/install.sh"

tar -C "$STAGE" -czf "dist/${NAME}.tar.gz" "$NAME"
echo "Built dist/${NAME}.tar.gz"
echo "Copy to the EC2:  scp dist/${NAME}.tar.gz ec2-host:"
echo "Then there:       tar xzf ${NAME}.tar.gz && ${NAME}/install.sh"
