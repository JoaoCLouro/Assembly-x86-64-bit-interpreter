; basic_alu_flow_control.asm
; Demonstrates simple ALU operations and flow control
; Memory addressing allowed only for second operand (no base/index)


section .data
val1 dd 5
val2 dd 2


section .text
global _start


_start:
; --- ALU OPERATIONS ---
mov eax, 10 ; load immediate value
add eax, [val1] ; eax = eax + val1 (10 + 5 = 15)
sub eax, [val2] ; eax = eax - val2 (15 - 2 = 13)
inc eax ; eax = 14


xor ebx, ebx ; ebx = 0
or ebx, [val2] ; ebx = ebx OR val2 (0 OR 2 = 2)
and eax, [val1] ; eax = eax AND val1 (14 AND 5 = 4)


; --- FLOW CONTROL ---
cmp eax, 4 ; compare eax with 4
jne _not_equal ; jump if not equal


; equal case
mov ecx, 1
jmp _end_program


_not_equal:
mov ecx, 0
cmp rdi, 5
jne _outro


_outro:
mov rdi, 5
jmp _start


_end_program:
; exit system call (Linux)
mov rax, 60 ; syscall: exit
xor rdi, rdi
syscall
