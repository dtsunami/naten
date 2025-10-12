"""Shell mode manager for da_code CLI."""

import logging
import subprocess
import time

from .ux import console

logger = logging.getLogger(__name__)


class ShellModeManager:
    """Manages shell mode and captures command output for agent context."""

    def __init__(self):
        self.is_shell_mode = False
        self.shell_history = []
        self.max_history_entries = 50
        self.shell_command_history = []  # Separate history for shell commands only

    def toggle_shell_mode(self):
        """Toggle between shell mode and agent mode."""
        self.is_shell_mode = not self.is_shell_mode
        mode_name = "shell" if self.is_shell_mode else "agent"
        console.print(f"[cyan]🔧 Switched to {mode_name} mode[/cyan]")

    def execute_shell_command(self, command: str) -> str:
        """Execute shell command and capture output."""
        # Add command to shell command history for up/down arrow navigation
        if command.strip() and (not self.shell_command_history or command != self.shell_command_history[-1]):
            self.shell_command_history.append(command)
            # Keep shell command history manageable
            if len(self.shell_command_history) > 1000:
                self.shell_command_history = self.shell_command_history[-1000:]

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30
            )

            # Combine stdout and stderr
            output = ""
            if result.stdout:
                output += result.stdout
            if result.stderr:
                output += f"\nSTDERR:\n{result.stderr}"

            # Add to history for agent context
            self.shell_history.append({
                'command': command,
                'output': output,
                'return_code': result.returncode,
                'timestamp': time.time()
            })

            # Keep only recent entries
            if len(self.shell_history) > self.max_history_entries:
                self.shell_history = self.shell_history[-self.max_history_entries:]

            return output

        except subprocess.TimeoutExpired:
            error_msg = f"Command timed out after 30 seconds: {command}"
            self.shell_history.append({
                'command': command,
                'output': error_msg,
                'return_code': -1,
                'timestamp': time.time()
            })
            return error_msg

        except Exception as e:
            error_msg = f"Shell execution error: {str(e)}"
            self.shell_history.append({
                'command': command,
                'output': error_msg,
                'return_code': -1,
                'timestamp': time.time()
            })
            return error_msg

    def get_shell_context_for_agent(self) -> str:
        """Get recent shell commands and output as context for the agent."""
        if not self.shell_history:
            return ""

        context_lines = ["Recent shell commands and their output:"]

        # Get last 5 commands for context
        recent_commands = self.shell_history[-5:]

        for entry in recent_commands:
            context_lines.append(f"\n$ {entry['command']}")
            if entry['return_code'] == 0:
                context_lines.append(f"Output:\n{entry['output'][:1000]}")  # Limit output length
            else:
                context_lines.append(f"Error (code {entry['return_code']}):\n{entry['output'][:1000]}")

        return "\n".join(context_lines)