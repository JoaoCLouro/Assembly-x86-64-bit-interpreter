#include "../include/registers.h"
#include <stdlib.h>
#include <stdio.h>

typedef union x86_aliased_registers {
    uint64_t r64;
    uint32_t e32;
    uint16_t x16;
    struct {
        uint8_t l;
        uint8_t h;
    } r8;
} x86_aliased_registers;

typedef struct x86_reg_t {
    x86_aliased_registers reg;
    uint8_t is_signed;
} x86_reg_t;

struct CPURegs {
    x86_reg_t regs[16];
    uint32_t rflags;
};

CPURegs* CPURegs_create() {
    CPURegs *c = (CPURegs*)calloc(1, sizeof(CPURegs));
    if (c == NULL) {
        fprintf(stderr, "Fail allocating register memory. Aborting program\n");
        return NULL;
    }
    return c;
}

void CPURegs_free(CPURegs *c) {
    free(c);
}

x86_reg_t* get_reg_ptr(CPURegs *current_state, uint8_t reg_id) {
    if (reg_id > 15 || !current_state) return NULL; // Dropped reg_id < 0 check
    return &(current_state->regs[reg_id]);
}

void set_reg_sign (CPURegs *current_state, uint8_t reg_id, uint8_t is_signed) {
    x86_reg_t *target = get_reg_ptr(current_state, reg_id);
    if (target) target->is_signed = is_signed;
}

int is_signed (CPURegs *current_state, uint8_t reg_id) {
    x86_reg_t *target = get_reg_ptr(current_state, reg_id);
    return target ? target->is_signed : -1;
}

void write_reg(CPURegs *current_state, uint8_t reg_id, int64_t value, uint8_t size, uint8_t is_high) {
    x86_reg_t *ptr = get_reg_ptr(current_state, reg_id);
    if (!ptr) return;

    x86_aliased_registers *target = &ptr->reg;

    if (size == 8) {
        target->r64 = (uint64_t)value;
    } else if (size == 4) {
        target->r64 = (uint32_t)value; // Architectural 32-bit zero-extension
    } else if (size == 2) {
        target->x16 = (uint16_t)value;
    } else if (size == 1) {
        if (is_high && reg_id < 4) target->r8.h = (uint8_t)value;
        else target->r8.l = (uint8_t)value;
    }
}

uint64_t read_8b_reg(CPURegs *current_state, uint8_t reg_id) {
    x86_reg_t *ptr = get_reg_ptr(current_state, reg_id);
    return ptr ? ptr->reg.r64 : 0;
}

uint32_t read_4b_reg(CPURegs *current_state, uint8_t reg_id) {
    x86_reg_t *ptr = get_reg_ptr(current_state, reg_id);
    return ptr ? ptr->reg.e32 : 0;
}

uint16_t read_2b_reg(CPURegs *current_state, uint8_t reg_id) {
    x86_reg_t *ptr = get_reg_ptr(current_state, reg_id);
    return ptr ? ptr->reg.x16 : 0;
}

uint8_t read_1b_reg(CPURegs *current_state, uint8_t reg_id, uint8_t is_high) {
    x86_reg_t *ptr = get_reg_ptr(current_state, reg_id);
    if (!ptr) return 0;

    if (is_high && reg_id < 4) return ptr->reg.r8.h;
    return ptr->reg.r8.l;
}

// ------------------------------------
// RFLAGS Functions (unaltered, look solid)
// ------------------------------------

uint32_t read_rflags(CPURegs *current_state) { return current_state ? current_state->rflags : 0; }
void write_rflags(CPURegs *current_state, uint32_t value) { if (current_state) current_state->rflags = value; }

uint8_t read_trap_flag(CPURegs *current_state)     { return (read_rflags(current_state) >> 8) & 0x1; }
uint8_t read_carry_flag(CPURegs *current_state)    { return (read_rflags(current_state) & 0x1); }
uint8_t read_zero_flag(CPURegs *current_state)     { return (read_rflags(current_state) >> 6) & 0x1; }
uint8_t read_sign_flag(CPURegs *current_state)     { return (read_rflags(current_state) >> 7) & 0x1; }
uint8_t read_overflow_flag(CPURegs *current_state) { return (read_rflags(current_state) >> 11) & 0x1; }
uint8_t read_parity_flag(CPURegs *current_state)   { return (read_rflags(current_state) >> 2) & 0x1; }

void exch_rflag (CPURegs *current_state, uint8_t flag_id) {
    if (flag_id > 31 || !current_state) return;
    current_state->rflags ^= (1U << flag_id);
}

void set_trap_flag(CPURegs *current_state) {
    if (current_state) current_state->rflags ^= (1U << 8);
}

#ifdef _WIN32
__declspec(dllexport) void* PyInit_libreg(void) { return 0; }
#endif
