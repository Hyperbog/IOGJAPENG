#!/usr/bin/env python3
"""Test Japanese scaffold insertion, identity rejection, and fixture capture."""
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import json
import subprocess
import sys

from integrate_jp_native import install, SHA256

HERE = Path(__file__).parent
ROM = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/mnt/data/Gaia Gensouki (Japan).sfc')


def mk_scaffold(root: Path) -> None:
    (root / 'src').mkdir()
    (root / 'rom_identity.txt').write_text(
        'display_name = Gaia Gensouki JPN\n'
        'expected_crc32 = b344e9a0\n'
        f'expected_sha256 = {SHA256}\n'
        'mapping = hirom\nregion = JPN\n', encoding='utf-8')
    (root / 'CMakeLists.txt').write_text(
        'add_executable(GaiaGensoukiJPN\n    src/main.c\n    src/game_rtl.c\n'
        '    src/gen_stubs.c\n)\n', encoding='utf-8')
    (root / 'src/main.c').write_text(
        '#include "game_rtl.h"\n'
        'static const SnesDesktopHostGame kGameHost = {\n'
        '    .game_info           = &kGameInfo,\n};\n', encoding='utf-8')


def main() -> None:
    subprocess.run(['gcc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    str(HERE / 'jp_probe.c'), str(HERE / 'test_probe.c'),
                    '-o', str(HERE / 'test_probe')], check=True)
    with TemporaryDirectory() as base:
        root = Path(base) / 'jp_project'
        root.mkdir()
        mk_scaffold(root)
        files_before = sorted(root.rglob('*'))
        status = install(ROM, root, HERE, check=True)
        assert status and files_before == sorted(root.rglob('*'))
        changes = install(ROM, root, HERE)
        assert len(changes) == 6, changes
        assert install(ROM, root, HERE) == [], 'integration is not idempotent'
        main_src = (root / 'src/main.c').read_text()
        cmake_src = (root / 'CMakeLists.txt').read_text()
        assert main_src.count('jp_trace_end_sim_frame') == 2
        assert 'src/jp_snesrecomp_adapter.c' in cmake_src
        # Fail closed for the USA ROM / incorrect project identity.
        (root / 'rom_identity.txt').write_text('mapping = hirom\nregion = JPN\n')
        try:
            install(ROM, root, HERE)
        except ValueError as exc:
            assert 'identity' in str(exc)
        else:
            raise AssertionError('must reject unverified target scaffold')

        capture = Path(base) / 'synthetic'
        capture.mkdir()
        subprocess.run([str(HERE / 'test_probe'), str(capture)], check=True)
        events = [json.loads(line) for line in (capture / 'events.jsonl').read_text().splitlines()]
        assert events[0]['evidence'] == 'synthetic_fixture'
        assert [event['type'] for event in events] == [
            'header', 'cop', 'conditional_c5', 'handler', 'ppu_snapshot']
        assert events[1]['site'] == '88:E000' and events[1]['inline_ptr'] == '88:E134'
        assert events[2]['selector_value'] == 2 and events[2]['target'] == '88:E350'
        ppu = (capture / 'frame_000000.ppu.bin').read_bytes()
        assert len(ppu) == 66592 and ppu[32:34] == b'\x34\x12'
        digest = hashlib.sha256(ppu[:65536]).hexdigest()
        print(json.dumps({'test': 'pass', 'scaffold_files_added_or_updated': len(changes),
                          'events': len(events), 'synthetic_vram_sha256': digest,
                          'synthetic_ppu_bytes': len(ppu)}))


if __name__ == '__main__':
    main()
