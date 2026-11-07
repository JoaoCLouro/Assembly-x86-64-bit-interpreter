; Syscall test: write(1, msg, len) to stdout, then exit(60).
; This test is verified by capturing stdout (e.g. via monkeypatch on
; sys.stdout / os.write, or by redirecting fd 1) rather than by
; register/memory state alone, since the point is exercising the real
; write() syscall path.
;
; Expected behavior:
;   - stdout receives exactly "hi\n" (3 bytes)
;   - rax = 3 immediately after the write syscall (bytes written)
;   - process exits via the exit syscall, with the exit code sourced
;     from the 'exit_code' .data variable rather than hardcoded, exercising
;     both the write() path and unsized-memory-operand size inference
;     (mov rax, [exit_code] infers size 8 from rax, per assembly_specs.md 5.3)
;
; NOTE: 'exit' itself is NOT usable as a label/variable name here - the
; parser treats it as already in use (reserved), so 'exit_code' is used
; instead.

section .data
    msg: db "hi", 0x0a
    msg_len equ: 3
    exit_code: db 60

section .text
    global _start

_start:
    mov rax, 1          ; sys_write
    mov rdi, 1          ; fd = stdout
    mov rsi, msg
    mov rdx, msg_len
    syscall             ; rax now holds bytes written (expect 3)

    mov r8, rax         ; preserve write() return value before exit clobbers rax

    mov rax, [exit_code] ; exit code, size inferred as 8 bytes from rax
    xor rdi, rdi
    syscall
