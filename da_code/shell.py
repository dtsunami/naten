"""Child process shell management with user confirmation."""

import asyncio
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple

from .models import CommandExecution, CommandStatus, UserResponse
from .ui_modern import modern_ui

logger = logging.getLogger(__name__)


class ShellExecutor:
    """Manages shell command execution with user confirmation."""

    def __init__(self, default_timeout: int = 300):
        """Initialize shell executor."""
        self.default_timeout = default_timeout

    async def execute_with_confirmation(self, execution: CommandExecution) -> CommandExecution:
        """Execute command after getting user confirmation."""
        # Use modern UI for confirmation (respects DA_CODE_AUTO_ACCEPT)
        response = await modern_ui.confirm_command(
            command=execution.command,
            explanation=execution.explanation or "",
            working_directory=execution.working_directory,
            reasoning=execution.agent_reasoning or "",
            related_files=execution.related_files or []
        )

        if response == "no":
            execution.update_status(CommandStatus.DENIED)
            print("❌ Command execution cancelled by user.")
            return execution

        elif response == "modify":
            # Allow user to modify command
            modified_command = await modern_ui.get_command_modification(execution.command)
            if modified_command:
                execution.user_modifications = modified_command
                execution.command = modified_command
                modern_ui.show_success(f"Command modified to: {modified_command}")
            else:
                execution.update_status(CommandStatus.DENIED)
                modern_ui.show_warning("Command execution cancelled.")
                return execution

        elif response == "explain":
            # Show detailed explanation and ask again
            self._display_detailed_explanation(execution)
            return await self.execute_with_confirmation(execution)

        # Execute the approved command
        execution.user_response = UserResponse.YES
        execution.update_status(CommandStatus.APPROVED)
        return await self._execute_command(execution)

    def _display_command_info(self, execution: CommandExecution) -> None:
        """Display command information to the user."""
        print("\n" + "="*60)
        print("🤖 Agent wants to execute a command:")
        print("="*60)
        print(f"Command: {execution.command}")
        print(f"Directory: {execution.working_directory}")

        if execution.explanation:
            print(f"Purpose: {execution.explanation}")

        if execution.agent_reasoning:
            print(f"Reasoning: {execution.agent_reasoning}")

        if execution.related_files:
            print(f"Related files: {', '.join(execution.related_files)}")

        print("="*60)

    async def _get_user_confirmation(self, execution: CommandExecution) -> UserResponse:
        """Get user confirmation for command execution."""
        while True:
            try:
                # Create confirmation prompt
                prompt = self._create_confirmation_prompt(execution)
                execution.user_prompt = prompt

                print(prompt)
                user_input = input("Your choice: ").strip().lower()

                if user_input in ['y', 'yes', '1']:
                    return UserResponse.YES
                elif user_input in ['n', 'no', '2']:
                    return UserResponse.NO
                elif user_input in ['m', 'modify', '3']:
                    return UserResponse.MODIFY
                elif user_input in ['e', 'explain', '4']:
                    return UserResponse.EXPLAIN
                else:
                    print("Invalid choice. Please enter y/n/m/e or 1/2/3/4")

            except (EOFError, KeyboardInterrupt):
                print("\n❌ Operation cancelled by user.")
                return UserResponse.NO

    def _create_confirmation_prompt(self, execution: CommandExecution) -> str:
        """Create confirmation prompt for user."""
        return """
Do you want to execute this command?
1. [Y]es - Execute the command
2. [N]o - Cancel execution
3. [M]odify - Edit the command
4. [E]xplain - Show more details

"""

    async def _get_command_modification(self, original_command: str) -> Optional[str]:
        """Allow user to modify the command."""
        try:
            print(f"\nOriginal command: {original_command}")
            print("Enter your modified command (or press Enter to cancel):")
            modified = input("Modified command: ").strip()

            if not modified:
                return None

            return modified

        except (EOFError, KeyboardInterrupt):
            return None

    def _display_detailed_explanation(self, execution: CommandExecution) -> None:
        """Display detailed explanation of the command."""
        print("\n" + "="*60)
        print("📋 Detailed Command Explanation:")
        print("="*60)

        # Break down the command
        parts = execution.command.split()
        if parts:
            print(f"Base command: {parts[0]}")
            if len(parts) > 1:
                print(f"Arguments: {' '.join(parts[1:])}")

        # Show working directory impact
        print(f"\nWorking directory: {execution.working_directory}")
        print(f"Timeout: {execution.timeout_seconds} seconds")

        # Show potential risks
        self._show_command_risks(execution.command)

        # Show expected outcome
        if execution.explanation:
            print(f"\nExpected outcome: {execution.explanation}")

        if execution.agent_reasoning:
            print(f"Agent reasoning: {execution.agent_reasoning}")

        print("="*60)

    def _show_command_risks(self, command: str) -> None:
        """Show potential risks of the command."""
        risks = []
        cmd_lower = command.lower()

        if any(dangerous in cmd_lower for dangerous in ['rm -rf', 'sudo rm', 'format', 'fdisk']):
            risks.append("⚠️  DESTRUCTIVE: This command may delete files or modify system")

        if 'sudo' in cmd_lower:
            risks.append("🔒 PRIVILEGED: This command requires administrator privileges")

        if any(net in cmd_lower for net in ['curl', 'wget', 'git clone', 'pip install']):
            risks.append("🌐 NETWORK: This command will access the internet")

        if any(sys in cmd_lower for sys in ['systemctl', 'service', 'kill', 'pkill']):
            risks.append("⚙️  SYSTEM: This command affects system services or processes")

        if risks:
            print("\n🚨 Potential risks:")
            for risk in risks:
                print(f"  {risk}")

    async def _execute_command(self, execution: CommandExecution) -> CommandExecution:
        """Execute the approved command."""
        execution.update_status(CommandStatus.EXECUTING)

        # Use async UI for better command execution feedback
        start_time = time.time()

        try:
            # Change to working directory
            original_cwd = os.getcwd()
            if execution.working_directory and Path(execution.working_directory).exists():
                os.chdir(execution.working_directory)

            # Execute command with timeout
            process = await asyncio.create_subprocess_shell(
                execution.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=execution.working_directory
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=execution.timeout_seconds
                )

                execution_time = time.time() - start_time

                # Decode output
                stdout_text = stdout.decode('utf-8', errors='replace') if stdout else ''
                stderr_text = stderr.decode('utf-8', errors='replace') if stderr else ''

                # Set results
                execution.set_result(
                    exit_code=process.returncode or 0,
                    stdout=stdout_text,
                    stderr=stderr_text,
                    execution_time=execution_time
                )

                # Display results (cleaner format)
                self._display_execution_results_clean(execution)

            except asyncio.TimeoutError:
                # Kill the process
                process.terminate()
                await process.wait()

                execution.update_status(CommandStatus.TIMEOUT)
                execution.execution_time = time.time() - start_time

                print(f"⏰ Command timed out after {execution.timeout_seconds} seconds")

            finally:
                # Restore original working directory
                os.chdir(original_cwd)

        except Exception as e:
            execution_time = time.time() - start_time
            execution.update_status(CommandStatus.FAILED)
            execution.execution_time = execution_time
            execution.stderr = str(e)

            print(f"💥 Command failed: {e}")
            logger.error(f"Command execution error: {e}")

        return execution

    def _display_execution_results(self, execution: CommandExecution) -> None:
        """Display command execution results."""
        print("\n" + "-"*60)

        if execution.status == CommandStatus.SUCCESS:
            print("✅ Command completed successfully")
        else:
            print("❌ Command failed")

        print(f"Exit code: {execution.exit_code}")
        print(f"Execution time: {execution.execution_time:.2f} seconds")

        if execution.stdout:
            print("\n📤 Output:")
            print(execution.stdout)

        if execution.stderr:
            print("\n🚫 Error output:")
            print(execution.stderr)

        print("-"*60)

    def _display_execution_results_clean(self, execution: CommandExecution) -> None:
        """Display command execution results in a clean format."""
        if execution.status == CommandStatus.SUCCESS:
            print(f"✅ Completed ({execution.execution_time:.2f}s)")
            if execution.stdout and execution.stdout.strip():
                # Show output but truncate if too long
                output = execution.stdout.strip()
                if len(output) > 500:
                    lines = output.split('\n')
                    if len(lines) > 10:
                        shown_lines = lines[:8] + ["...", f"[{len(lines) - 8} more lines]"]
                        output = '\n'.join(shown_lines)
                    else:
                        output = output[:500] + "..."
                print(f"📤 Output:\n{output}")
        else:
            print(f"❌ Failed (exit code: {execution.exit_code}, {execution.execution_time:.2f}s)")
            if execution.stderr and execution.stderr.strip():
                error = execution.stderr.strip()
                if len(error) > 300:
                    error = error[:300] + "..."
                print(f"🚫 Error: {error}")

    def execute_simple(self, command: str, working_directory: str = None, timeout: int = None) -> Tuple[int, str, str]:
        """Execute a simple command without confirmation (for system commands)."""
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=working_directory,
                timeout=timeout or self.default_timeout
            )

            return result.returncode, result.stdout, result.stderr

        except subprocess.TimeoutExpired:
            return -1, "", "Command timed out"
        except Exception as e:
            return -1, "", str(e)