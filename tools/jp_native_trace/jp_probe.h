#ifndef IOG_JP_PROBE_H
#define IOG_JP_PROBE_H
#include <stdint.h>
#include <stdio.h>

typedef int (*JPRead8)(void *ctx, uint32_t cpu_address, uint8_t *out);

typedef struct JPProbe {
    FILE *events;
    char out_dir[768];
    uint64_t frame;
    unsigned snapshots;
    unsigned snapshot_every;
    unsigned snapshot_limit;
} JPProbe;

typedef struct JPVideoRegs {
    uint8_t bgmode, inidisp, bg3sc;
    uint16_t bg_tile_addr, vram_pointer;
} JPVideoRegs;

/* All observers are read-only and log only CPU-executed sites. */
int jp_probe_open(JPProbe *p, const char *out_dir, unsigned every, unsigned limit,
                  const char *evidence);
void jp_probe_close(JPProbe *p);
void jp_probe_cop(JPProbe *p, uint16_t sp, uint64_t clock, JPRead8 read, void *ctx);
void jp_probe_c5(JPProbe *p, uint8_t db, uint16_t y, uint64_t clock,
                 JPRead8 read, void *ctx);
void jp_probe_opcode(JPProbe *p, uint32_t pc24, uint64_t clock);
int jp_probe_frame(JPProbe *p, const uint16_t vram[0x8000],
                   const uint16_t cgram[0x100], const uint16_t oam[0x100],
                   const uint8_t high_oam[0x20], const JPVideoRegs *regs);
#endif
