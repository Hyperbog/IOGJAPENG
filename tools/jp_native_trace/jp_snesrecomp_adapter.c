/* Compile in a JAPANESE ROM build of SNESRecomp, never the USA Babel target.
 * Call IogJpTraceBegin() once after cart_load(); call IogJpTraceFrame() at
 * end_sim_frame (after emulated PPU draw); call IogJpTraceEnd() on shutdown.
 * Linking this source does not switch Babel's ROM identity to Japan. */
#include "jp_probe.h"
#include "jp_trace_adapter.h"
#include "cpu_state.h"
#include "snes/interp_bridge.h"
#include "snes/snes.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

extern Snes *g_snes;
extern Ppu *g_ppu;
static JPProbe g_trace;
static int g_enabled;

/* Pure peek: never touch PPU/APU I/O registers, even for malformed sources. */
static int peek_cpu(void *ctx, uint32_t addr, uint8_t *value) {
    const CpuState *cpu = (const CpuState *)ctx;
    const uint8_t bank = (uint8_t)(addr >> 16);
    const uint16_t lo = (uint16_t)addr;
    int32_t wr = cpu_wram_offset(bank, lo);
    if (wr >= 0 && cpu->ram) { *value = cpu->ram[wr]; return 1; }
    if (!g_snes || !g_snes->cart || !g_snes->cart->rom) return 0;
    if (bank == 0x7E || bank == 0x7F) return 0;
    if (bank < 0x40 || (bank >= 0x80 && bank < 0xC0))
        if (lo < 0x8000) return 0;
    uint32_t off = ((uint32_t)(bank & 0x3F) << 16) | lo;
    if (off >= g_snes->cart->romSize) return 0;
    *value = g_snes->cart->rom[off];
    return 1;
}
static void on_cop(CpuState *cpu, uint32_t pc) {
    (void)pc;
    jp_probe_cop(&g_trace, cpu->S, cpu->master_cycles, peek_cpu, cpu);
}
static void on_c5(CpuState *cpu, uint32_t pc) {
    (void)pc;
    jp_probe_c5(&g_trace, cpu->DB, cpu->Y, cpu->master_cycles, peek_cpu, cpu);
}
static void on_handler(CpuState *cpu, uint32_t pc) {
    jp_probe_opcode(&g_trace, pc, cpu->master_cycles);
}
void IogJpTraceBegin(void) {
    const char *dir = getenv("IOG_JP_TRACE_DIR");
    if (g_enabled || !dir || !*dir || !g_snes || !g_snes->cart) return;
    Cart *cart = g_snes->cart;
    /* Conservative runtime signature; use external jp_text_trace.py to
       validate the *complete* SHA-256 before launching the Japanese host. */
    const uint8_t *r = cart->rom;
    if (!r || cart->romSize != 0x200000 ||
        memcmp(r + 0xFFC0, "GAIA GENSOUKI 1 JPN  ", 21) ||
        memcmp(r + 0x857D, "\xC2\x20\x9B\xA3\x04\x85\x0C", 7)) {
        fprintf(stderr, "[jp-trace] unsupported ROM; no hooks installed\n");
        return;
    }
    if (!jp_probe_open(&g_trace, dir, 1, 600, "native_interpreter")) {
        fprintf(stderr, "[jp-trace] cannot write trace files under %s\n", dir);
        return;
    }
    /* Required: otherwise ahead-of-time bodies bypass interpreted PC hooks.
       This is a diagnostic switch, not normal game performance policy. */
    interp_bridge_set_interpret_all(1);
    interp_bridge_set_pre_opcode_hook(0x80857D, on_cop);
    interp_bridge_set_pre_opcode_hook(0x82B2A6, on_c5);
    interp_bridge_set_pre_opcode_hook(0x80A9EB, on_handler);
    interp_bridge_set_pre_opcode_hook(0x80AA39, on_handler);
    interp_bridge_set_pre_opcode_hook(0x82B05F, on_handler);
    interp_bridge_set_pre_opcode_hook(0x82B54A, on_handler);
    g_enabled = 1;
    atexit(IogJpTraceEnd);
}
void IogJpTraceFrame(void) {
    if (!g_enabled || !g_ppu) return;
    const JPVideoRegs regs = {g_ppu->bgmode, g_ppu->inidisp,
        g_ppu->bgXsc[2], g_ppu->bgTileAdr, g_ppu->vramPointer};
    if (!jp_probe_frame(&g_trace, g_ppu->vram, g_ppu->cgram,
                        g_ppu->oam, g_ppu->highOam, &regs)) {
        fprintf(stderr, "[jp-trace] PPU capture failed; closing trace\n");
        jp_probe_close(&g_trace);
        g_enabled = 0;
    }
}
void IogJpTraceEnd(void) {
    if (!g_enabled) return;
    jp_probe_close(&g_trace);
    g_enabled = 0;
}
