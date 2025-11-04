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
# AI Nudge Phrases (Prompt Engineering Shortcuts)
#====================================================================================================

# da_code generated nudge phrases (feel free to edit/extend)
NUDGE_PHRASES = '''check your work and implement step by step
verify the changes after editing files
test all new features and changes thoroughly before finalizing
always use best ci/cd and development practices when updaing code'''.split('\n')

#====================================================================================================
# File/Directory Utilities
#====================================================================================================

from .file_utils import get_file_emoji


#====================================================================================================
# Directory Context
#====================================================================================================

class DirectoryContext:
    """Provides intelligent directory context for the agent with activity-based previews."""

    def __init__(self, working_dir: str, daignore=None):
        """Initialize directory context.

        Args:
            working_dir: Working directory path
            daignore: DaIgnore instance for filtering files (optional)
        """
        self.working_dir = Path(working_dir)
        self.daignore = daignore
        self._cache_timestamp = None
        self._cached_listing = None

    def _should_ignore(self, path: Path) -> bool:
        """Check if path should be ignored using DaIgnore or fallback patterns."""
        # Use daignore if available
        if self.daignore:
            relative_path = str(path.relative_to(self.working_dir))
            return self.daignore.is_ignored(relative_path)

        # Fallback to hard-coded patterns if no daignore
        ignored = {'.git', '__pycache__', '.vscode', 'node_modules', '.da'}
        return path.name in ignored or path.name.startswith('.')

    def get_directory_listing(self) -> Tuple[str, float]:
        """Get integrated directory listing with subdirectory previews and time deltas."""
        try:
            listing = []
            current_time = time.time()

            # Get activity scores for directories
            directory_scores = {}
            for item in self.working_dir.iterdir():
                # Skip ignored files/directories
                if self._should_ignore(item):
                    continue

                if item.is_dir():
                    score = self._calculate_activity_score(item, current_time)
                    directory_scores[item.name] = score

            # Process all items with integrated subdirectory previews
            for item in sorted(self.working_dir.iterdir()):
                # Skip ignored files/directories
                if self._should_ignore(item):
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
                # Skip ignored files/directories
                if self._should_ignore(item):
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
                # Skip ignored files
                if self._should_ignore(file_path):
                    continue

                if file_path.is_file():
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
                # Skip ignored files
                if self._should_ignore(item):
                    continue

                if item.is_file():
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

    def _extract_instructions(self, content: str) -> List[str]:
        """Extract instructions from markdown content as a list.

        Format: ## Text explaining the instruction to agent
                  <- optional detail>

        Each ## in .md becomes one instruction with detail combined.

        Ignored sections:
        - Everything after '---' (horizontal rule)
        - HTML comments <!-- ... -->
        """
        lines = content.split('\n')
        instructions = []
        current_instruction = None
        current_detail = []
        in_description = True  # Skip lines until after project description
        in_comment = False  # Track HTML comment blocks
        max_detail_length = 200  # Character limit for detail

        for line in lines:
            stripped = line.strip()

            # Check for horizontal rule - stop processing
            if stripped.startswith('---'):
                # Save current instruction before stopping
                if current_instruction:
                    detail = ' '.join(current_detail).strip()
                    if len(detail) > max_detail_length:
                        detail = detail[:max_detail_length].rsplit(' ', 1)[0] + '...'
                    if detail:
                        instructions.append(f"{current_instruction}: {detail}")
                    else:
                        instructions.append(current_instruction)
                break  # Stop processing after ---

            # Handle HTML comments
            if '<!--' in stripped:
                in_comment = True
            if in_comment:
                if '-->' in stripped:
                    in_comment = False
                continue  # Skip comment lines

            # Skip H1 (project title)
            if stripped.startswith('# '):
                in_description = True
                continue

            # Check if this is a ## heading (instruction)
            if stripped.startswith('## '):
                # Now we're past the description
                in_description = False

                # Save previous instruction if exists
                if current_instruction:
                    detail = ' '.join(current_detail).strip()
                    # Truncate if too long
                    if len(detail) > max_detail_length:
                        detail = detail[:max_detail_length].rsplit(' ', 1)[0] + '...'

                    if detail:
                        instructions.append(f"{current_instruction}: {detail}")
                    else:
                        instructions.append(current_instruction)

                # Start new instruction (remove '## ')
                current_instruction = stripped[3:].strip()
                current_detail = []
                continue

            # If we're in description section, skip
            if in_description:
                continue

            # If we're collecting an instruction and hit another heading, stop
            if current_instruction and stripped.startswith('#'):
                # Save current instruction
                detail = ' '.join(current_detail).strip()
                if len(detail) > max_detail_length:
                    detail = detail[:max_detail_length].rsplit(' ', 1)[0] + '...'

                if detail:
                    instructions.append(f"{current_instruction}: {detail}")
                else:
                    instructions.append(current_instruction)
                current_instruction = None
                current_detail = []
                continue

            # Collect detail lines for current instruction
            if current_instruction and stripped:
                current_detail.append(stripped)

        # Save last instruction if exists
        if current_instruction:
            detail = ' '.join(current_detail).strip()
            if len(detail) > max_detail_length:
                detail = detail[:max_detail_length].rsplit(' ', 1)[0] + '...'

            if detail:
                instructions.append(f"{current_instruction}: {detail}")
            else:
                instructions.append(current_instruction)

        return instructions

    def create_sample_da_json(self) -> None:
        """Create a sample DA.json file with common MCP servers."""
        sample_data = {
            "mcp_servers": [
                {
                "name": "agno_docs",
                "url": "https://docs.agno.com/mcp",
                "description": "Agno Agent docs"
                },
                {
                "name": "fastmcp_docs",
                "url": "https://gofastmcp.com/mcp",
                "description": "FastMCP documentation server"
                }
            ],
            "default_working_directory": ".",
            "agent_settings": {
                "model": "gpt-5-chat",
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

## Use consistent code style
Follow the existing patterns in the codebase for naming and formatting

## Write tests for new features
All new functionality should include unit tests with good coverage

## Document important decisions
Add comments explaining why, not just what the code does

---

**Note:** Each `## heading` above becomes one instruction for the AI agent.
You can add optional detail below each heading (limited to ~200 chars).
The agent receives these as project-specific instructions along with default tool usage instructions.

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
# Token and Context Tracking
#====================================================================================================
#
# NOTE: ContextTracker and StreamingTokenTracker have been removed (stale code).
#
# Use the new telemetry system instead:
#   - context_telemetry.py: ModelInterceptor, ModelStatsTracker (ACTUAL token usage from LLM)
#   - token_estimator.py: TokenEstimator (estimates for pre-call planning)
#
# The old trackers used rough estimates. The new system captures real usage from model calls.
#====================================================================================================