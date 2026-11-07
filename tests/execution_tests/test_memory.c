#include "../../execution/include/memory_eng.h"

#include <stdio.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdlib.h>

// --- Test helpers ---

static int tests_run    = 0;
static int tests_passed = 0;

#define TEST(name) static void name(void)

#define RUN(name) \
    do { \
        printf("  %-45s", #name); \
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

// -----------------------------------------------------------------------
// Tests
// -----------------------------------------------------------------------

// 1. table_init() returns a non-NULL pointer
TEST(test_table_init_not_null) {
    Table *t = table_init();
    ASSERT(t != NULL);
    free_table(t);
}

// 2. free_table() doesn't crash on a freshly-initialised table
TEST(test_free_table_no_crash) {
    Table *t = table_init();
    ASSERT(t != NULL);
    free_table(t);
}

// 3. write_mem() returns 0 (success) for a simple single-byte write
//    with create_page = 1 so the page is allocated on demand
TEST(test_write_mem_single_byte) {
    Table *t = table_init();
    ASSERT(t != NULL);

    uint8_t data = 0xAB;
    int ret = write_mem(t, 0x1000, &data, 1, 1);
    ASSERT(ret == 0);

    free_table(t);
}

// 4. read_mem() retrieves exactly the byte that was written
TEST(test_read_mem_single_byte_roundtrip) {
    Table *t = table_init();
    ASSERT(t != NULL);

    uint8_t written = 0xCD;
    ASSERT(write_mem(t, 0x2000, &written, 1, 1) == 0);

    uint8_t result = 0x00;
    int ret = read_mem(t, 0x2000, &result, 1);
    ASSERT(ret == 0);
    ASSERT(result == written);

    free_table(t);
}

// 5. Multi-byte write / read roundtrip
TEST(test_write_read_multi_byte) {
    Table *t = table_init();
    ASSERT(t != NULL);

    uint8_t src[8] = {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
    ASSERT(write_mem(t, 0x3000, src, sizeof(src), 1) == 0);

    uint8_t dst[8] = {0};
    ASSERT(read_mem(t, 0x3000, dst, sizeof(dst)) == 0);
    ASSERT(memcmp(src, dst, sizeof(src)) == 0);

    free_table(t);
}

// 6. Two independent writes to different addresses don't overlap
TEST(test_two_writes_independent) {
    Table *t = table_init();
    ASSERT(t != NULL);

    uint8_t a = 0xAA, b = 0xBB;
    ASSERT(write_mem(t, 0x4000, &a, 1, 1) == 0);
    ASSERT(write_mem(t, 0x5000, &b, 1, 1) == 0);

    uint8_t ra = 0, rb = 0;
    ASSERT(read_mem(t, 0x4000, &ra, 1) == 0);
    ASSERT(read_mem(t, 0x5000, &rb, 1) == 0);
    ASSERT(ra == 0xAA);
    ASSERT(rb == 0xBB);

    free_table(t);
}

// 7. Overwriting the same address reflects the latest value
TEST(test_overwrite_same_address) {
    Table *t = table_init();
    ASSERT(t != NULL);

    uint8_t v1 = 0x11;
    ASSERT(write_mem(t, 0x6000, &v1, 1, 1) == 0);

    uint8_t v2 = 0x22;
    ASSERT(write_mem(t, 0x6000, &v2, 1, 0) == 0);

    uint8_t result = 0;
    ASSERT(read_mem(t, 0x6000, &result, 1) == 0);
    ASSERT(result == 0x22);

    free_table(t);
}

// 8. write_mem() with create_page = 0 on a non-existent page should fail
TEST(test_write_no_create_page_fails) {
    Table *t = table_init();
    ASSERT(t != NULL);

    uint8_t data = 0xFF;
    int ret = write_mem(t, 0xDEAD0000ULL, &data, 1, 0);
    ASSERT(ret != 0);

    free_table(t);
}

// 9. read_mem() on an unmapped address should fail
TEST(test_read_unmapped_address_fails) {
    Table *t = table_init();
    ASSERT(t != NULL);

    uint8_t result = 0;
    int ret = read_mem(t, 0xBEEF0000ULL, &result, 1);
    ASSERT(ret != 0);

    free_table(t);
}

// 10. Large address (high 64-bit value) roundtrip
TEST(test_large_address_roundtrip) {
    Table *t = table_init();
    ASSERT(t != NULL);

    uint64_t addr = 0xFFFFFFFF00000000ULL;
    uint8_t  src  = 0x7E;
    ASSERT(write_mem(t, addr, &src, 1, 1) == 0);

    uint8_t dst = 0;
    ASSERT(read_mem(t, addr, &dst, 1) == 0);
    ASSERT(dst == src);

    free_table(t);
}

// 11. Page Crossing (Writing and reading across a 4KB boundary)
TEST(test_page_boundary_crossing) {
    Table *t = table_init();
    ASSERT(t != NULL);

    // Address 0x0FFC is exactly 4 bytes before the end of the first 4KB page
    // Writing 8 bytes here will place 4 bytes in page 0, and 4 bytes in page 1
    uint64_t addr = 0x0FFC;
    uint8_t src[8] = {0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88};

    // Should successfully map both pages and split the write
    ASSERT(write_mem(t, addr, src, 8, 1) == 0);

    uint8_t dst[8] = {0};
    // Should successfully traverse both pages to read the full block back
    ASSERT(read_mem(t, addr, dst, 8) == 0);
    ASSERT(memcmp(src, dst, 8) == 0);

    free_table(t);
}

// -----------------------------------------------------------------------
// Entry point
// -----------------------------------------------------------------------

int main(void) {
    printf("=== MMU Memory Engine Tests ===\n\n");

    RUN(test_table_init_not_null);
    RUN(test_free_table_no_crash);
    RUN(test_write_mem_single_byte);
    RUN(test_read_mem_single_byte_roundtrip);
    RUN(test_write_read_multi_byte);
    RUN(test_two_writes_independent);
    RUN(test_overwrite_same_address);
    RUN(test_write_no_create_page_fails);
    RUN(test_read_unmapped_address_fails);
    RUN(test_large_address_roundtrip);
    RUN(test_page_boundary_crossing);

    printf("\n%d / %d tests passed.\n", tests_passed, tests_run);
    return (tests_passed == tests_run) ? 0 : 1;
}
