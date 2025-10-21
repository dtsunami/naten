"""Session management functions for da_code CLI."""

import os
import logging
from pathlib import Path

from .context import ContextLoader
from .models import CodeSession
from .daignore import DaIgnore, create_example_daignore

logger = logging.getLogger(__name__)


def create_session(context_ldr: ContextLoader, session_id: str = None):
    """Create a new code session.

    Args:
        context_ldr: Context loader for project configuration
        session_id: Optional ObjectId string to restore/create a specific session
    """
    if not os.path.exists(".da"):
        os.makedirs(".da")

    # Load project context
    project_context = context_ldr.load_project_context()

    # Load MCP servers
    mcp_servers = context_ldr.load_mcp_servers()

    # Determine working directory
    working_dir = os.getcwd()

    # Initialize daignore for file filtering
    from bson import ObjectId
    daignore = DaIgnore(project_root=working_dir)

    # Create session with optional id for restart (pass as _id to use MongoDB ObjectId)
    if session_id:
        # Validate and create with specific ObjectId
        if ObjectId.is_valid(session_id):
            code_session = CodeSession(
                _id=session_id,  # This will set the id field
                working_directory=working_dir,
                project_context=project_context,
                mcp_servers=mcp_servers,
                daignore=daignore,
            )
        else:
            raise ValueError(f"Invalid session ID format: {session_id}")
    else:
        code_session = CodeSession(
            working_directory=working_dir,
            project_context=project_context,
            mcp_servers=mcp_servers,
            daignore=daignore,
        )
    return code_session


def create_example_configuration(config_mgr, context_ldr: ContextLoader) -> int:
    """Setup configuration files."""
    from .ux import show_status_splash

    show_status_splash()
    print("🔧 Setting up da_code configuration...")

    try:
        # Create sample environment file
        config_mgr.create_sample_env()

        # Create sample context files if they don't exist
        if not Path('AGENTS.md').exists():
            context_ldr.create_sample_agents_md()

        if not Path('DA.json').exists():
            context_ldr.create_sample_da_json()

        # Create .daignore if it doesn't exist
        if not Path('.daignore').exists():
            create_example_daignore()
            print("✓ Created .daignore file")

        print("\n✅ Setup complete!")
        print("\nNext steps:")
        print("1. Edit .env with your Azure OpenAI credentials")
        print("2. Edit AGENTS.md with your project information")
        print("3. Edit DA.json with your MCP server configuration")
        print("4. Edit .daignore to control agent file access")
        print("5. Run 'da_code status' to verify configuration")
        print("6. Run 'da_code' to start interactive session")

        return 0

    except Exception as e:
        print(f"❌ Setup failed: {e}")
        return 1


def show_status(config_mgr, context_ldr: ContextLoader) -> int:
    """Show configuration and system status."""
    try:
        config_mgr.print_config_status()

        # Check project context
        print("\n=== Project Context ===")
        project_context = context_ldr.load_project_context()
        if project_context:
            print(f"✓ AGENTS.md loaded: {project_context.project_name or 'Unnamed project'}")
        else:
            print("✗ AGENTS.md not found or empty")

        # Check MCP servers
        mcp_servers = context_ldr.load_mcp_servers()
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