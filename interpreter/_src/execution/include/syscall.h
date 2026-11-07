#ifndef SYSCALL_H
#define SYSCALL_H

#include <stdint.h>
#include <stddef.h>

// Compilation command: gcc -O3 -shared -o libscl.so -fPIC syscall.c

/**
 * @brief Performs a real read from a file descriptor.
 * * Reads up to `size` bytes from the real stream mapped to `fd` into `buffer`.
 * * fd 0/1/2 map to stdin/stdout/stderr; any other fd is treated as a real
 * * file descriptor previously returned by sys_open.
 * * `buffer` is a plain host-allocated byte array, NOT a simulated memory
 * * address — the Python side is responsible for copying the result into
 * * simulated memory afterwards.
 * @param fd File descriptor (0/1/2 for std streams, or a real fd from sys_open)
 * @param buffer Buffer to read into, must be at least `size` bytes
 * @param size Number of bytes to read
 * @return Number of bytes actually read, or -1 on error / unknown fd
 */
int64_t sys_read(int fd, uint8_t *buffer, size_t size);

/**
 * @brief Performs a real write to a file descriptor.
 * * Writes `size` bytes from `buffer` to the real stream mapped to `fd`.
 * * fd 0/1/2 map to stdin/stdout/stderr; any other fd is treated as a real
 * * file descriptor previously returned by sys_open.
 * * `buffer` is a plain host-allocated byte array that the Python side has
 * * already populated from simulated memory.
 * @param fd File descriptor (0/1/2 for std streams, or a real fd from sys_open)
 * @param buffer Buffer to write from, must contain at least `size` bytes
 * @param size Number of bytes to write
 * @return Number of bytes actually written, or -1 on error / unknown fd
 */
int64_t sys_write(int fd, const uint8_t *buffer, size_t size);

/**
 * @brief Opens a real file.
 * * Thin wrapper around the real open(2) syscall. `path` is a plain
 * * NUL-terminated string — the Python side is responsible for reading
 * * the path string out of simulated memory first.
 * @param path NUL-terminated path to the file to open
 * @param flags Real O_* flags (O_RDONLY, O_WRONLY, O_RDWR, O_CREAT, O_TRUNC, O_APPEND, ...)
 * @param mode Permission bits used only when O_CREAT is set (e.g. 0644)
 * @return A real file descriptor (>= 0) on success, or -1 on error
 */
int64_t sys_open(const char *path, int flags, int mode);

/**
 * @brief Closes a real file descriptor previously returned by sys_open.
 * @param fd File descriptor to close
 * @return 0 on success, or -1 on error
 * @warning Does not accept 0/1/2 — closing the standard streams is not supported
 */
int64_t sys_close(int fd);

/**
 * @brief Fills `buffer` with `size` bytes of random data from CSPRNG.
 * * Thin wrapper around the real getrandom(2) syscall (falls back to /dev/urandom
 * * if getrandom(2) is unavailable on the).
 * @param buffer Buffer to fill with random bytes, must be at least `size` bytes
 * @param size Number of random bytes requested
 * @return Number of random bytes actually written to `buffer`, or -1 on error
 */
int64_t sys_getrandom(uint8_t *buffer, size_t size);

// To complete with more syscalls

#endif // SYSCALL_H
