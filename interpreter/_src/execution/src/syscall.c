#include "../include/syscall.h"

#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>

#if defined(__linux__)
#include <sys/random.h>
#endif

// Resolves a simulated/real fd to a real fd usable with read(2)/write(2).
// fd 0/1/2 map straight to the standard streams. Any other value is assumed
// to be a real fd previously handed back by sys_open, and is passed through
// as-is (the host kernel will reject it if it's not actually open).
static int resolve_fd(int fd)
{
    return fd;
}

int64_t sys_read(int fd, uint8_t *buffer, size_t size)
{
    int real_fd = resolve_fd(fd);
    ssize_t read_count = read(real_fd, buffer, size);
    if (read_count < 0)
    {
        return -1;
    }
    return (int64_t) read_count;
}

int64_t sys_write(int fd, const uint8_t *buffer, size_t size)
{
    int real_fd = resolve_fd(fd);
    ssize_t written_count = write(real_fd, buffer, size);
    if (written_count < 0)
    {
        return -1;
    }
    return (int64_t) written_count;
}

int64_t sys_open(const char *path, int flags, int mode)
{
    int fd = open(path, flags, mode);
    if (fd < 0)
    {
        return -1;
    }
    return (int64_t) fd;
}

int64_t sys_close(int fd)
{
    // Refuse to close the standard streams through this path
    // treats 0/1/2 as always-open.
    if (fd == 0 || fd == 1 || fd == 2)
    {
        return -1;
    }

    if (close(fd) < 0)
    {
        return -1;
    }
    return 0;
}

int64_t sys_getrandom(uint8_t *buffer, size_t size)
{
#if defined(__linux__)
    ssize_t got = getrandom(buffer, size, 0);
    if (got < 0)
    {
        return -1;
    }
    return (int64_t) got;
#else
    // Fallback for non-Linux hosts: read from /dev/urandom
    FILE* urandom = fopen("/dev/urandom", "rb");
    if (!urandom)
    {
        return -1;
    }
    size_t got = fread(buffer, sizeof(uint8_t), size, urandom);
    fclose(urandom);
    return (int64_t) got;
#endif
}
