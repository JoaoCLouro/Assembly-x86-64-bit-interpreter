; basic_alu_loop.asm
; Demonstrates simple ALU operations and manual looping using cmp and jumps
; No printing, no arrays or vectors
; Intel syntax (NASM style)


section .text
global _start


_start:
; --- ALU OPERATIONS ---
mov eax, 10
xor ebx, ebx


; --- SIMPLE LOOP ---
_loopStart:
cmp ebx, 3
je _loopEnd
add eax, 2 ; example operation inside loop
inc ebx; increment counter
jmp _loopStart


_loopEnd:
; --- EXIT ---
mov rax, 60 ; syscall: exit
xor rdi, rdi
syscall
