"""Interactive UI components for da_code."""

import os
import sys
import tty
import termios
from typing import List, Optional


class InteractiveMenu:
    """Interactive menu with arrow key navigation."""

    def __init__(self, options: List[str], default_index: int = 0):
        """Initialize menu with options and default selection."""
        self.options = options
        self.selected = default_index
        self.default_index = default_index

    def show_menu(self, title: str = "", description: str = "") -> int:
        """Show interactive menu and return selected index."""
        try:
            # Check if we're in a terminal that supports interactive input
            if not sys.stdin.isatty():
                return self.fallback_menu(title, description)

            # Save terminal settings
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)

            try:
                # Set terminal to raw mode
                tty.setraw(sys.stdin.fileno())

                while True:
                    # Clear screen and show menu
                    self._render_menu(title, description)

                    # Get key input
                    key = self._get_key()

                    if key == 'up' and self.selected > 0:
                        self.selected -= 1
                    elif key == 'down' and self.selected < len(self.options) - 1:
                        self.selected += 1
                    elif key == 'enter':
                        return self.selected
                    elif key == 'escape':
                        return -1  # Cancelled

            finally:
                # Restore terminal settings
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

        except (OSError, termios.error):
            # Fallback to simple input if terminal control fails
            return self.fallback_menu(title, description)

    def fallback_menu(self, title: str = "", description: str = "") -> int:
        """Fallback menu for non-interactive terminals."""
        if title:
            print(f"\n{title}")
        if description:
            print(f"{description}\n")

        for i, option in enumerate(self.options):
            default_marker = " (default)" if i == self.default_index else ""
            print(f"{i + 1}. {option}{default_marker}")

        print(f"\nPress Enter for default ({self.options[self.default_index]}) or choose 1-{len(self.options)}:")

        while True:
            try:
                user_input = input("Choice: ").strip()

                if not user_input:
                    return self.default_index

                choice = int(user_input)
                if 1 <= choice <= len(self.options):
                    return choice - 1
                else:
                    print(f"Please enter a number between 1 and {len(self.options)}")

            except (ValueError, KeyboardInterrupt):
                print("Invalid input. Press Enter for default or enter a number.")

    def _render_menu(self, title: str, description: str) -> None:
        """Render the interactive menu."""
        # Clear screen
        print("\033[2J\033[H", end="")

        if title:
            print(f"\n{title}")
        if description:
            print(f"{description}\n")

        for i, option in enumerate(self.options):
            if i == self.selected:
                # Highlight selected option
                print(f"\033[7m > {option} \033[0m")
            else:
                print(f"   {option}")

        print(f"\nUse ↑↓ arrows to navigate, Enter to select, Esc to cancel")
        print(f"Default: {self.options[self.default_index]}")

    def _get_key(self) -> str:
        """Get a single key press."""
        key = sys.stdin.read(1)

        if ord(key) == 27:  # ESC sequence
            key += sys.stdin.read(2)
            if key == '\033[A':
                return 'up'
            elif key == '\033[B':
                return 'down'
            else:
                return 'escape'
        elif ord(key) == 13 or ord(key) == 10:  # Enter
            return 'enter'
        else:
            return 'other'


def confirm_command(command: str, explanation: str = "", working_directory: str = "",
                   reasoning: str = "", related_files: List[str] = None) -> str:
    """Show improved command confirmation dialog."""

    # Display command information
    print("\n" + "="*60)
    print("🤖 Agent wants to execute a command:")
    print("="*60)
    print(f"Command: {command}")
    print(f"Directory: {working_directory}")

    if explanation:
        print(f"Purpose: {explanation}")

    if reasoning:
        print(f"Reasoning: {reasoning}")

    if related_files:
        print(f"Related files: {', '.join(related_files)}")

    print("="*60)

    # Create interactive menu
    options = [
        "Yes - Execute the command",
        "No - Cancel execution",
        "Modify - Edit the command",
        "Explain - Show more details"
    ]

    menu = InteractiveMenu(options, default_index=0)  # Default to "Yes"

    try:
        choice = menu.show_menu(
            title="Command Confirmation",
            description="Choose an option:"
        )

        if choice == 0:
            return "yes"
        elif choice == 1:
            return "no"
        elif choice == 2:
            return "modify"
        elif choice == 3:
            return "explain"
        else:
            return "no"  # Cancelled or invalid

    except KeyboardInterrupt:
        print("\n❌ Operation cancelled by user.")
        return "no"


def get_command_modification(original_command: str) -> Optional[str]:
    """Get command modification from user."""
    try:
        print(f"\nOriginal command: {original_command}")
        print("Enter your modified command (or press Enter to cancel):")
        modified = input("Modified command: ").strip()

        if not modified:
            return None

        return modified

    except (EOFError, KeyboardInterrupt):
        return None