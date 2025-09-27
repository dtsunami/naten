
"""Main CLI entry point for da_code tool."""

import argparse
import asyncio
import logging
import os
import sys
import time

import random
from typing import List
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.styles import Style


from .agent import DaCodeAgent
from .config import ConfigManager, setup_logging
from .context import ContextLoader
from .models import CodeSession, da_mongo

logger = logging.getLogger(__name__)



"""ASCII art splash screen for da_code."""



def get_splash_screen() -> str:
    """Get the da_code ASCII splash screen."""

    # Main da_code ASCII art
    ascii_art = r"""
██████╗  █████╗      ██████╗ ██████╗ ██████╗ ███████╗
██╔══██╗██╔══██╗    ██╔════╝██╔═══██╗██╔══██╗██╔════╝
██║  ██║███████║    ██║     ██║   ██║██║  ██║█████╗
██║  ██║██╔══██║    ██║     ██║   ██║██║  ██║██╔══╝
██████╔╝██║  ██║    ╚██████╗╚██████╔╝██████╔╝███████╗
╚═════╝ ╚═╝  ╚═╝     ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝

    🤖 Agentic CLI with LangChain & Azure OpenAI 🚀
    """

    return ascii_art


def get_animated_splash() -> List[str]:
    """Get animated frames for splash screen."""

    frames = [
        # Frame 1
        r"""
██████╗  █████╗      ██████╗ ██████╗ ██████╗ ███████╗
██╔══██╗██╔══██╗    ██╔════╝██╔═══██╗██╔══██╗██╔════╝
██║  ██║███████║    ██║     ██║   ██║██║  ██║█████╗
██║  ██║██╔══██║    ██║     ██║   ██║██║  ██║██╔══╝
██████╔╝██║  ██║    ╚██████╗╚██████╔╝██████╔╝███████╗
╚═════╝ ╚═╝  ╚═╝     ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝

    🤖 Initializing AI Agent...
""",
        # Frame 2
        r"""
██████╗  █████╗      ██████╗ ██████╗ ██████╗ ███████╗
██╔══██╗██╔══██╗    ██╔════╝██╔═══██╗██╔══██╗██╔════╝
██║  ██║███████║    ██║     ██║   ██║██║  ██║█████╗
██║  ██║██╔══██║    ██║     ██║   ██║██║  ██║██╔══╝
██████╔╝██║  ██║    ╚██████╗╚██████╔╝██████╔╝███████╗
╚═════╝ ╚═╝  ╚═╝     ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝

    🧠 Loading LangChain...
""",
        # Frame 3
        r"""
██████╗  █████╗      ██████╗ ██████╗ ██████╗ ███████╗
██╔══██╗██╔══██╗    ██╔════╝██╔═══██╗██╔══██╗██╔════╝
██║  ██║███████║    ██║     ██║   ██║██║  ██║█████╗
██║  ██║██╔══██║    ██║     ██║   ██║██║  ██║██╔══╝
██████╔╝██║  ██║    ╚██████╗╚██████╔╝██████╔╝███████╗
╚═════╝ ╚═╝  ╚═╝     ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝

    ☁️  Connecting to Azure OpenAI...
""",
        # Frame 4
        r"""
██████╗  █████╗      ██████╗ ██████╗ ██████╗ ███████╗
██╔══██╗██╔══██╗    ██╔════╝██╔═══██╗██╔══██╗██╔════╝
██║  ██║███████║    ██║     ██║   ██║██║  ██║█████╗
██║  ██║██╔══██║    ██║     ██║   ██║██║  ██║██╔══╝
██████╔╝██║  ██║    ╚██████╗╚██████╔╝██████╔╝███████╗
╚═════╝ ╚═╝  ╚═╝     ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝

    🔧 Loading MCP Servers...
""",
        # Final frame
        r"""
██████╗  █████╗      ██████╗ ██████╗ ██████╗ ███████╗
██╔══██╗██╔══██╗    ██╔════╝██╔═══██╗██╔══██╗██╔════╝
██║  ██║███████║    ██║     ██║   ██║██║  ██║█████╗
██║  ██║██╔══██║    ██║     ██║   ██║██║  ██║██╔══╝
██████╔╝██║  ██║    ╚██████╗╚██████╔╝██████╔╝███████╗
╚═════╝ ╚═╝  ╚═╝     ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝

    🚀 Ready! Your AI coding assistant is online.
"""
    ]

    return frames


