section .data
    msg: db "hi", 0x0a
    msg_len equ: 3

section .text
    global _start

_start:
    mov rax, 60
    xor rdi, rdi
    syscall
