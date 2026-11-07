; Test Program to exercise Segment_Mapper parsing
; Covers: .data, .rodata, .bss, #define, and equ

#define SYSTEM_EXIT 60
STDOUT: EQU 1

section .rodata
    greeting db 'Hello World', 0
    prompt   db 'Enter number: ', 0
    msg_len  equ $-prompt

section .data
    count    dd 10
    array    times 5 dd 0xFF ; Test 'times' directive
    is_valid db 1

section .bss
    buffer   resb 128        ; Test 'resb' reservation
    results  resq 1          ; Test 'resq' reservation

section .text
    global _start

_start:
    ; This is a dummy start label
    mov rax, SYSTEM_EXIT
    mov rdi, 0
    ; The interpreter will start here
