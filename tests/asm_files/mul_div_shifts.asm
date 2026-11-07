section .text
global _start

_start:
    ; --- Multiplication Test ---
    mov rax, 5
    mov rbx, 10
    mul rbx             ; Test basic unsigned multiplication

    ; --- Unsigned Division Test ---
    mov rax, 100
    xor rdx, rdx
    mov rbx, 3
    div rbx             ; Test unsigned division

    ; --- Positive Signed Division Test ---
    mov rax, 100
    xor rdx, rdx
    mov rbx, 3
    idiv rbx            ; Test signed division with positive operands

    ; --- Shift Operations ---
    mov rax, 0xF0
    shl rax, 2          ; Shift Left
    shr rax, 2          ; Shift Right Logical
    sar rax, 1          ; Shift Right Arithmetic

    ; --- Rotate Operations ---
    mov rbx, 0x03
    rol rbx, 2          ; Rotate Left
    ror rbx, 2          ; Rotate Right

    ; --- Carry-Through Rotates ---
    mov rcx, 0x05
    rcl rcx, 1          ; Rotate Through Carry Left
    rcr rcx, 1          ; Rotate Through Carry Right

    ; Exit syscall (Linux x86-64)
    mov rax, 60
    xor rdi, rdi
    syscall
