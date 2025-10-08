"""Context loading for AGENTS.md and DA.json files."""

import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .models import MCPServerInfo, ProjectContext

logger = logging.getLogger(__name__)


#====================================================================================================
# File/Directory Utilities
#====================================================================================================

def get_file_emoji(filename: str) -> str:
    """Get emoji for file type."""
    name_lower = filename.lower()
    if name_lower.endswith(('.py', '.pyw')):
        return "🐍"
    elif name_lower.endswith(('.js', '.jsx', '.ts', '.tsx')):
        return "🟨"
    elif name_lower.endswith(('.md', '.markdown')):
        return "📖"
    elif name_lower.endswith(('.json', '.yaml', '.yml', '.toml')):
        return "⚙️"
    elif name_lower.endswith(('.env', '.gitignore', '.dockerignore')):
        return "🔧"
    elif name_lower.endswith(('.txt', '.log')):
        return "📝"
    elif name_lower.endswith(('.sh', '.bash', '.zsh')):
        return "🔸"
    elif name_lower.endswith(('.html', '.htm', '.css')):
        return "🌐"
    elif name_lower.endswith(('.sql', '.db', '.sqlite')):
        return "🗄️"
    elif name_lower.endswith(('.jpg', '.jpeg', '.png', '.gif', '.svg')):
        return "🖼️"
    else:
        return "📄"


#====================================================================================================
# Directory Context
#====================================================================================================

class DirectoryContext:
    """Provides intelligent directory context for the agent with activity-based previews."""

    def __init__(self, working_dir: str):
        """Initialize directory context."""
        self.working_dir = Path(working_dir)
        self._cache_timestamp = None
        self._cached_listing = None

    def get_directory_listing(self) -> Tuple[str, float]:
        """Get integrated directory listing with subdirectory previews and time deltas."""
        try:
            listing = []
            current_time = time.time()

            # Get files/dirs, skip ignored patterns
            ignored = {'.git', '__pycache__', '.vscode', 'node_modules'}

            # Get activity scores for directories
            directory_scores = {}
            for item in self.working_dir.iterdir():
                if (item.is_dir() and
                    not item.name.startswith('.') and
                    item.name not in ignored):
                    score = self._calculate_activity_score(item, current_time)
                    directory_scores[item.name] = score

            # Process all items with integrated subdirectory previews
            for item in sorted(self.working_dir.iterdir()):
                if item.name.startswith('.') and item.name not in {'.env', '.gitignore'}:
                    continue
                if item.name in ignored:
                    continue

                try:
                    if item.is_dir():
                        # Directory with activity score and time delta
                        activity_score = directory_scores.get(item.name, float('inf'))
                        time_delta = self._format_time_delta(activity_score)

                        listing.append(f"📁 {item.name}/ ({time_delta})")

                        # Add subdirectory preview if it's one of the active directories
                        if activity_score < 7 * 86400:  # Only show preview for dirs active within 7 days
                            preview = self._get_subdirectory_preview(item.name, max_files=3)
                            if preview:
                                listing.append(preview)
                    else:
                        # File with size and modification time
                        stat = item.stat()
                        mod_delta = current_time - stat.st_mtime
                        time_str = self._format_time_delta(mod_delta)

                        size = stat.st_size
                        if size < 1024:
                            size_str = f"{size}B"
                        elif size < 1024*1024:
                            size_str = f"{size//1024}KB"
                        else:
                            size_str = f"{size//(1024*1024)}MB"

                        emoji = get_file_emoji(item.name)
                        listing.append(f"{emoji} {item.name} ({size_str}, {time_str})")

                except (OSError, PermissionError):
                    continue

            if not listing:
                listing.append("(empty directory)")

            result = "\n".join(listing)
            timestamp = time.time()

            # Update cache
            self._cached_listing = result
            self._cache_timestamp = timestamp

            return result, timestamp

        except Exception as e:
            logger.error(f"Failed to get directory listing: {e}")
            return f"📁 {self.working_dir} (unable to read)", time.time()

    def check_changes(self, cache_timestamp: float) -> Optional[str]:
        """Check if directory changed since timestamp. Returns update message if changed."""
        if not cache_timestamp:
            return None

        try:
            # Quick check: any file newer than cache?
            for item in self.working_dir.iterdir():
                if item.name.startswith('.') and item.name not in {'.env', '.gitignore'}:
                    continue
                if item.name in {'.git', '__pycache__', '.vscode', 'node_modules'}:
                    continue

                try:
                    if item.stat().st_mtime > cache_timestamp:
                        new_listing, _ = self.get_directory_listing()
                        return f"📁 Directory updated:\n{new_listing}\n\n"
                except (OSError, PermissionError):
                    continue

            return None

        except Exception as e:
            logger.error(f"Failed to check directory changes: {e}")
            return None

    def _calculate_activity_score(self, dir_path: Path, current_time: float) -> float:
        """Calculate activity score using max(avg_file_activity, directory_activity)."""
        try:
            dir_stat = dir_path.stat()
            directory_update_delta = current_time - dir_stat.st_mtime

            # Get all file update deltas
            file_deltas = []
            for file_path in dir_path.rglob('*'):
                if (file_path.is_file() and
                    not file_path.name.startswith('.') and
                    file_path.name not in {'__pycache__', '.pyc', '.pyo'}):
                    file_delta = current_time - file_path.stat().st_mtime
                    file_deltas.append(file_delta)

            if not file_deltas:
                return directory_update_delta

            avg_file_activity = sum(file_deltas) / len(file_deltas)

            # Scoring formula: max of average file activity vs directory activity
            score = max(avg_file_activity, directory_update_delta)
            return score

        except (OSError, PermissionError):
            return float('inf')  # Inaccessible = lowest priority

    def _get_subdirectory_preview(self, subdir_name: str, max_files: int = 4) -> str:
        """Get preview of subdirectory contents with emoji file types."""
        subdir_path = self.working_dir / subdir_name
        if not subdir_path.exists() or not subdir_path.is_dir():
            return ""

        preview_lines = []
        file_count = 0
        total_files = 0

        try:
            # Get files sorted by size (larger files often more important)
            files = []
            for item in subdir_path.iterdir():
                if item.is_file() and not item.name.startswith('.'):
                    try:
                        size = item.stat().st_size
                        files.append((item.name, size))
                        total_files += 1
                    except (OSError, PermissionError):
                        continue

            # Sort by size descending, then by name
            files.sort(key=lambda x: (-x[1], x[0]))

            # Show top files with emojis
            for filename, size in files[:max_files]:
                if size < 1024:
                    size_str = f"{size}B"
                elif size < 1024*1024:
                    size_str = f"{size//1024}KB"
                else:
                    size_str = f"{size//(1024*1024)}MB"

                emoji = get_file_emoji(filename)
                preview_lines.append(f"  └── {emoji} {filename} ({size_str})")
                file_count += 1

            # Add summary if there are more files
            if total_files > max_files:
                remaining = total_files - max_files
                preview_lines.append(f"  └── ... and {remaining} more files")

        except (OSError, PermissionError):
            preview_lines.append(f"  └── (unable to read {subdir_name})")

        return "\n".join(preview_lines)

    def _format_time_delta(self, seconds: float) -> str:
        """Format time delta in human readable form."""
        if seconds < 60:
            return f"{int(seconds)}s ago"
        elif seconds < 3600:
            return f"{int(seconds/60)}m ago"
        elif seconds < 86400:
            return f"{int(seconds/3600)}h ago"
        else:
            return f"{int(seconds/86400)}d ago"


