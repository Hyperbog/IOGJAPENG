#!/usr/bin/env bash
# Runs SNESRecomp's *original-ROM-verified* generator and native compiler.
# Requires a Japanese scaffold and its initialized framework submodules.
set -euo pipefail
usage() {
  cat <<'HELP'
Usage: build_jp_native.sh --rom /path/to/original_jp.sfc --project /path/to/JapaneseScaffold

Use the SNESRecomp scaffold first, not Babel's USA repository:
  sh snesrecomp/tools/new_project/setup_project.sh \
    --rom /path/to/original_jp.sfc --dir /path/to/ports \
    --name 'Gaia Gensouki Japan' --players 1 --yes \
    --no-recomp-ui --no-ci --no-github --no-generate --no-build

The script verifies the ROM SHA-256 and scaffold identity before touching
project files. The ROM is never copied. A successful build does not establish
emulation accuracy; validate captured frames against a reference emulator.
HELP
}
rom=""; project=""
while (( $# )); do
  case "$1" in
    --rom) rom="${2:-}"; shift 2;;
    --project) project="${2:-}"; shift 2;;
    -h|--help) usage; exit 0;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2;;
  esac
done
[[ -n "$rom" && -n "$project" ]] || { usage >&2; exit 2; }
rom="$(realpath "$rom")"
project="$(realpath "$project")"
source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -f "$project/snesrecomp/snesrecomp_cli.py" ]]; then
  echo 'SNESRecomp framework submodule missing: initialize the scaffold submodules.' >&2
  exit 1
fi
python3 "$source_dir/integrate_jp_native.py" --rom "$rom" --project "$project"
(
  cd "$project"
  ./tools/regen.sh --rom "$rom" --cfg-roots
  cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
  cmake --build build --parallel
)
echo 'Build complete. To capture game PPU state, run the compiled Japanese'
echo 'executable with IOG_JP_TRACE_DIR set to an existing empty directory.'
echo "The original JP cartridge path is: $rom"
echo 'All frame_*.ppu.bin files are private ROM-derived runtime evidence.'
