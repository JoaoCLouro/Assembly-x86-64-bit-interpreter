section .data
    a dq 5
    b dq 3

section .text
    global _start

_start:
    ; Carregar valores
    mov rax, [a]
    mov rbx, [b]

    ; -----------------------
    ; Aritmética da ALU
    ; -----------------------

    add rax, rbx          ; rax = a + b

    ; -----------------------
    ; Operações lógicas
    ; -----------------------

    xor rbx, rax          ; rbx = b XOR (a+b)
    not rax               ; rax = NOT (a+b)

    ; Terminar o programa
    mov rax, 60
    xor rdi, rdi          ; syscall: exit
    syscall
