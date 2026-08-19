#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${PYTHON_BIN:-python3}"
clean_build=0
with_torrent=0

usage() {
  echo "Usage: bash scripts/build.sh [--clean] [--with-torrent] [--python PATH]"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --clean)
      clean_build=1
      shift
      ;;
    --with-torrent)
      with_torrent=1
      shift
      ;;
    --python)
      if [[ $# -lt 2 ]]; then
        usage
        exit 2
      fi
      python_bin="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

cd "$project_root"
"$python_bin" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 'AniRSS requires Python 3.11+')"
version="$("$python_bin" -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])")"
release_notes="RELEASE_NOTES-$version.md"
if [[ ! -f "$release_notes" ]]; then
  echo "Missing release notes: $release_notes" >&2
  exit 1
fi

install_target=".[packaging]"
if [[ $with_torrent -eq 1 ]]; then
  install_target=".[packaging,torrent]"
fi

echo "Installing AniRSS build dependencies from $install_target ..."
"$python_bin" -m pip install -e "$install_target"

pyinstaller_args=(--noconfirm)
if [[ $clean_build -eq 1 ]]; then
  pyinstaller_args+=(--clean)
fi

echo "Building AniRSS ..."
ANIRSS_BUNDLE_TORRENT="$with_torrent" \
  "$python_bin" -m PyInstaller "${pyinstaller_args[@]}" AniRSS.spec

bundle_root="$project_root/dist/AniRSS"
cp LICENSE QUICKSTART.txt "$release_notes" THIRD_PARTY_NOTICES.md "$bundle_root/"
mkdir -p "$bundle_root/licenses"
cp -R resources/licenses/. "$bundle_root/licenses/"

echo "Build complete: $project_root/dist/AniRSS"

if [[ $with_torrent -eq 1 ]]; then
  echo "BT was requested; verify libtorrent loads on a clean target system before release."
fi
