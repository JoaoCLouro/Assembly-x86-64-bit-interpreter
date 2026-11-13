#include "../include/syscall.h"

#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <fcntl.h>
#include <errno.h>
#include <limits.h>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <bcrypt.h>
#include <io.h>
#include <sys/stat.h>
#ifdef _MSC_VER
#pragma comment(lib, "bcrypt.lib")
#endif
#else
#include <unistd.h>
#if defined(__linux__)
#include <sys/random.h>
#endif
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
#ifdef _WIN32
    unsigned int chunk = (size > UINT_MAX) ? UINT_MAX : (unsigned int) size;
    int read_count = _read(real_fd, buffer, chunk);
    if (read_count < 0)
    {
        return -1;
    }
    return (int64_t) read_count;
#else
    ssize_t read_count = read(real_fd, buffer, size);
    if (read_count < 0)
    {
        return -1;
    }
    return (int64_t) read_count;
#endif
}

int64_t sys_write(int fd, const uint8_t *buffer, size_t size)
{
    int real_fd = resolve_fd(fd);
#ifdef _WIN32
    unsigned int chunk = (size > UINT_MAX) ? UINT_MAX : (unsigned int) size;
    int written_count = _write(real_fd, buffer, chunk);
    if (written_count < 0)
    {
        return -1;
    }
    return (int64_t) written_count;
#else
    ssize_t written_count = write(real_fd, buffer, size);
    if (written_count < 0)
    {
        return -1;
    }
    return (int64_t) written_count;
#endif
}

int64_t sys_open(const char *path, int flags, int mode)
{
#ifdef _WIN32
    // Translate Linux x86-64 open(2) flags to Windows CRT _open flags
    int win_flags = _O_BINARY;
    switch (flags & 3)
    {
        case 1:  win_flags |= _O_WRONLY; break;
        case 2:  win_flags |= _O_RDWR;   break;
        default: win_flags |= _O_RDONLY; break;
    }
    if (flags & 0100)  win_flags |= _O_CREAT;
    if (flags & 0200)  win_flags |= _O_EXCL;
    if (flags & 01000) win_flags |= _O_TRUNC;
    if (flags & 02000) win_flags |= _O_APPEND;

    int win_mode = 0;
    if (mode & 0400) win_mode |= _S_IREAD;
    if (mode & 0200) win_mode |= _S_IWRITE;
    if (win_mode == 0 && (win_flags & _O_CREAT))
    {
        win_mode = _S_IREAD | _S_IWRITE;
    }

    int fd = _open(path, win_flags, win_mode);
#else
    int fd = open(path, flags, mode);
#endif
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

#ifdef _WIN32
    if (_close(fd) < 0)
#else
    if (close(fd) < 0)
#endif
    {
        return -1;
    }
    return 0;
}

int64_t sys_getrandom(uint8_t *buffer, size_t size)
{
#ifdef _WIN32
    size_t total = 0;
    while (total < size)
    {
        ULONG chunk = (size - total > ULONG_MAX) ? ULONG_MAX : (ULONG) (size - total);
        if (!BCRYPT_SUCCESS(BCryptGenRandom(NULL, buffer + total, chunk, BCRYPT_USE_SYSTEM_PREFERRED_RNG)))
        {
            return (total > 0) ? (int64_t) total : -1;
        }
        total += chunk;
    }
    return (int64_t) total;
#elif defined(__linux__)
    ssize_t got = getrandom(buffer, size, 0);
    if (got < 0)
    {
        return -1;
    }
    return (int64_t) got;
#else
    // Fallback for non-Linux POSIX hosts: read from /dev/urandom
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

#ifdef _WIN32
__declspec(dllexport) void* PyInit_libsyscall(void) { return 0; }
#endif
