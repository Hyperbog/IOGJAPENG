#include "jp_probe.h"
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int get8(JPRead8 r, void *ctx, unsigned bank, unsigned addr, uint8_t *out) {
    return r && r(ctx, ((bank & 255u) << 16) | (addr & 65535u), out);
}
static int get16(JPRead8 r, void *ctx, unsigned bank, unsigned addr, uint16_t *out) {
    uint8_t lo, hi;
    if (!get8(r, ctx, bank, addr, &lo) ||
        !get8(r, ctx, bank, (addr + 1u) & 65535u, &hi)) return 0;
    *out = (uint16_t)((unsigned)lo | ((unsigned)hi << 8));
    return 1;
}
int jp_probe_open(JPProbe *p, const char *out_dir, unsigned every, unsigned limit,
                  const char *evidence) {
    if (!p || !out_dir || !*out_dir || strlen(out_dir) > 690 || !evidence) return 0;
    if (strcmp(evidence, "synthetic_fixture") &&
        strcmp(evidence, "native_interpreter")) return 0;
    memset(p, 0, sizeof(*p));
    snprintf(p->out_dir, sizeof p->out_dir, "%s", out_dir);
    p->snapshot_every = every ? every : 1;
    p->snapshot_limit = limit ? limit : 600;
    char path[850];
    snprintf(path, sizeof path, "%s/events.jsonl", out_dir);
    p->events = fopen(path, "w");
    if (!p->events) return 0;
    fprintf(p->events, "{\"type\":\"header\",\"schema\":\"jp_native_trace_v1\","
            "\"evidence\":\"%s\",\"vram_unit\":\"byte\"}\n", evidence);
    fflush(p->events);
    return 1;
}
void jp_probe_close(JPProbe *p) {
    if (p && p->events) { fclose(p->events); p->events = NULL; }
}
void jp_probe_cop(JPProbe *p, uint16_t sp, uint64_t clock, JPRead8 read, void *ctx) {
    if (!p || !p->events) return;
    uint8_t bank, sig;
    uint16_t pc_after, ptr;
    /* Native 65816 COP frame above S: P, PCL, PCH, PBR. The saved
       PC points immediately after the 2-byte COP instruction. */
    if (!get16(read, ctx, 0, (uint16_t)(sp + 2u), &pc_after) ||
        !get8(read, ctx, 0, (uint16_t)(sp + 4u), &bank)) return;
    uint16_t pc = (uint16_t)(pc_after - 2u);
    if (!get8(read, ctx, bank, (uint16_t)(pc + 1u), &sig)) return;
    if (sig != 0xBF && sig != 0x6B) return;
    if (!get16(read, ctx, bank, pc_after, &ptr)) return;
    fprintf(p->events, "{\"type\":\"cop\",\"frame\":%" PRIu64
            ",\"clock\":%" PRIu64 ",\"site\":\"%02X:%04X\","
            "\"cop\":\"%02X\",\"inline_ptr\":\"%02X:%04X\","
            "\"sp\":%u}\n", p->frame, clock, bank, pc, sig, bank, ptr, sp);
}
void jp_probe_c5(JPProbe *p, uint8_t db, uint16_t y, uint64_t clock,
                 JPRead8 read, void *ctx) {
    if (!p || !p->events) return;
    uint16_t table, selector_addr, selector_val, selected_ptr;
    /* Handler $82:B2A6: LDA $0000,Y; INY twice; STA $00;
       LDA $0000,Y; INY twice; TAX; LDA $0000,X;
       ASL; ADC $00; TAX; LDA $0000,X; TAY; JSL $82:B05F. */
    if (!get16(read, ctx, db, y, &table) ||
        !get16(read, ctx, db, (uint16_t)(y + 2u), &selector_addr) ||
        !get16(read, ctx, db, selector_addr, &selector_val)) {
        fprintf(p->events, "{\"type\":\"c5_unreadable\",\"frame\":%" PRIu64
                ",\"clock\":%" PRIu64 ",\"db\":%u,\"y\":%u}\n",
                p->frame, clock, db, y);
        return;
    }
    uint16_t slot = (uint16_t)(table + (uint16_t)(selector_val * 2u));
    if (!get16(read, ctx, db, slot, &selected_ptr)) {
        fprintf(p->events, "{\"type\":\"c5_unreadable_slot\","
                "\"frame\":%" PRIu64 ",\"clock\":%" PRIu64
                ",\"db\":%u,\"table\":%u,\"selector_addr\":%u,"
                "\"selector_value\":%u,\"slot\":%u}\n",
                p->frame, clock, db, table, selector_addr, selector_val, slot);
        return;
    }
    fprintf(p->events, "{\"type\":\"conditional_c5\",\"frame\":%" PRIu64
            ",\"clock\":%" PRIu64 ",\"operand_pc\":\"%02X:%04X\",\"table\":\"%02X:%04X\","
            "\"selector_addr\":\"%02X:%04X\",\"selector_value\":%u,"
            "\"slot\":\"%02X:%04X\",\"target\":\"%02X:%04X\"}\n",
            p->frame, clock, db, y, db, table, db, selector_addr, selector_val,
            db, slot, db, selected_ptr);
}
void jp_probe_opcode(JPProbe *p, uint32_t pc24, uint64_t clock) {
    if (!p || !p->events) return;
    fprintf(p->events, "{\"type\":\"handler\",\"frame\":%" PRIu64
            ",\"clock\":%" PRIu64 ",\"pc\":\"%06X\"}\n",
            p->frame, clock, (unsigned)(pc24 & 0xFFFFFFu));
}
static uint64_t hash_bytes(uint64_t state, uint8_t b) {
    return (state ^ b) * UINT64_C(1099511628211); /* FNV-1a 64-bit */
}
static int dump_words_le(FILE *f, const uint16_t *src, size_t words,
                         uint64_t *hash) {
    for (size_t i = 0; i < words; ++i) {
        uint8_t lo = (uint8_t)src[i], hi = (uint8_t)(src[i] >> 8);
        if (fputc(lo, f) == EOF || fputc(hi, f) == EOF) return 0;
        if (hash) { *hash = hash_bytes(*hash, lo); *hash = hash_bytes(*hash, hi); }
    }
    return 1;
}
static int dump_bytes(FILE *f, const uint8_t *src, size_t n) {
    return fwrite(src, 1, n, f) == n;
}
int jp_probe_frame(JPProbe *p, const uint16_t vram[0x8000],
                   const uint16_t cgram[0x100], const uint16_t oam[0x100],
                   const uint8_t high_oam[0x20], const JPVideoRegs *regs) {
    if (!p || !p->events || !vram || !cgram || !oam || !high_oam || !regs)
        return 0;
    uint64_t frame = p->frame++;
    if (frame % p->snapshot_every || p->snapshots >= p->snapshot_limit) return 1;
    char path[1024], file[96];
    snprintf(file, sizeof file, "frame_%06" PRIu64 ".ppu.bin", frame);
    snprintf(path, sizeof path, "%s/%s", p->out_dir, file);
    FILE *f = fopen(path, "wb");
    if (!f) return 0;
    /* 66,592 bytes: 65,536 VRAM + 512 CGRAM + 512 low OAM + 32 high OAM.
       No image upscaling or BG-layer substitution is involved. */
    uint64_t checksum = UINT64_C(14695981039346656037);
    int ok = dump_words_le(f, vram, 0x8000, &checksum) &&
             dump_words_le(f, cgram, 0x100, NULL) &&
             dump_words_le(f, oam, 0x100, NULL) &&
             dump_bytes(f, high_oam, 0x20);
    if (fclose(f) != 0) ok = 0;
    if (!ok) { remove(path); return 0; }
    fprintf(p->events, "{\"type\":\"ppu_snapshot\",\"frame\":%" PRIu64
            ",\"file\":\"%s\",\"bytes\":66592,"
            "\"vram_bytes\":65536,\"vram_fnv1a64\":\"%016" PRIx64 "\","
            "\"bgmode\":%u,\"inidisp\":%u,\"bg3sc\":%u,"
            "\"bg_tile_addr\":%u,\"vram_pointer\":%u}\n",
            frame, file, checksum, regs->bgmode, regs->inidisp,
            regs->bg3sc, regs->bg_tile_addr, regs->vram_pointer);
    fflush(p->events);
    p->snapshots++;
    return 1;
}
