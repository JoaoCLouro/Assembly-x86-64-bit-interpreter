section .text
global _start

_start:
    ; --- Decimal Tests (Baseline) ---
    mov rax, -100        ; Standard decimal
    mov rbx, -100d       ; 'd' suffixed decimal
    mov rcx, -0d100      ; '0d' prefixed decimal

    ; --- Hexadecimal Tests ---
    mov rdx, -0x1A       ; '0x' prefixed hex
    mov rsi, -1Ah        ; 'h' suffixed hex

    ; --- Binary Tests ---
    mov rdi, -0b1010     ; '0b' prefixed binary
    mov rbp, -1010b      ; 'b' suffixed binary

    ; --- Octal Tests ---
    mov r8, -020o        ; 'o' suffixed octal
    mov r9, -20q         ; 'q' suffixed octal

    ; Exit syscall (Linux x86-64)
    mov rax, 60
    xor rdi, rdi
    syscall