def get_random_taglines() -> List[str]:
    """Get random taglines for variety."""
    return [
        "🤖 Agentic CLI with LangChain & Azure OpenAI 🚀",
        "🧠 AI-Powered Command Line Assistant 🔧",
        "⚡ Smart Automation with Human Oversight 🛡️",
        "🎯 Precision Coding with AI Intelligence 💡",
        "🔬 Advanced AI Tooling for Developers 🚀",
        "🌟 Next-Gen CLI Experience 🤖",
        "⚙️  Intelligent Command Execution 🎪",
        "🎨 Where AI Meets Development Workflow 🔥"
    ]


def get_mini_splash() -> str:
    """Get a smaller splash for quick starts."""
    return r"""
██████╗  █████╗ ██████╗
██╔══██╗██╔══██╗██╔════╝
██║  ██║███████║██║     
██║  ██║██╔══██║██║     
██████╔╝██║  ██║╚██████╗
╚═════╝ ╚═╝  ╚═╝ ╚═════╝
🤖 Your AI Coding Assistant 🚀
"""


def get_status_splash() -> str:
    """Get splash screen for status/setup commands."""
    return r"""
    ╔═════════════════════════════════╗
    ║     ██████╗  █████╗ ██████╗     ║
    ║     ██╔══██╗██╔══██╗██╔════╝    ║
    ║     ██║  ██║███████║██║         ║
    ║     ██║  ██║██╔══██║██║         ║
    ║     ██████╔╝██║  ██╚██████╗     ║
    ║     ╚═════╝ ╚═╝  ╚═╝╚═════╝     ║
    ╚═════════════════════════════════╝
    """


def print_with_colors(text: str, color_code: str = "94") -> None:
    """Print text with ANSI colors."""
    print(f"\033[{color_code}m{text}\033[0m")


def print_gradient_splash(text: str) -> None:
    """Print splash with gradient effect."""
    lines = text.split('\n')
    # True blue gradient: dark blue -> bright blue -> cyan
    colors = ["34", "94", "94", "96", "96", "36", "36", "96"]

    for i, line in enumerate(lines):
        color = colors[i % len(colors)]
        print(f"\033[{color}m{line}\033[0m")


def print_rainbow_splash(text: str) -> None:
    """Print splash with rainbow colors."""
    lines = text.split('\n')
    rainbow_colors = ["91", "93", "92", "96", "94", "95"]

    for i, line in enumerate(lines):
        if line.strip():  # Only color non-empty lines
            color = rainbow_colors[i % len(rainbow_colors)]
            print(f"\033[{color}m{line}\033[0m")
        else:
            print(line)


def show_splash(style: str = "default", mini: bool = False) -> None:
    """Show splash screen with specified style."""

    if mini:
        splash = get_mini_splash()
    else:
        splash = get_splash_screen()
        # Add random tagline
        taglines = get_random_taglines()
        random_tagline = random.choice(taglines)
        splash = splash.replace("🤖 Agentic CLI with LangChain & Azure OpenAI 🚀", random_tagline)

    # Apply styling
    if style == "gradient":
        print_gradient_splash(splash)
    elif style == "rainbow":
        print_rainbow_splash(splash)
    elif style == "blue":
        print_with_colors(splash, "94")
    elif style == "cyan":
        print_with_colors(splash, "96")
    elif style == "green":
        print_with_colors(splash, "92")
    elif style == "yellow":
        print_with_colors(splash, "93")
    elif style == "purple":
        print_with_colors(splash, "95")
    else:
        # Default - no colors
        print(splash)


def show_status_splash() -> None:
    """Show splash for status/configuration commands."""
    print_with_colors(get_status_splash(), "96")


#---------------------------------------------------------------
# Setup
#---------------------------------------------------------------

default_timeout = 300
config_manager = ConfigManager()
context_loader = ContextLoader()

