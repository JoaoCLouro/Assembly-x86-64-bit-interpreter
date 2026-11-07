#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <assert.h>
#include "../../execution/include/syscall.h"

// Helper macros for colored test output
#define PRINT_SUCCESS(msg) printf("\033[0;32m[PASS]\033[0m %s\n", msg)
#define PRINT_FAIL(msg)    printf("\033[0;31m[FAIL]\033[0m %s\n", msg)

// ==========================================
// STDIO TESTS (0, 1, 2)
// ==========================================

void test_sys_write_stdout() {
    int p[2];
    assert(pipe(p) == 0);

    // Save current stdout and redirect fd 1 to the pipe
    int old_stdout = dup(STDOUT_FILENO);
    dup2(p[1], STDOUT_FILENO);

    const char* msg = "Hello, simulated stdout!";
    size_t msg_len = strlen(msg);

    // Execute
    int64_t bytes_written = sys_write(1, (const uint8_t*)msg, msg_len);

    // Restore original stdout
    fflush(stdout);
    dup2(old_stdout, STDOUT_FILENO);
    close(old_stdout);

    // Read the result
    char buffer[256] = {0};
    read(p[0], buffer, sizeof(buffer));

    close(p[0]);
    close(p[1]);

    // Assertions
    assert(bytes_written == (int64_t)msg_len);
    assert(strcmp(buffer, msg) == 0);

    PRINT_SUCCESS("sys_write to stdout (fd=1)");
}

void test_sys_read_stdin() {
    int p[2];
    assert(pipe(p) == 0);

    // Save current stdin and redirect fd 0 to the pipe
    int old_stdin = dup(STDIN_FILENO);
    dup2(p[0], STDIN_FILENO);

    // Provide mock data
    const char* input_data = "MockInput";
    size_t input_len = strlen(input_data);
    write(p[1], input_data, input_len);

    // Execute
    uint8_t buffer[256] = {0};
    int64_t bytes_read = sys_read(0, buffer, input_len);

    // Restore original stdin
    dup2(old_stdin, STDIN_FILENO);
    close(old_stdin);

    close(p[0]);
    close(p[1]);

    // Assertions
    assert(bytes_read == (int64_t)input_len);
    assert(memcmp(buffer, input_data, input_len) == 0);

    PRINT_SUCCESS("sys_read from stdin (fd=0)");
}

// ==========================================
// FILE I/O TESTS
// ==========================================

void test_file_io_lifecycle() {
    const char *test_file = "test_io_temp.txt";
    const uint8_t write_data[] = "System Call Test Data";
    size_t data_len = sizeof(write_data);
    uint8_t read_buffer[64] = {0};

    // 1. Test sys_open (Create / Write Only)
    int64_t fd_write = sys_open(test_file, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    assert(fd_write >= 3); // Must not step on std streams

    // 2. Test sys_write (To real file)
    int64_t bytes_written = sys_write(fd_write, write_data, data_len);
    assert(bytes_written == (int64_t)data_len);

    // 3. Test sys_close (Write file)
    int64_t close_res = sys_close(fd_write);
    assert(close_res == 0);

    // 4. Test sys_open (Read Only)
    int64_t fd_read = sys_open(test_file, O_RDONLY, 0);
    assert(fd_read >= 3);

    // 5. Test sys_read (From real file)
    int64_t bytes_read = sys_read(fd_read, read_buffer, data_len);
    assert(bytes_read == (int64_t)data_len);
    assert(memcmp(read_buffer, write_data, data_len) == 0);

    // 6. Test sys_close (Read file)
    close_res = sys_close(fd_read);
    assert(close_res == 0);

    // Cleanup
    unlink(test_file);

    PRINT_SUCCESS("File I/O lifecycle (sys_open, sys_write, sys_read, sys_close)");
}

void test_sys_close_protections() {
    // Standard streams should be protected
    assert(sys_close(0) == -1);
    assert(sys_close(1) == -1);
    assert(sys_close(2) == -1);

    // Invalid FDs
    assert(sys_close(-1) == -1);
    assert(sys_close(9999) == -1);

    PRINT_SUCCESS("sys_close protects std streams and handles invalid FDs");
}

// ==========================================
// INVALID FD TESTS
// ==========================================

void test_invalid_fds() {
    uint8_t buffer[10] = {0};

    // Test with completely out-of-bounds FDs (not mapped to open files)
    assert(sys_read(9999, buffer, sizeof(buffer)) == -1);
    assert(sys_read(-1, buffer, sizeof(buffer)) == -1);

    assert(sys_write(9999, buffer, sizeof(buffer)) == -1);
    assert(sys_write(-1, buffer, sizeof(buffer)) == -1);

    PRINT_SUCCESS("sys_read and sys_write properly reject invalid FDs");
}

// ==========================================
// GETRANDOM TEST
// ==========================================

void test_sys_getrandom() {
    uint8_t buf1[32] = {0};
    uint8_t buf2[32] = {0};

    int64_t res1 = sys_getrandom(buf1, sizeof(buf1));
    assert(res1 == (int64_t)sizeof(buf1));

    int64_t res2 = sys_getrandom(buf2, sizeof(buf2));
    assert(res2 == (int64_t)sizeof(buf2));

    // Probability of identical 32-byte arrays from CSPRNG is astronomically low
    assert(memcmp(buf1, buf2, sizeof(buf1)) != 0);

    PRINT_SUCCESS("sys_getrandom successfully fetches random bytes");
}

int main() {
    printf("Starting complete syscall integration tests...\n");
    printf("--------------------------------------------\n");

    // Standard stream I/O tests
    test_sys_write_stdout();
    test_sys_read_stdin();

    // New File I/O lifecycle tests
    test_file_io_lifecycle();
    test_sys_close_protections();
    test_invalid_fds();

    // Getrandom test
    test_sys_getrandom();

    printf("--------------------------------------------\n");
    printf("\033[0;32mALL TESTS PASSED SUCCESSFULLY.\033[0m\n");

    return 0;
}
