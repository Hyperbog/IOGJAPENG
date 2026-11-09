# Gaia Gensouki (Japan): native COP + conditional + PPU tracing

## Status (verified on 2026-11-08)

- Original Japanese ROM: 2,097,152 bytes, SHA-256 `7c0380753f976a8e41de92dc78ac76e413e97f0d8610c2d65b0ac31ff24676d0`, CRC32 `b344e9a0`, HiROM, region `JPN`.
- `jp_probe.c`, `test_probe.c`: `gcc -std=c11 -Wall -Wextra -Werror -pedantic` **passes**, synthetic COP and selected `$C5` pointer events verified.
- `jp_snesrecomp_adapter.c`: **compiles** against local ABI stubs drawn from upstream headers; linking against the full SNESRecomp framework **not tested**.
- `integrate_jp_native.py`: identity enforcement, dry run, idempotent integration and refusal to edit incorrectly identified scaffold **pass**.
- `audit_capture.py`: synthetic capture verification and deliberate refusal to classify it as genuine gameplay **pass**.
- Original-game CPU execution and original VRAM capture **not accomplished**: no SNES libretro core, source checkout or Japanese SNESRecomp executable is available locally; this environment cannot resolve external GitHub for a clone.

## Install in a separately scaffolded Japanese port

The existing [Babel Recomp](https://github.com/mrOt4/babel-recomp) source targets the USA ROM and its compiled code and localization rules. **Do not retarget its USA executable.** Start from a fresh project generated with [SNESRecomp](https://github.com/RetroPortingToolKit/snesrecomp):

```sh
# On a development machine with GitHub access, a C/C++ compiler and CMake:
git clone https://github.com/RetroPortingToolKit/snesrecomp.git
sh snesrecomp/tools/new_project/setup_project.sh \
  --rom '/path/to/Gaia Gensouki (Japan).sfc' --dir ./ports \
  --name 'Gaia Gensouki Japan' --players 1 --yes \
  --no-recomp-ui --no-ci --no-github --no-generate --no-build

# The scaffold creates a directory inside ./ports; use that directory:
bash ./jp_native_trace/build_jp_native.sh \
  --rom '/path/to/Gaia Gensouki (Japan).sfc' \
  --project './ports/<actual-scaffold-directory>'
```

`build_jp_native.sh` calls the upstream verified `regen.sh --cfg-roots`, followed by CMake compilation. The build may require native packages (`SDL`, etc.) and framework submodules available on that machine. Generating the executable is necessary but not sufficient to prove the generic frame driver runs the Japanese title correctly; test reset/NMI and frame pacing against a reference core.

## Capture only from real execution

```sh
mkdir -p /path/to/trace_out
IOG_JP_TRACE_DIR='/path/to/trace_out' \
  /path/to/JapaneseScaffold/build/<actual-executable> \
  '/path/to/Gaia Gensouki (Japan).sfc'
python3 jp_native_trace/audit_capture.py /path/to/trace_out
```

Run the title and exercise the desired branch. Tracing starts on the **first `before_run_frame` callback**, forces the **interpreted CPU path** to keep pre-opcode hooks visible, captures frames in `end_sim_frame`, and closes the event file on process exit. The diagnostic output is limited to 600 snapshots by default. The program continues running after that cap (the hooks may continue logging events). No input automation or save-state replay is implemented here.

When `IOG_JP_TRACE_DIR` is unset, the native probe does not activate. It does **not** rewrite CPU registers, text, ROM bytes, or the rendered PPU data.

## What is recorded

`events.jsonl` records a declared provenance (`native_interpreter` or `synthetic_fixture`), COP calling address and inline pointer, actual branch selector and selected target of `$C5` at `$82:B2A6`, text handler entry PCs, and frame snapshots. Native captures come from the SNESRecomp interpreter; the tool does not claim independent reference-emulator equivalence.

Each `frame_NNNNNN.ppu.bin` is **66,592 bytes**: 65,536 bytes VRAM (little-endian), 512 CGRAM, 512 OAM, 32 high OAM. PPU register values are logged per frame. Run `audit_capture.py` to verify snapshot size and FNV-1a hash; its JSON also supplies SHA-256 for each frame's VRAM. Synthetic tests require `--allow-synthetic`.

`test_integration.py` works offline with the supplied original ROM:

```sh
python3 jp_native_trace/test_integration.py '/path/to/Gaia Gensouki (Japan).sfc'
```

## Boundaries

- **Static text candidates** are in the previously committed `tools/jp_text_trace.py` and must not be conflated with executed COP references.
- **Conditional branch events** are only real when the Japanese CPU actually reached the handler; synthetic fixture events are explicitly marked.
- **Authentic VRAM** requires the Japanese port executing the original game. The synthetic `test_probe` capture is explicitly not a substitute.
- The existing GitHub `master_extraction.json` is unchanged; never commit the original ROM, generated C code, extracted graphics, or PPU dumps to the public repo.
