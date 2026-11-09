#!/usr/bin/env python3
"""Gaia Gensouki (JP) ROM-verified COP/text-reference reconnaissance.

Read-only. Does not translate glyphs, patch the ROM, or claim that a COP
pattern found in raw bytes is reachable code. Python 3.9+; no dependencies.
"""
from __future__ import annotations

import argparse
from collections import Counter, deque
import hashlib
import json
from pathlib import Path

EXPECTED_SHA256 = "7c0380753f976a8e41de92dc78ac76e413e97f0d8610c2d65b0ac31ff24676d0"
ROM_SIZE = 0x200000
COP_VECTOR = 0x8007
COP_DISPATCH = 0x857D
COP_TABLE = 0x8595
TEXT_ENTRY = 0x2B05F      # JSL $82:B05F
CMD_TABLE = 0x2B094       # 32 word entries, $82:B094
DICT_TABLE = 0x1CA7D      # $81:CA7D, selected by C2's bank switch

# Operand widths inferred from JP command handlers at $82:B094.
# None means a dynamic/undetermined length. Do not parse across it.
WIDTHS = {
    0xC0: 0, 0xC1: 2, 0xC2: 1, 0xC3: 1, 0xC4: 0,
    0xC5: 4, 0xC6: None, 0xC7: 1, 0xC8: 0, 0xC9: 1,
    0xCA: 0, 0xCB: 0, 0xCC: 0, 0xCD: 0, 0xCE: 1,
    0xCF: 3, 0xD0: 0, 0xD1: 0, 0xD2: 0, 0xD3: 2,
    0xD4: 0, 0xD5: 0, 0xD6: 1, 0xD7: 0, 0xD8: None,
    0xD9: 1,
}
HALT = {0xC0, 0xCA, 0xCC}
CALLS = {0x6B, 0xBF}


def rom_offset(ptr: int) -> int | None:
    """Map a 24-bit SNES CPU address to the 2 MiB HiROM image."""
    bank, addr = (ptr >> 16) & 0xFF, ptr & 0xFFFF
    if bank in (0x7E, 0x7F):
        return None  # WRAM
    if bank <= 0x3F or 0x80 <= bank <= 0xBF:
        if addr < 0x8000:
            return None  # RAM, MMIO or other non-cartridge space
    off = ((bank & 0x3F) << 16) | addr
    return off if off < ROM_SIZE else None


def word(rom: bytes, at: int) -> int:
    if at < 0 or at + 2 > len(rom):
        raise ValueError(f"word outside ROM: {at:#x}")
    return int.from_bytes(rom[at:at + 2], "little")


def assert_jp_engine(rom: bytes) -> dict:
    """Reject unknown ROM versions and changed 65816 dispatch signatures."""
    sha = hashlib.sha256(rom).hexdigest()
    if len(rom) != ROM_SIZE or sha != EXPECTED_SHA256:
        raise ValueError(f"unsupported ROM identity: size={len(rom)}, sha256={sha}")
    if rom[0xFFC0:0xFFD5] != b"GAIA GENSOUKI 1 JPN  ":
        raise ValueError("JP internal header mismatch")
    if word(rom, 0xFFE4) != COP_VECTOR:
        raise ValueError("native COP vector is not $8007")
    if rom[COP_VECTOR:COP_VECTOR + 4] != bytes.fromhex("5c7d8580"):
        raise ValueError("COP vector does not jump to $80:857D")
    # REP #$20; TXY; LDA $04,S; STA $0C; LDA $02,S; DEC;
    # STA $0A; LDA [$0A]; INC $0A; AND #$00FF; ASL; TAX; JMP ($8595,X)
    dispatch = bytes.fromhex("c2209ba304850ca3023a850aa70ae60a29ff000aaa7c9585")
    if rom[COP_DISPATCH:COP_DISPATCH + len(dispatch)] != dispatch:
        raise ValueError("native COP dispatcher differs from analyzed sequence")
    handlers = {f"{op:02X}": word(rom, COP_TABLE + 2 * op) for op in (0x6B, 0xBD, 0xBF)}
    if handlers != {"6B": 0xAA39, "BD": 0xA963, "BF": 0xA9EB}:
        raise ValueError(f"text-related COP handlers changed: {handlers}")
    if rom[TEXT_ENTRY:TEXT_ENTRY + 28] != bytes.fromhex(
        "080bdaa900005be220b900003009c82010b82026bd80f0c88940d008"):
        raise ValueError("Japanese $82:B05F glyph dispatch changed")
    if word(rom, CMD_TABLE) != 0xB0C8 or word(rom, CMD_TABLE + 2 * 0x0F) != 0xB1A8:
        raise ValueError("Japanese command table changed")
    return {"sha256": sha, "native_cop_vector": "00:8007",
            "cop_dispatch": "80:857D", "cop_table": "80:8595",
            "handlers": {key: f"80:{val:04X}" for key, val in handlers.items()},
            "wide_text_engine": "82:B05F", "command_table": "82:B094",
            "dictionary_table": "81:CA7D"}


def indirect_table_candidates(rom: bytes, bank: int, table: int) -> dict:
    """Unproven candidate bound: first pointer immediately follows the table."""
    start = rom_offset((bank << 16) | table)
    if start is None or start + 2 > len(rom):
        return {"candidate_entries": [], "extent_basis": "unavailable"}
    first = word(rom, start)
    delta = first - table
    if not (2 <= delta <= 512 and delta % 2 == 0):
        return {"candidate_entries": [], "extent_basis": "unknown"}
    n = delta // 2
    entries = [rom_offset((bank << 16) | word(rom, start + 2 * i))
               for i in range(n)]
    return {"candidate_entries": entries,
            "extent_basis": "heuristic_first_pointer_after_table_not_runtime_verified"}


