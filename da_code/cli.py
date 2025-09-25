"""Main CLI entry point for da_code tool."""

import argparse
import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .agent import DaCodeAgent
from .config import ConfigManager, setup_logging
from .context import ContextLoader
from .models import CodeSession, da_mongo
from .splash import show_splash, show_status_splash

logger = logging.getLogger(__name__)


class DaCodeCLI:
    """Main CLI application for da_code."""

    def __init__(self):
        """Initialize CLI application."""
        self.config_manager = ConfigManager()
        self.context_loader = ContextLoader()
        self.session: Optional[CodeSession] = None
        self.agent: Optional[DaCodeAgent] = None
        self.session_start_time = None

    async def run(self) -> int:
        """Run the CLI application."""
        parser = self.create_argument_parser()
        args = parser.parse_args()

        # Setup logging
        log_level = args.log_level or os.getenv('LOG_LEVEL', 'INFO')
        setup_logging(log_level)

        try:
            # Handle different commands
            if args.command == 'setup':
                return self.setup_configuration()
            elif args.command == 'status':
                return self.show_status()
            elif args.command == 'interactive':
                return await self.run_interactive_session()
            else:
                # Default to interactive session
                return await self.run_interactive_session()

        except KeyboardInterrupt:
            print("\n👋 Goodbye!")
            return 0
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            print(f"❌ Error: {e}")
            return 1

    def create_argument_parser(self) -> argparse.ArgumentParser:
        """Create argument parser for CLI."""
        parser = argparse.ArgumentParser(
            description="da_code - Agentic CLI tool with LangChain and Azure OpenAI",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  da_code                    Start interactive session
  da_code --setup            Create sample configuration files
  da_code --status           Show configuration status
  da_code --log-level DEBUG  Start with debug logging
            """
        )

        subparsers = parser.add_subparsers(dest='command', help='Available commands')

        # Interactive session (default)
        interactive_parser = subparsers.add_parser('interactive', help='Start interactive session')
        interactive_parser.add_argument('--working-dir', '-w', help='Working directory for session')

        # Setup command
        setup_parser = subparsers.add_parser('setup', help='Create sample configuration files')

        # Status command
        status_parser = subparsers.add_parser('status', help='Show configuration status')

        # Global options
        parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], help='Set logging level')
        parser.add_argument('--working-dir', '-w', help='Working directory for session')

        return parser

    def setup_configuration(self) -> int:
        """Setup configuration files."""
        show_status_splash()
        print("🔧 Setting up da_code configuration...")

        try:
            # Create sample environment file
            self.config_manager.create_sample_env()

            # Create sample DA files if they don't exist
            if not Path('DA.md').exists():
                self.context_loader.create_sample_da_md()

            if not Path('DA.json').exists():
                self.context_loader.create_sample_da_json()

            print("\n✅ Setup complete!")
            print("\nNext steps:")
            print("1. Edit .env.da_code with your Azure OpenAI credentials")
            print("2. Edit DA.md with your project information")
            print("3. Edit DA.json with your MCP server configuration")
            print("4. Run 'da_code --status' to verify configuration")
            print("5. Run 'da_code' to start interactive session")

            return 0

        except Exception as e:
            print(f"❌ Setup failed: {e}")
            return 1

    def show_status(self) -> int:
        """Show configuration and system status."""
        show_status_splash()
        try:
            self.config_manager.print_config_status()

            # Check project context
            print("\n=== Project Context ===")
            project_context = self.context_loader.load_project_context()
            if project_context:
                print(f"✓ DA.md loaded: {project_context.project_name or 'Unnamed project'}")
            else:
                print("✗ DA.md not found or empty")

            # Check MCP servers
            mcp_servers = self.context_loader.load_mcp_servers()
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

    async def run_interactive_session(self) -> int:
        """Run interactive chat session with agent."""
        # Show gradient splash
        show_splash("gradient")

        try:
            # Initialize session
            if not await self.initialize_session():
                return 1

            # Show welcome message
            self.show_welcome_message()

            # Start interactive loop
            await self.interactive_loop()

            return 0

        except Exception as e:
            logger.error(f"Interactive session error: {e}")
            print(f"❌ Session failed: {e}")
            return 1

        finally:
            await self.cleanup_session()

    async def initialize_session(self) -> bool:
        """Initialize session, agent, and monitoring."""
        try:
            # Validate configuration
            if not self.config_manager.validate_config():
                print("❌ Configuration validation failed!")
                print("Run 'da_code --setup' to create configuration files.")
                return False

            # Create agent configuration
            agent_config = self.config_manager.create_agent_config()

            # Load project context
            project_context = self.context_loader.load_project_context()

            # Load MCP servers
            mcp_servers = self.context_loader.load_mcp_servers()

            # Determine working directory
            working_dir = os.getcwd()
            if hasattr(sys.modules['__main__'], 'args') and getattr(sys.modules['__main__'].args, 'working_dir', None):
                working_dir = sys.modules['__main__'].args.working_dir

            # Create session
            self.session = CodeSession(
                working_directory=working_dir,
                project_context=project_context,
                mcp_servers=mcp_servers,
                agent_model=agent_config.deployment_name,
                agent_temperature=agent_config.temperature
            )

            # Create agent
            self.agent = DaCodeAgent(agent_config, self.session)

            # Record session start time
            self.session_start_time = time.time()

            logger.info("Session initialized successfully")
            return True

        except Exception as e:
            logger.error(f"Session initialization failed: {e}")
            print(f"❌ Failed to initialize session: {e}")
            return False

    def show_welcome_message(self) -> None:
        """Show minimal welcome message."""
        # Get project name from current directory
        project_name = os.path.basename(os.getcwd())
        print(f"📁 {project_name} • {self.session.agent_model}")

        # Show brief MongoDB warning if not connected
        if not da_mongo.mongo_enabled:
            print("⚠️  MongoDB not connected - using local file tracking")

        print("Type 'help' for commands")

    async def interactive_loop(self) -> None:
        """Main interactive loop for chatting with agent."""
        print("\n🚀 Ready! How can I help you?")

        while True:
            try:
                # Get user input
                user_input = input("\n👤 You: ").strip()

                if not user_input:
                    continue

                # Handle special commands
                if user_input.lower() in ['exit', 'quit', 'q']:
                    print("👋 Ending session...")
                    break
                elif user_input.lower() in ['help', 'h']:
                    self.show_help()
                    continue
                elif user_input.lower() in ['status', 'info']:
                    self.show_session_info()
                    continue
                elif user_input.lower() in ['clear', 'cls']:
                    self.agent.clear_memory()
                    print("🧹 Memory cleared!")
                    continue

                # Chat with agent using simple async UI
                from .async_ui_simple import simple_async_ui
                response = await simple_async_ui.chat_with_agent(
                    self.agent.chat,
                    user_input
                )

                if response:
                    print(response)


            except (EOFError, KeyboardInterrupt):
                print("\n👋 Session interrupted")
                break
            except Exception as e:
                logger.error(f"Error in interactive loop: {e}")
                print(f"\n❌ Error: {e}")
                print("Type 'exit' to quit or continue chatting...")

    def show_help(self) -> None:
        """Show help information."""
        print("""
🆘 da_code Help

SPECIAL COMMANDS:
  help, h      - Show this help message
  status, info - Show current session information
  clear, cls   - Clear conversation memory
  exit, quit, q - End session

USAGE EXAMPLES:
  "What files are in the current directory?"
  "Install the requests package"
  "Create a Python script that does X"
  "Read the contents of config.py"
  "Run the tests for this project"

FEATURES:
  ✅ All commands require your confirmation before execution
  ✅ Full conversation memory within session
  ✅ Access to MCP servers for specialized operations
  ✅ Project context awareness from DA.md
  ✅ Session tracking and monitoring

SAFETY:
  🔒 You will be prompted before any command execution
  🔒 Dangerous commands are highlighted with warnings
  🔒 All operations are logged for review
        """)

    def show_session_info(self) -> None:
        """Show current session information."""
        if not self.agent:
            print("❌ No active session")
            return

        info = self.agent.get_session_info()
        session_duration = time.time() - self.session_start_time if self.session_start_time else 0

        print(f"""
📊 Current Session Info:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Session ID: {info['session_id']}
Duration: {session_duration:.1f} seconds
Commands: {info['total_commands']} total, {info['successful_commands']} successful, {info['failed_commands']} failed
Working Dir: {info['working_directory']}
Agent Model: {info['agent_model']}
MCP Servers: {info['mcp_servers']} available
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        """)

        # Show MongoDB tracking status
        mongo_status = da_mongo.mongo_enabled
        print(f"💾 Session Tracking: {'MongoDB' if mongo_status else 'Local Files'}")

    async def cleanup_session(self) -> None:
        """Cleanup session and save final state."""
        try:
            if self.session and self.session_start_time:
                session_duration = time.time() - self.session_start_time

                # Save final session state to MongoDB
                await da_mongo.save_session(self.session)

                print(f"\n📊 Duration: {session_duration:.1f}s • {self.session.total_commands} commands • {self.session.total_llm_calls} LLM calls")
                print(f"  Tool Calls: {self.session.total_tool_calls}")
                if self.session.total_commands > 0:
                    print(f"  Success rate: {(self.session.successful_commands / self.session.total_commands) * 100:.1f}%")

        except Exception as e:
            logger.error(f"Cleanup error: {e}")


async def main() -> int:
    """Main entry point for da_code CLI."""
    cli = DaCodeCLI()
    return await cli.run()


def cli_entry_point():
    """Entry point for setuptools console_scripts."""
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
        sys.exit(0)


if __name__ == "__main__":
    cli_entry_point()