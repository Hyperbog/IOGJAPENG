#include "jp_probe.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <stdint.h>

typedef struct { uint8_t ram[0x20000], rom[0x20000]; } Mock;
static int mockread(void *ctx, uint32_t a, uint8_t *v) {
    Mock *m = ctx;
    uint8_t bank = (uint8_t)(a >> 16);
    uint16_t addr = (uint16_t)a;
    if (bank == 0 || (bank == 0x88 && addr < 0x2000)) {
        *v = m->ram[addr]; return 1;
    }
    if (bank == 0x88 && addr >= 0x8000) {
        *v = m->rom[addr]; return 1;
    }
    return 0;
}
int main(int argc, char **argv) {
    assert(argc == 2);
    JPProbe probe;
    Mock *m = calloc(1, sizeof(*m));
    assert(m);
    /* Synthesized COP #BF at $88:E000; saved return PC=E002. */
    m->ram[0x01FC] = 0x02; m->ram[0x01FD] = 0xE0;
    m->ram[0x01FE] = 0x88;
    m->rom[0xE000] = 0x02; m->rom[0xE001] = 0xBF;
    m->rom[0xE002] = 0x34; m->rom[0xE003] = 0xE1;
    /* Synthesized $C5 operands at $88:E100: table E200, selector $00AC;
       $88:00AC WRAM = 2; table entry 2 points at E350. */
    m->rom[0xE100] = 0x00; m->rom[0xE101] = 0xE2;
    m->rom[0xE102] = 0xAC; m->rom[0xE103] = 0x00;
    m->ram[0xAC] = 0x02; m->ram[0xAD] = 0x00;
    m->rom[0xE204] = 0x50; m->rom[0xE205] = 0xE3;
    assert(jp_probe_open(&probe, argv[1], 1, 2, "synthetic_fixture"));
    jp_probe_cop(&probe, 0x01FA, 113, mockread, m);
    jp_probe_c5(&probe, 0x88, 0xE100, 114, mockread, m);
    jp_probe_opcode(&probe, 0x82B05F, 115);
    uint16_t *vram = calloc(0x8000, 2);
    uint16_t cgram[0x100] = {0}, oam[0x100] = {0};
    uint8_t high[0x20] = {0};
    JPVideoRegs regs = {1, 15, 0x40, 0x8000, 0};
    assert(vram);
    vram[0x10] = 0x1234;
    assert(jp_probe_frame(&probe, vram, cgram, oam, high, &regs));
    jp_probe_close(&probe);
    free(vram); free(m);
    return 0;
}