def parse_text(rom: bytes, off: int, bank: int, max_bytes: int = 768) -> dict:
    """Tokenize known JP widths, record static edges, preserve uncertainty.

    A byte <$80 is one glyph. $80-$BF is a *two-byte* glyph.
    $C0-$D9 dispatch through $82:B094. Unknown control sizes stop parsing.
    """
    cur, end = off, min(len(rom), off + max_bytes, (off & ~0xFFFF) + 0x10000)
    counts = Counter()
    edges = []
    unknown = None
    while cur < end:
        at = cur
        code = rom[cur]
        cur += 1
        if code < 0x80:
            counts["glyph_1byte"] += 1
            continue
        if code < 0xC0:
            if cur >= end:
                unknown = f"truncated_two_byte_glyph_at_{at:06X}"
                break
            cur += 1
            counts["glyph_2byte"] += 1
            continue
        width = WIDTHS.get(code)
        if width is None:
            unknown = f"unknown_command_width_{code:02X}_at_{at:06X}"
            break
        if cur + width > end:
            unknown = f"truncated_command_{code:02X}_at_{at:06X}"
            break
        operands = rom[cur:cur + width]
        cur += width
        counts[f"cmd_{code:02X}"] += 1
        if code == 0xC2:  # 8-bit dictionary index; table bank set to $81
            index = operands[0]
            dest = word(rom, DICT_TABLE + 2 * index)
            target = rom_offset(0x810000 | dest)
            if target is not None:
                edges.append({"kind": "dictionary_C2", "at": at,
                              "index": index, "target": target, "bank": 0x81})
        elif code == 0xCF:  # 24-bit nested string; verified $82:B1A8
            ptr = int.from_bytes(operands, "little")
            target = rom_offset(ptr)
            edges.append({"kind": "nested_CF", "at": at,
                          "snes_ptr": f"{ptr:06X}", "target": target,
                          "bank": ptr >> 16})
        elif code == 0xD3:  # LDY word (absolute bank-local text jump)
            dest = int.from_bytes(operands, "little")
            edges.append({"kind": "jump_D3", "at": at,
                          "target": rom_offset((bank << 16) | dest), "bank": bank})
            return {"offset": off, "span": cur - off, "stop": "jump_D3",
                    "counts": dict(counts), "edges": edges}
        elif code == 0xC5:  # selector address in RAM, bank-local pointer table
            table = int.from_bytes(operands[:2], "little")
            selector = int.from_bytes(operands[2:], "little")
            edges.append({"kind": "indirect_C5", "at": at, "bank": bank,
                          "table": table, "selector_ram": selector,
                          "target": None, "requires_runtime": True,
                          **indirect_table_candidates(rom, bank, table)})
        if code in HALT:
            return {"offset": off, "span": cur - off, "stop": f"halt_{code:02X}",
                    "counts": dict(counts), "edges": edges}
    return {"offset": off, "span": cur - off, "stop": unknown or "limit_reached",
            "counts": dict(counts), "edges": edges}


def scan(rom: bytes, max_nodes: int = 5000) -> dict:
    identity = assert_jp_engine(rom)
    calls = []
    roots = deque()
    for i in range(0, len(rom) - 3):
        if rom[i] != 0x02 or rom[i + 1] not in CALLS:
            continue
        # COP immediate is followed by a 16-bit string pointer in the
        # same script bank. Physical ROM offset, not a runtime PBR claim.
        target = (i & ~0xFFFF) | word(rom, i + 2)
        if 0 <= target < len(rom):
            calls.append({"site": i, "cop": f"{rom[i + 1]:02X}",
                          "target": target, "bank": 0x80 | (i >> 16)})
            roots.append((target, 0x80 | (i >> 16)))
    seen = set()
    nodes = []
    unresolved = []
    while roots and len(nodes) < max_nodes:
        off, bank = roots.popleft()
        if off in seen:
            continue
        seen.add(off)
        node = parse_text(rom, off, bank)
        nodes.append(node)
        for e in node["edges"]:
            if e["target"] is not None:
                roots.append((e["target"], e["bank"]))
            else:
                unresolved.append({"source": off, **e})
    ends = Counter(n["stop"].split("_at_")[0] for n in nodes)
    edges = Counter(e["kind"] for n in nodes for e in n["edges"])
    return {"schema": "jp_rom_reference_trace_v1", "identity": identity,
            "disclaimer": "static pattern scan; no CPU reachability or frame execution proved",
            "summary": {"cop_pattern_sites": len(calls),
                        "cop_by_opcode": dict(Counter(x["cop"] for x in calls)),
                        "distinct_direct_targets": len(set(x["target"] for x in calls)),
                        "parsed_nodes": len(nodes), "parse_stops": dict(ends),
                        "reference_edge_kinds": dict(edges),
                        "unresolved_edges": len(unresolved),
                        "heuristic_indirect_candidate_slots": sum(
                            len(e["candidate_entries"]) for e in unresolved),
                        "worklist_remaining": len(roots)},
            "call_sites": calls, "text_nodes": nodes,
            "unresolved_indirections": unresolved}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("rom", type=Path, help="your original Japanese .sfc")
    ap.add_argument("--out", type=Path, help="optional machine-readable report")
    ap.add_argument("--max-nodes", type=int, default=5000)
    args = ap.parse_args()
    result = scan(args.rom.read_bytes(), args.max_nodes)
    if args.out:
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"identity": result["identity"], "summary": result["summary"]}, indent=2))


if __name__ == "__main__":
    main()
