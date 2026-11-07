section .data
    a: db 5
    b: db 15

section .rodata
    con: dq 10000

section .text
global _start
_start:
mov al, [a]
mov bl, [b]

_loop:
cmp al, bl
jb _loopident
jmp _fim

_loopident:
mov al, 50
jmp _loop

_fim:
mov rax, 60
mov rdi, 0
syscall
