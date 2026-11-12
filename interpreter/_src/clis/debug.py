from typing import Any, ClassVar

from textual.app import App, ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, RichLog, Static

from interpreter._src.parsing.debugger import Debugger, StopReason


class DebugCLI(App[None]):
    CSS_PATH = "debug.tcss"

    def __init__(self, debugger: Debugger) -> None:
        super().__init__()
        self.debugger: Debugger = debugger
        self.command_history: list[str] = []
        self.history_index: int = -1

    BINDINGS: ClassVar[list[BindingType]] = [
        ("d", "toggle_dark", "Toggle Dark Mode"),
        ("q", "quit", "Quit"),
        ("up", "history_up", "Previous Command"),
        ("down", "history_down", "Next Command"),
    ]

    def on_mount(self) -> None:
        self.update_panels()
        self.query_one("#debug_input").focus()

    def action_toggle_dark(self) -> None:
        self.theme = (
            "textual-dark" if self.theme == "textual-light" else "textual-light"
        )

    async def action_quit(self) -> None:
        self.exit()

    def action_history_up(self) -> None:
        if not self.command_history:
            return
        if self.history_index < len(self.command_history) - 1:
            self.history_index += 1
            cmd = self.command_history[-(self.history_index + 1)]
            self.query_one("#debug_input", Input).value = cmd

    def action_history_down(self) -> None:
        if not self.command_history:
            return
        if self.history_index > 0:
            self.history_index -= 1
            cmd = self.command_history[-(self.history_index + 1)]
            self.query_one("#debug_input", Input).value = cmd
        elif self.history_index == 0:
            self.history_index = -1
            self.query_one("#debug_input", Input).value = ""

    def on_input_submitted(self, event: Input.Submitted) -> None:
        user_input = event.value.strip()
        if not user_input:
            return

        self.command_history.append(user_input)
        self.history_index = -1
        event.input.value = ""

        result = self.debugger.submit(user_input)

        output_log = self.query_one(".debug_output", RichLog)
        output_log.write(f"[bold cyan]>>> {user_input}[/bold cyan]")

        for line in result.lines:
            output_log.write(line)
        if result.output:
            output_log.write(result.output)

        self.update_panels()

        if result.quit:
            self.exit()
            return

        if result.stop and result.stop.reason in (
            StopReason.FINISHED,
            StopReason.EXITED,
            StopReason.FAULT,
        ):
            output_log.write(
                f"\n[bold red]Execution stopped: {result.stop.reason.value}[/bold red]"
            )

    def get_ui_state(self) -> dict[str, Any]:
        return {
            "registers": self.debugger.read_registers(num_rep=16),
            "flags": self.debugger.read_registers("eflags", num_rep=2),
        }

    def update_panels(self) -> None:
        program_widget = self.query_one(".program Static", Static)
        program_widget.update("\n".join(self.debugger.program_lines()))

        state = self.get_ui_state()
        regs = state["registers"]

        reg_text = ""
        for r, val in regs.items():
            if r != "eflags":
                reg_text += f"[bold text-muted]{r.upper():<7}[/] {val}\n"

        flags_bin = state["flags"].get("eflags", "0")
        reg_text += f"\n[bold text-muted]EFLAGS[/]\n{flags_bin}"

        reg_widget = self.query_one(".registers Static", Static)
        reg_widget.update(reg_text)

    def compose(self) -> ComposeResult:
        with Horizontal():
            program_panel = Vertical(classes="program")
            program_panel.border_title = " Program Source "
            with program_panel:
                yield Static()

            with Vertical(classes="center_panel"):
                # New Help Panel
                help_panel = Vertical(classes="help_wrapper")
                help_panel.border_title = "  Commands "
                with help_panel:
                    yield Static(self.debugger.help_text(), classes="help_text")

                # Output Log
                output_panel = Vertical(classes="debug_wrapper")
                output_panel.border_title = " Output Log "
                with output_panel:
                    yield RichLog(highlight=True, markup=True, classes="debug_output")

                cmd_input = Input(placeholder=">>> ", id="debug_input")
                cmd_input.border_title = " Command Prompt "
                yield cmd_input

            # Registers Panel
            reg_panel = Vertical(classes="registers")
            reg_panel.border_title = " Registers "
            with reg_panel:
                yield Static(markup=True)
