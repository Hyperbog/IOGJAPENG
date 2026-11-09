#!/usr/bin/env python3
"""Audit a captured JSONL event log and its original PPU snapshots.

Rejects synthetic fixture captures by default. Does not claim to independently
authenticate an emulator or infer branch reachability without hook events.
"""
from pathlib import Path
import argparse
from collections import Counter
import hashlib
import json
import sys

VRAM_BYTES = 65536
PPU_BYTES = 66592
FNV_OFFSET = 14695981039346656037
FNV_PRIME = 1099511628211


def checksum(raw: bytes) -> str:
    h = FNV_OFFSET
    for b in raw:
        h = ((h ^ b) * FNV_PRIME) & 0xFFFFFFFFFFFFFFFF
    return f"{h:016x}"


def audit(directory: Path, allow_synthetic: bool = False) -> dict:
    log = directory / 'events.jsonl'
    records = [json.loads(x) for x in log.read_text().splitlines() if x.strip()]
    if not records or records[0].get('schema') != 'jp_native_trace_v1':
        raise ValueError('missing or unrecognized trace header')
    origin = records[0].get('evidence')
    if origin not in ('native_interpreter', 'synthetic_fixture'):
        raise ValueError(f'unrecognized trace provenance: {origin}')
    if origin != 'native_interpreter' and not allow_synthetic:
        raise ValueError('synthetic test capture: pass --allow-synthetic only for diagnostics')
    counts = Counter()
    vram_sha256 = {}
    sites = set()
    branches = set()
    for rec in records[1:]:
        kind = rec.get('type')
        counts[kind] += 1
        if kind == 'cop':
            sites.add((rec['site'], rec['cop'], rec['inline_ptr']))
        if kind == 'conditional_c5':
            branches.add((rec['table'], rec['selector_addr'], rec['selector_value'], rec['target']))
        if kind != 'ppu_snapshot':
            continue
        path = directory / rec['file']
        if path.parent.resolve() != directory.resolve():
            raise ValueError('PPU snapshot references a file outside capture directory')
        payload = path.read_bytes()
        if len(payload) != PPU_BYTES or rec.get('bytes') != PPU_BYTES:
            raise ValueError(f'{path}: incorrect byte length')
        vr = payload[:VRAM_BYTES]
        if checksum(vr) != rec['vram_fnv1a64']:
            raise ValueError(f'{path}: VRAM hash does not match event log')
        vram_sha256[rec['file']] = hashlib.sha256(vr).hexdigest()
    return {'schema': 'jp_capture_audit_v1', 'provenance': origin,
            'frame_snapshots_verified': counts['ppu_snapshot'],
            'cop_events': counts['cop'], 'unique_executed_cop_patterns': len(sites),
            'conditional_branch_events': counts['conditional_c5'],
            'distinct_selected_branches': len(branches),
            'handler_events': counts['handler'],
            'vram_sha256_by_frame': vram_sha256,
            'note': 'Checksums validate captured files, not emulator fidelity.'}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory', type=Path)
    p.add_argument('--allow-synthetic', action='store_true')
    p.add_argument('--output', type=Path)
    args = p.parse_args()
    try:
        result = audit(args.directory, args.allow_synthetic)
        output = json.dumps(result, indent=2) + '\n'
        if args.output:
            args.output.write_text(output, encoding='utf-8')
        print(output, end='')
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        p.exit(1, f'capture audit rejected: {exc}\n')


if __name__ == '__main__':
    main()