"""Initialize session, agent, and monitoring."""
try:
    # Validate configuration
    if not config_manager.validate_config():
        print("❌ Configuration validation failed!")
        print("Run 'da_code --setup' to create configuration files.")
        exit()

    # Create agent configuration
    agent_config = config_manager.create_agent_config()

    # Load project context
    project_context = context_loader.load_project_context()

    # Load MCP servers
    mcp_servers = context_loader.load_mcp_servers()

    # Determine working directory
    working_dir = os.getcwd()
    if hasattr(sys.modules['__main__'], 'args') and getattr(sys.modules['__main__'].args, 'working_dir', None):
        working_dir = sys.modules['__main__'].args.working_dir

    # Create session
    code_session = CodeSession(
        working_directory=working_dir,
        project_context=project_context,
        mcp_servers=mcp_servers,
        agent_model=agent_config.deployment_name,
        agent_temperature=agent_config.temperature
    )

    # Create agent
    agent = DaCodeAgent(agent_config, code_session)

    # Record session start time
    session_start_time = time.time()

    logger.info("code_session initialized successfully")
            
except Exception as e:
    logger.error(f"CodeSession initialization failed: {e}")
    print(f"❌ Failed to initialize CodeSession: {e}")
    exit()

#DaCodeAgent:
#    """Main LangChain agent for da_code CLI tool."""#
#
#    def __init__(self, config: AgentConfig, session: CodeSession):



def setup_configuration() -> int:
    """Setup configuration files."""
    show_status_splash()
    print("🔧 Setting up da_code configuration...")

    try:
        # Create sample environment file
        config_manager.create_sample_env()

        # Create sample DA files if they don't exist
        if not Path('DA.md').exists():
            context_loader.create_sample_da_md()

        if not Path('DA.json').exists():
            context_loader.create_sample_da_json()

        print("\n✅ Setup complete!")
        print("\nNext steps:")
        print("1. Edit .env.da_code with your Azure OpenAI credentials")
        print("2. Edit DA.md with your project information")
        print("3. Edit DA.json with your MCP server configuration")
        print("4. Run 'da_code status' to verify configuration")
        print("5. Run 'da_code' to start interactive session")

        return 0

    except Exception as e:
        print(f"❌ Setup failed: {e}")
        return 1



def show_status() -> int:
    """Show configuration and system status."""
    show_status_splash()
    try:
        config_manager.print_config_status()

        # Check project context
        print("\n=== Project Context ===")
        project_context = context_loader.load_project_context()
        if project_context:
            print(f"✓ DA.md loaded: {project_context.project_name or 'Unnamed project'}")
        else:
            print("✗ DA.md not found or empty")

        # Check MCP servers
        mcp_servers = context_loader.load_mcp_servers()
        print(f"\n=== MCP Servers ===")
        if mcp_servers:
            print(f"✓ Found {len(mcp_servers)} MCP servers:")
            for server in mcp_servers:
                print(f"  - {server.name}: {server.url}")
        else:
            print("✗ No MCP servers configured")

        return 0

    except Exception as e:
        print(f"❌ Status check failed: {e}")
        return 1



# Define available commands for autocompletion
commands = ['help', 'exit', 'setup', 'status']
command_completer = WordCompleter(commands, ignore_case=True)

# Define style
style = Style.from_dict({
    'prompt': 'ansicyan bold'
})

# Create a PromptSession
session = PromptSession(style=style)

def main():
    show_splash("gradient")
    print("Ready! Type 'help' for commands.")
    while True:
        try:
            user_input = session.prompt('> ', completer=command_completer)
            if user_input.lower() == 'exit':
                print("Goodbye!")
                break
            elif user_input.lower() == 'help':
                print("Available commands:")
                for cmd in commands:
                    print(f"  - {cmd}")
            elif user_input.lower() == 'setup':
                setup_configuration()
            elif user_input.lower() == 'status':
                show_status()
            elif user_input.strip() == '':
                continue
            else:
                response = agent.chat(message=f"{user_input}")
                print(response)
        except KeyboardInterrupt:
            continue
        except EOFError:
            break

if __name__ == '__main__':
    main()
