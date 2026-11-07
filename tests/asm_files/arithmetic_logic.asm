; ==============================================================================
; EXPECTED FINAL STATE (Integration Test Reference)
; ==============================================================================
; Registers:
;   RAX = 60                   (Set by exit syscall code)
;   RBX = 0xAAAA               (Swapped from original RDX/RBX sequence)
;   RDI = 0                    (Zeroed for exit syscall status)
;   RCX, RDX, RSI, R8-R15 = 0  (Unmodified / Zeroed)
;
; Flags (RFLAGS):
;   CF (Carry Flag)      = 0
;   ZF (Zero Flag)       = 0
;   SF (Sign Flag)       = 0
;   OF (Overflow Flag)   = 0
;
; Memory:
;   [Data/BSS Segments]  = Unmodified / Zero (No explicit stores used)
; ==============================================================================

section .text
global _start

_start:
    ; --- Basic Arithmetic & Flags ---
    mov rax, 100
    add rax, 50         ; ADD
    adc rax, 1          ; ADC (Add with Carry)

    sub rax, 20         ; SUB
    sbb rax, 0          ; SBB (Subtract with Borrow)

    inc rax             ; INC
    dec rax             ; DEC

    neg rax             ; NEG (Two's complement negation)
    cmp rax, 130        ; CMP (Sets flags without altering destination)

    ; --- Bitwise Operations ---
    mov rbx, 0x0F0F0F0F
    and rbx, 0xFF00FF00 ; AND
    or rbx, 0x00FF00FF  ; OR
    xor rbx, rbx        ; XOR (Zero out register)
    not rbx             ; NOT (Bitwise inversion)

    ; --- Data Exchange ---
    mov rax, 0xAAAA
    mov rbx, 0x5555
    xchg rax, rbx       ; XCHG operands

    mov rax, 60
    xor rdi, rdi
    syscall