#====================================================================================================
# Project Context Loader
#====================================================================================================


class ContextLoader:
    """Loads project context from AGENTS.md and MCP server info from DA.json."""

    def __init__(self, project_root: Optional[str] = None):
        """Initialize context loader with project root directory."""
        self.project_root = Path(project_root) if project_root else Path.cwd()
        self.agents_md_path = self.project_root / "AGENTS.md"
        self.da_json_path = self.project_root / "DA.json"

    def load_project_context(self) -> Optional[ProjectContext]:
        """Load project context from AGENTS.md file."""
        try:
            if not self.agents_md_path.exists():
                logger.warning(f"AGENTS.md not found at {self.agents_md_path}")
                return None

            with open(self.agents_md_path, 'r', encoding='utf-8') as f:
                content = f.read()

            if not content.strip():
                logger.warning("AGENTS.md is empty")
                return None

            # Extract project name and description from markdown
            project_name = self._extract_project_name(content)
            description = self._extract_description(content)
            instructions = self._extract_instructions(content)

            context = ProjectContext(
                project_name=project_name,
                description=description,
                instructions=instructions,
                file_content=content
            )

            logger.info(f"Loaded project context from {self.agents_md_path}")
            return context

        except Exception as e:
            logger.error(f"Failed to load AGENTS.md: {e}")
            return None

    def load_mcp_servers(self) -> List[MCPServerInfo]:
        """Load MCP server information from DA.json file and add built-in servers."""
        servers = []

        # Load external MCP servers from DA.json
        try:
            if not self.da_json_path.exists():
                logger.warning(f"DA.json not found at {self.da_json_path}")
                return servers

            with open(self.da_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            mcp_servers = data.get('mcp_servers', [])

            for server_data in mcp_servers:
                try:
                    server = MCPServerInfo(**server_data)
                    servers.append(server)
                except Exception as e:
                    logger.error(f"Invalid MCP server data: {server_data}, error: {e}")
                    continue

            logger.info(f"Loaded {len(servers)} total MCP servers ({len(mcp_servers)} from DA.json + 1 built-in)")
            return servers

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in DA.json: {e}")
            return servers
        except Exception as e:
            logger.error(f"Failed to load DA.json: {e}")
            return servers

    def _extract_project_name(self, content: str) -> Optional[str]:
        """Extract project name from markdown content."""
        lines = content.split('\n')

        for line in lines:
            line = line.strip()
            # Look for first H1 heading
            if line.startswith('# '):
                return line[2:].strip()

        return None

    def _extract_description(self, content: str) -> Optional[str]:
        """Extract project description from markdown content."""
        lines = content.split('\n')
        description_lines = []
        found_title = False

        for line in lines:
            line = line.strip()

            # Skip empty lines before finding title
            if not found_title and not line:
                continue

            # Found the title (H1)
            if line.startswith('# '):
                found_title = True
                continue

            # Stop at next heading or section
            if found_title and (line.startswith('#') or line.startswith('##')):
                break

            # Collect description lines
            if found_title:
                description_lines.append(line)

        description = '\n'.join(description_lines).strip()
        return description if description else None

    def _extract_instructions(self, content: str) -> Optional[str]:
        """Extract instructions from markdown content."""
        # Look for sections with 'instruction' in the heading
        lines = content.split('\n')
        instructions_lines = []
        in_instructions = False

        for line in lines:
            line_lower = line.lower().strip()

            # Check if this is an instructions heading
            if line_lower.startswith('#') and 'instruction' in line_lower:
                in_instructions = True
                continue

            # Stop at next heading
            if in_instructions and line.strip().startswith('#'):
                break

            # Collect instruction lines
            if in_instructions:
                instructions_lines.append(line)

        instructions = '\n'.join(instructions_lines).strip()
        return instructions if instructions else None

    def create_sample_da_json(self) -> None:
        """Create a sample DA.json file with common MCP servers."""
        sample_data = {
            "mcp_servers": [
                {
                    "name": "search",
                    "url": "http://localhost:8080/search",
                    "port": 8003,
                    "description": "Web search MCP server",
                    "tools": ["web_search", "extract_content"]
                }
            ],
            "default_working_directory": ".",
            "agent_settings": {
                "model": "gpt-40",
                "temperature": 0.7,
                "max_tokens": None,
                "require_confirmation": True
            }
        }

        try:
            with open(self.da_json_path, 'w', encoding='utf-8') as f:
                json.dump(sample_data, f, indent=2)

            logger.info(f"Created sample DA.json at {self.da_json_path}")
        except Exception as e:
            logger.error(f"Failed to create sample DA.json: {e}")

    def create_sample_agents_md(self) -> None:
        """Create a sample AGENTS.md file."""
        sample_content = """# Project Name

Brief description of your project goes here.

## Agent Instructions

Instructions for the da_code AI agent on how to work with this project:

### Development Workflow
- Preferred coding patterns and conventions
- Testing approach (unit tests, integration tests, etc.)
- Git workflow and commit message style
- Code review process

### Project Structure
- Key directories and their purposes
- Important configuration files
- Entry points and main modules
- Documentation locations

### Tools and Technologies
- Programming languages and frameworks
- Build tools and package managers
- Development dependencies
- Deployment tools

## Coding Standards

### Style Guidelines
- Code formatting preferences
- Naming conventions
- Comment and documentation style
- Error handling patterns

### Best Practices
- Performance considerations
- Security guidelines
- Accessibility requirements
- Browser/platform compatibility

## Agent Behavior

### Preferred Actions
- Always run tests after code changes
- Use specific linting/formatting tools
- Follow specific commit patterns
- Ask for confirmation before major changes

### Project Context
- Domain-specific knowledge the agent should know
- Business logic and requirements
- Integration points with external systems
- Known issues or technical debt

## Important Files

- `src/main.py` - Application entry point
- `tests/` - Test suite location
- `requirements.txt` - Python dependencies
- `README.md` - Project documentation
- `.env.example` - Environment configuration template
"""

        try:
            with open(self.agents_md_path, 'w', encoding='utf-8') as f:
                f.write(sample_content)

            logger.info(f"Created sample AGENTS.md at {self.agents_md_path}")
            print(f"\n📝 Created sample AGENTS.md file at {self.agents_md_path}")
            print("💡 Edit this file to provide context and instructions for the AI agent")
        except Exception as e:
            logger.error(f"Failed to create sample AGENTS.md: {e}")


#====================================================================================================
# MCP Server Health Check and Tool Discovery, TODO: should these be deleted?
#====================================================================================================


async def check_mcp_server_health(server: MCPServerInfo) -> bool:
    """Check if an MCP server is healthy and responsive."""
    try:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            health_url = f"{server.url.rstrip('/')}/health"
            async with session.get(health_url, timeout=5) as response:
                return response.status == 200

    except Exception as e:
        logger.error(f"Health check failed for {server.name}: {e}")
        return False


async def discover_mcp_tools(server: MCPServerInfo) -> List[str]:
    """Discover available tools from an MCP server."""
    try:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            tools_url = f"{server.url.rstrip('/')}/mcp"
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list"
            }

            async with session.post(tools_url, json=payload, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    result = data.get('result', {})
                    tools = result.get('tools', [])
                    return [tool.get('name', '') for tool in tools if tool.get('name')]

    except Exception as e:
        logger.error(f"Tool discovery failed for {server.name}: {e}")

    return []