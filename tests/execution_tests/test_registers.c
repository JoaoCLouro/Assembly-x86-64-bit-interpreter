#include "../../execution/include/registers.h"

#include <stdio.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <assert.h>

// Building (src must be built)
// gcc -O3 -shared -o libregisters.so -fPIC registers.c
// gcc -O3 -o test_suite tests.c -L. -lregisters

// --- Test helpers ---

static int tests_run    = 0;
static int tests_passed = 0;

#define TEST(name) static void name(void)

#define RUN(name) \
    do { \
        printf("  %-55s", #name); \
        tests_run++; \
        name(); \
        tests_passed++; \
        printf("PASS\n"); \
    } while (0)

#define ASSERT(cond) \
    do { \
        if (!(cond)) { \
            printf("FAIL\n    Assertion failed: %s  (%s:%d)\n", \
                   #cond, __FILE__, __LINE__); \
            return; \
        } \
    } while (0)

// Arbitrary register IDs
#define REG_A  0
#define REG_B  1
#define REG_C  2

// -----------------------------------------------------------------------
// Tests — lifecycle & bounds checking
// -----------------------------------------------------------------------

TEST(test_init_not_null) {
    CPURegs *r = CPURegs_create();
    ASSERT(r != NULL);
    CPURegs_free(r);
}

TEST(test_free_no_crash) {
    CPURegs *r = CPURegs_create();
    ASSERT(r != NULL);
    CPURegs_free(r);
}

TEST(test_out_of_bounds_reg) {
    CPURegs *r = CPURegs_create();

    // Should safely do nothing without crashing
    write_reg(r, 99, 0xFF, 1, 0);

    // Should safely return 0 or default failure values
    ASSERT(read_8b_reg(r, 99) == 0);
    ASSERT(is_signed(r, 99) == -1);

    CPURegs_free(r);
}

// -----------------------------------------------------------------------
// Tests — sign setters / getters
// -----------------------------------------------------------------------

TEST(test_default_unsigned) {
    CPURegs *r = CPURegs_create();
    ASSERT(is_signed(r, REG_A) == 0);
    CPURegs_free(r);
}

TEST(test_set_signed) {
    CPURegs *r = CPURegs_create();
    set_reg_sign(r, REG_A, 1);
    ASSERT(is_signed(r, REG_A) != 0);
    CPURegs_free(r);
}

TEST(test_clear_signed) {
    CPURegs *r = CPURegs_create();
    set_reg_sign(r, REG_A, 1);
    set_reg_sign(r, REG_A, 0);
    ASSERT(is_signed(r, REG_A) == 0);
    CPURegs_free(r);
}

TEST(test_sign_flag_per_register) {
    CPURegs *r = CPURegs_create();
    set_reg_sign(r, REG_A, 1);
    ASSERT(is_signed(r, REG_B) == 0);
    CPURegs_free(r);
}

// -----------------------------------------------------------------------
// Tests — write_reg / read_Xb_reg & Arch Rules
// -----------------------------------------------------------------------

TEST(test_write_read_1b_low) {
    CPURegs *r = CPURegs_create();
    write_reg(r, REG_A, 0xAB, 1, 0);
    uint8_t v = read_1b_reg(r, REG_A, 0);
    ASSERT(v == 0xAB);
    CPURegs_free(r);
}

TEST(test_write_read_1b_high) {
    CPURegs *r = CPURegs_create();
    write_reg(r, REG_A, 0xCD, 1, 1);
    uint8_t v = read_1b_reg(r, REG_A, 1);
    ASSERT(v == 0xCD);
    CPURegs_free(r);
}

TEST(test_8b_high_low_independence) {
    CPURegs *r = CPURegs_create();
    write_reg(r, REG_A, 0, 8, 0);    // Clear RAX
    write_reg(r, REG_A, 0xAA, 1, 0); // Write AL
    write_reg(r, REG_A, 0xBB, 1, 1); // Write AH

    // AX should now be 0xBBAA
    ASSERT(read_2b_reg(r, REG_A) == 0xBBAA);
    CPURegs_free(r);
}

TEST(test_write_read_2b) {
    CPURegs *r = CPURegs_create();
    write_reg(r, REG_A, 0x1234, 2, 0);
    uint16_t v = read_2b_reg(r, REG_A);
    ASSERT(v == 0x1234);
    CPURegs_free(r);
}

TEST(test_write_read_4b) {
    CPURegs *r = CPURegs_create();
    write_reg(r, REG_A, 0xDEADBEEF, 4, 0);
    uint32_t v = read_4b_reg(r, REG_A);
    ASSERT(v == 0xDEADBEEF);
    CPURegs_free(r);
}

TEST(test_write_read_8b) {
    CPURegs *r = CPURegs_create();
    write_reg(r, REG_A, 0x0123456789ABCDEFULL, 8, 0);
    uint64_t v = read_8b_reg(r, REG_A);
    ASSERT(v == 0x0123456789ABCDEFULL);
    CPURegs_free(r);
}

TEST(test_32b_zero_extension) {
    CPURegs *r = CPURegs_create();
    // Fill register with 1s
    write_reg(r, REG_A, 0xFFFFFFFFFFFFFFFFULL, 8, 0);
    // Write 32-bit value
    write_reg(r, REG_A, 0x12345678, 4, 0);

    // The upper 32 bits MUST be zeroed out
    uint64_t v = read_8b_reg(r, REG_A);
    ASSERT(v == 0x0000000012345678ULL);
    CPURegs_free(r);
}

TEST(test_16b_no_zero_extension) {
    CPURegs *r = CPURegs_create();
    // Fill register with 1s
    write_reg(r, REG_A, 0xFFFFFFFFFFFFFFFFULL, 8, 0);
    // Write 16-bit value
    write_reg(r, REG_A, 0x1234, 2, 0);

    // The upper 48 bits MUST remain untouched
    uint64_t v = read_8b_reg(r, REG_A);
    ASSERT(v == 0xFFFFFFFFFFFF1234ULL);
    CPURegs_free(r);
}

TEST(test_registers_independent) {
    CPURegs *r = CPURegs_create();
    write_reg(r, REG_A, 0x11, 1, 0);
    write_reg(r, REG_B, 0x22, 1, 0);
    ASSERT(read_1b_reg(r, REG_A, 0) == 0x11);
    ASSERT(read_1b_reg(r, REG_B, 0) == 0x22);
    CPURegs_free(r);
}

// -----------------------------------------------------------------------
// Tests — flags
// -----------------------------------------------------------------------

TEST(test_read_rflags_no_crash) {
    CPURegs *r = CPURegs_create();
    (void)read_rflags(r);
    CPURegs_free(r);
}

TEST(test_write_read_rflags) {
    CPURegs *r = CPURegs_create();
    write_rflags(r, 0b00000101); // Set CF and PF
    uint32_t flags = read_rflags(r);
    ASSERT((flags & 0b00000101) == 0b00000101);
    CPURegs_free(r);
}

TEST(test_carry_flag) {
    CPURegs *r = CPURegs_create();
    write_rflags(r, read_rflags(r) | 0x1);
    ASSERT(read_carry_flag(r) != 0);
    write_rflags(r, read_rflags(r) & ~0x1);
    ASSERT(read_carry_flag(r) == 0);
    CPURegs_free(r);
}

TEST(test_zero_flag) {
    CPURegs *r = CPURegs_create();
    write_rflags(r, read_rflags(r) | 0x40);
    ASSERT(read_zero_flag(r) != 0);
    write_rflags(r, read_rflags(r) & ~0x40);
    ASSERT(read_zero_flag(r) == 0);
    CPURegs_free(r);
}

TEST(test_sign_flag) {
    CPURegs *r = CPURegs_create();
    write_rflags(r, read_rflags(r) | 0x80);
    ASSERT(read_sign_flag(r) != 0);
    write_rflags(r, read_rflags(r) & ~0x80);
    ASSERT(read_sign_flag(r) == 0);
    CPURegs_free(r);
}

TEST(test_overflow_flag) {
    CPURegs *r = CPURegs_create();
    write_rflags(r, read_rflags(r) | 0x800);
    ASSERT(read_overflow_flag(r) != 0);
    write_rflags(r, read_rflags(r) & ~0x800);
    ASSERT(read_overflow_flag(r) == 0);
    CPURegs_free(r);
}

TEST(test_parity_flag) {
    CPURegs *r = CPURegs_create();

    // Set Parity Flag (bit 2 -> 0x4)
    write_rflags(r, read_rflags(r) | 0x4);
    ASSERT(read_parity_flag(r) != 0);

    // Clear Parity Flag
    write_rflags(r, read_rflags(r) & ~0x4);
    ASSERT(read_parity_flag(r) == 0);

    CPURegs_free(r);
}

TEST(test_trap_flag_toggle) {
    CPURegs *r = CPURegs_create();

    // First call should set it
    set_trap_flag(r);
    ASSERT(read_trap_flag(r) != 0);

    // Second call should clear it
    set_trap_flag(r);
    ASSERT(read_trap_flag(r) == 0);

    CPURegs_free(r);
}

TEST(test_exch_rflag_toggle) {
    CPURegs *r = CPURegs_create();
    uint32_t before = read_rflags(r);
    exch_rflag(r, 0); // Toggle CF
    uint32_t after = read_rflags(r);
    ASSERT((before & 0x1) != (after & 0x1));
    CPURegs_free(r);
}

// -----------------------------------------------------------------------
// Entry point
// -----------------------------------------------------------------------

int main(void) {
    printf("=== CPU Registers Execution Tests ===\n\n");

    RUN(test_init_not_null);
    RUN(test_free_no_crash);
    RUN(test_out_of_bounds_reg);

    RUN(test_default_unsigned);
    RUN(test_set_signed);
    RUN(test_clear_signed);
    RUN(test_sign_flag_per_register);

    RUN(test_write_read_1b_low);
    RUN(test_write_read_1b_high);
    RUN(test_8b_high_low_independence);
    RUN(test_write_read_2b);
    RUN(test_write_read_4b);
    RUN(test_write_read_8b);

    RUN(test_32b_zero_extension);
    RUN(test_16b_no_zero_extension);

    RUN(test_registers_independent);

    RUN(test_read_rflags_no_crash);
    RUN(test_write_read_rflags);
    RUN(test_carry_flag);
    RUN(test_parity_flag);
    RUN(test_zero_flag);
    RUN(test_sign_flag);
    RUN(test_overflow_flag);
    RUN(test_trap_flag_toggle);
    RUN(test_exch_rflag_toggle);

    printf("\n%d / %d tests passed.\n", tests_passed, tests_run);
    return (tests_passed == tests_run) ? 0 : 1;
}
