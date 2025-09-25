"""Mock MCP server for todo.md file management following MCP architecture patterns."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional


class TodoTool:
    """MCP Tool definition for todo operations."""

    def __init__(self, name: str, description: str, input_schema: Dict[str, Any]):
        self.name = name
        self.description = description
        self.inputSchema = input_schema


class TodoOperations:
    """Handle todo.md file operations."""

    def __init__(self, working_directory: str = None):
        """Initialize todo operations."""
        self.working_dir = working_directory or os.getcwd()
        self.todo_file = Path(self.working_dir) / "todo.md"

    def get_tools(self) -> List[TodoTool]:
        """Get list of available todo operation tools."""
        tools = [
            TodoTool(
                name="read_todos",
                description="Read current todos from todo.md file",
                input_schema={
                    "type": "object",
                    "properties": {
                        "include_completed": {
                            "type": "boolean",
                            "default": False,
                            "description": "Include completed todos in the response"
                        }
                    },
                    "required": []
                }
            ),
            TodoTool(
                name="add_todo",
                description="Add a new todo item to todo.md",
                input_schema={
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": "The todo task description"
                        },
                        "priority": {
                            "type": "string",
                            "enum": ["low", "medium", "high", "urgent"],
                            "description": "Task priority level"
                        },
                        "context": {
                            "type": "string",
                            "description": "Additional context or details about the task"
                        }
                    },
                    "required": ["task"]
                }
            ),
            TodoTool(
                name="complete_todo",
                description="Mark a todo item as completed",
                input_schema={
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": "Task text to mark as completed (partial match)"
                        },
                        "number": {
                            "type": "integer",
                            "description": "Task number (1-based index) to mark as completed"
                        }
                    },
                    "anyOf": [
                        {"required": ["task"]},
                        {"required": ["number"]}
                    ]
                }
            ),
            TodoTool(
                name="update_todo",
                description="Update an existing todo item",
                input_schema={
                    "type": "object",
                    "properties": {
                        "old_text": {
                            "type": "string",
                            "description": "Current task text to find and update"
                        },
                        "new_text": {
                            "type": "string",
                            "description": "New task text to replace with"
                        },
                        "number": {
                            "type": "integer",
                            "description": "Task number (1-based index) to update"
                        }
                    },
                    "properties": {
                        "new_text": {"type": "string"}
                    },
                    "anyOf": [
                        {"required": ["old_text", "new_text"]},
                        {"required": ["number", "new_text"]}
                    ]
                }
            ),
            TodoTool(
                name="archive_todos",
                description="Archive completed todos and clear the list",
                input_schema={
                    "type": "object",
                    "properties": {
                        "keep_active": {
                            "type": "boolean",
                            "default": True,
                            "description": "Keep active todos when archiving"
                        }
                    },
                    "required": []
                }
            ),
            TodoTool(
                name="get_todo_stats",
                description="Get statistics about todos (active, completed, total)",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            )
        ]
        return tools

    def _ensure_todo_file(self) -> None:
        """Ensure todo.md file exists with proper structure."""
        if not self.todo_file.exists():
            template = f"""# Todo List

*Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*

## 📋 Active Tasks

## ✅ Completed Tasks

---
*This file is managed by da_code agent. You can edit it manually or through agent commands.*
"""
            self.todo_file.write_text(template.strip() + "\n")

    def _update_timestamp(self, content: str) -> str:
        """Update the last updated timestamp in the content."""
        lines = content.split('\n')
        new_lines = []

        for line in lines:
            if line.startswith('*Last updated:'):
                new_lines.append(f"*Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
            else:
                new_lines.append(line)

        return '\n'.join(new_lines)

    def _parse_todos(self, content: str) -> Dict[str, List[str]]:
        """Parse todos from markdown content."""
        active_todos = []
        completed_todos = []

        lines = content.split('\n')
        current_section = None

        for line in lines:
            line = line.strip()
            if '## 📋 Active Tasks' in line:
                current_section = 'active'
            elif '## ✅ Completed Tasks' in line:
                current_section = 'completed'
            elif line.startswith('## ') and not ('📋 Active Tasks' in line or '✅ Completed Tasks' in line):
                current_section = None
            elif line.startswith('- [ ]') and current_section == 'active':
                active_todos.append(line[5:].strip())
            elif line.startswith('- [x]') and current_section == 'completed':
                completed_todos.append(line[5:].strip())

        return {
            'active': active_todos,
            'completed': completed_todos
        }

    async def handle_read_todos(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle read_todos tool call."""
        try:
            self._ensure_todo_file()

            content = self.todo_file.read_text()
            todos = self._parse_todos(content)

            include_completed = params.get('include_completed', False)

            result = {
                "success": True,
                "file_path": str(self.todo_file),
                "active_count": len(todos['active']),
                "completed_count": len(todos['completed']),
                "active_todos": todos['active'],
                "last_updated": datetime.now().isoformat()
            }

            if include_completed:
                result["completed_todos"] = todos['completed']
                result["full_content"] = content

            return result

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to read todos: {str(e)}"
            }

    async def handle_add_todo(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle add_todo tool call."""
        try:
            task = params.get("task", "").strip()
            priority = params.get("priority", "").strip()
            context = params.get("context", "").strip()

            if not task:
                return {"success": False, "error": "Task description is required"}

            self._ensure_todo_file()

            # Build task text with priority icon and context
            priority_icons = {
                "low": "🔵",
                "medium": "🟡",
                "high": "🔴",
                "urgent": "⚡"
            }

            task_text = task
            if priority and priority in priority_icons:
                task_text = f"{priority_icons[priority]} {task}"

            if context:
                task_text += f" ({context})"

            # Read current content and add new todo
            content = self.todo_file.read_text()
            lines = content.split('\n')
            new_lines = []
            added = False

            for i, line in enumerate(lines):
                new_lines.append(line)
                if '## 📋 Active Tasks' in line and not added:
                    # Add empty line if next line isn't empty
                    if i + 1 < len(lines) and lines[i + 1].strip():
                        new_lines.append("")
                    new_lines.append(f"- [ ] {task_text}")
                    added = True

            if not added:
                # Add Active Tasks section if not found
                new_lines.extend([
                    "",
                    "## 📋 Active Tasks",
                    "",
                    f"- [ ] {task_text}"
                ])

            # Update timestamp and save
            new_content = '\n'.join(new_lines)
            new_content = self._update_timestamp(new_content)
            self.todo_file.write_text(new_content)

            return {
                "success": True,
                "message": f"Added todo: {task}",
                "task": task_text,
                "priority": priority
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to add todo: {str(e)}"
            }

    async def handle_complete_todo(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle complete_todo tool call."""
        try:
            task_text = params.get("task", "").strip()
            task_number = params.get("number", 0)

            if not task_text and not task_number:
                return {"success": False, "error": "Task text or number is required"}

            self._ensure_todo_file()

            content = self.todo_file.read_text()
            lines = content.split('\n')
            new_lines = []
            completed = False

            active_task_count = 0
            in_active_section = False
            completed_section_found = False
            completed_task_line = ""

            # First pass: find and mark the task for completion
            for line in lines:
                if '## 📋 Active Tasks' in line:
                    in_active_section = True
                elif '## ✅ Completed Tasks' in line:
                    in_active_section = False
                    completed_section_found = True
                elif line.startswith('## ') and not ('📋 Active Tasks' in line or '✅ Completed Tasks' in line):
                    in_active_section = False

                if in_active_section and line.startswith('- [ ]'):
                    active_task_count += 1
                    task_content = line[5:].strip()

                    # Check if this is the task to complete
                    should_complete = False
                    if task_number and active_task_count == task_number:
                        should_complete = True
                    elif task_text and task_text.lower() in task_content.lower():
                        should_complete = True

                    if should_complete and not completed:
                        completed_task_line = f"- [x] {task_content}"
                        completed = True
                        continue  # Skip adding the original line

                new_lines.append(line)

            if not completed:
                return {
                    "success": False,
                    "error": f"Todo not found: {task_text or f'#{task_number}'}"
                }

            # Add completed task to completed section
            if completed_section_found:
                # Insert after the completed tasks header
                insert_index = -1
                for i, line in enumerate(new_lines):
                    if '## ✅ Completed Tasks' in line:
                        insert_index = i + 1
                        break

                if insert_index >= 0:
                    # Insert after any existing empty line, or create one
                    if insert_index < len(new_lines) and new_lines[insert_index].strip() == "":
                        new_lines.insert(insert_index + 1, completed_task_line)
                    else:
                        new_lines.insert(insert_index, "")
                        new_lines.insert(insert_index + 1, completed_task_line)
            else:
                # Add completed section
                new_lines.extend([
                    "",
                    "## ✅ Completed Tasks",
                    "",
                    completed_task_line
                ])

            # Update timestamp and save
            new_content = '\n'.join(new_lines)
            new_content = self._update_timestamp(new_content)
            self.todo_file.write_text(new_content)

            return {
                "success": True,
                "message": f"Completed todo: {task_text or f'#{task_number}'}",
                "completed_task": completed_task_line[5:]  # Remove "- [x] "
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to complete todo: {str(e)}"
            }

    async def handle_update_todo(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle update_todo tool call."""
        try:
            old_text = params.get("old_text", "").strip()
            new_text = params.get("new_text", "").strip()
            task_number = params.get("number", 0)

            if not new_text:
                return {"success": False, "error": "New task text is required"}

            if not old_text and not task_number:
                return {"success": False, "error": "Old task text or number is required"}

            self._ensure_todo_file()

            content = self.todo_file.read_text()
            lines = content.split('\n')
            new_lines = []
            updated = False

            active_task_count = 0
            in_active_section = False

            for line in lines:
                if '## 📋 Active Tasks' in line:
                    in_active_section = True
                elif line.startswith('## ') and '📋 Active Tasks' not in line:
                    in_active_section = False

                if in_active_section and line.startswith('- [ ]'):
                    active_task_count += 1
                    task_content = line[5:].strip()

                    # Check if this is the task to update
                    should_update = False
                    if task_number and active_task_count == task_number:
                        should_update = True
                    elif old_text and old_text.lower() in task_content.lower():
                        should_update = True

                    if should_update and not updated:
                        new_lines.append(f"- [ ] {new_text}")
                        updated = True
                    else:
                        new_lines.append(line)
                else:
                    new_lines.append(line)

            if not updated:
                return {
                    "success": False,
                    "error": f"Todo not found: {old_text or f'#{task_number}'}"
                }

            # Update timestamp and save
            new_content = '\n'.join(new_lines)
            new_content = self._update_timestamp(new_content)
            self.todo_file.write_text(new_content)

            return {
                "success": True,
                "message": f"Updated todo: {old_text or f'#{task_number}'} -> {new_text}",
                "old_text": old_text,
                "new_text": new_text
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to update todo: {str(e)}"
            }

    async def handle_archive_todos(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle archive_todos tool call."""
        try:
            keep_active = params.get("keep_active", True)

            self._ensure_todo_file()

            if keep_active:
                # Just clear completed todos
                content = self.todo_file.read_text()
                lines = content.split('\n')
                new_lines = []
                in_completed_section = False

                for line in lines:
                    if '## ✅ Completed Tasks' in line:
                        in_completed_section = True
                        new_lines.append(line)
                    elif line.startswith('## ') and '✅ Completed Tasks' not in line:
                        in_completed_section = False
                        new_lines.append(line)
                    elif in_completed_section and line.startswith('- [x]'):
                        # Skip completed todos (archive them)
                        continue
                    else:
                        new_lines.append(line)

                # Update timestamp and save
                new_content = '\n'.join(new_lines)
                new_content = self._update_timestamp(new_content)
                self.todo_file.write_text(new_content)

                return {
                    "success": True,
                    "message": "Archived completed todos"
                }
            else:
                # Clear everything
                template = f"""# Todo List

*Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*

## 📋 Active Tasks

## ✅ Completed Tasks

---
*This file is managed by da_code agent. You can edit it manually or through agent commands.*
"""
                self.todo_file.write_text(template.strip() + "\n")

                return {
                    "success": True,
                    "message": "Cleared all todos"
                }

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to archive todos: {str(e)}"
            }

    async def handle_get_todo_stats(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle get_todo_stats tool call."""
        try:
            result = await self.handle_read_todos({})

            if result["success"]:
                return {
                    "success": True,
                    "active_count": result["active_count"],
                    "completed_count": result["completed_count"],
                    "total_count": result["active_count"] + result["completed_count"],
                    "file_path": result["file_path"]
                }
            else:
                return result

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to get todo stats: {str(e)}"
            }


class TodoMCPServer:
    """Mock MCP server for todo.md management."""

    def __init__(self, working_directory: str = None):
        """Initialize todo MCP server."""
        self.name = "todo"
        self.description = "Todo list management with markdown persistence"
        self.url = "internal://todo"
        self.todo_ops = TodoOperations(working_directory)

    def get_server_info(self):
        """Get server information for registration."""
        from .models import MCPServerInfo

        tools = [tool.name for tool in self.todo_ops.get_tools()]

        return MCPServerInfo(
            name=self.name,
            url=self.url,
            description=self.description,
            tools=tools,
            status="active"
        )

    async def handle_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MCP tool calls."""
        try:
            if tool_name == "read_todos":
                return await self.todo_ops.handle_read_todos(arguments)
            elif tool_name == "add_todo":
                return await self.todo_ops.handle_add_todo(arguments)
            elif tool_name == "complete_todo":
                return await self.todo_ops.handle_complete_todo(arguments)
            elif tool_name == "update_todo":
                return await self.todo_ops.handle_update_todo(arguments)
            elif tool_name == "archive_todos":
                return await self.todo_ops.handle_archive_todos(arguments)
            elif tool_name == "get_todo_stats":
                return await self.todo_ops.handle_get_todo_stats(arguments)
            else:
                available_tools = [tool.name for tool in self.todo_ops.get_tools()]
                return {
                    "success": False,
                    "error": f"Unknown tool: {tool_name}",
                    "available_tools": available_tools
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"Tool execution failed: {str(e)}"
            }

    async def call_mcp_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Handle MCP call and return JSON response (for agent integration)."""
        result = await self.handle_tool_call(tool_name, arguments)
        return json.dumps(result, indent=2, default=str)

    def get_context_for_agent(self) -> str:
        """Get todo context for agent prompt."""
        try:
            # Use synchronous approach for context
            self.todo_ops._ensure_todo_file()
            content = self.todo_ops.todo_file.read_text()
            todos = self.todo_ops._parse_todos(content)

            if len(todos['active']) == 0:
                return ""

            context = "\n📋 **Current Active Todos:**\n"
            for i, todo in enumerate(todos['active'], 1):
                context += f"{i}. {todo}\n"

            context += f"\n*Use the 'todo' MCP server to manage these {len(todos['active'])} active tasks.*\n"
            return context

        except Exception:
            return ""

    def check_continuation_needed(self) -> bool:
        """Check if session continuation prompt is needed."""
        try:
            self.todo_ops._ensure_todo_file()
            content = self.todo_ops.todo_file.read_text()
            todos = self.todo_ops._parse_todos(content)
            return len(todos['active']) > 0
        except Exception:
            return False

    def show_continuation_prompt(self) -> bool:
        """Show continuation prompt for existing todos."""
        if not self.check_continuation_needed():
            return True

        try:
            content = self.todo_ops.todo_file.read_text()
            todos = self.todo_ops._parse_todos(content)

            print(f"\n🔄 **Found {len(todos['active'])} active todos in todo.md**")
            print("=" * 50)

            for i, todo in enumerate(todos['active'], 1):
                print(f"{i}. {todo}")

            print("=" * 50)

            print("\nOptions:")
            print("1. [C]ontinue with existing todos (recommended)")
            print("2. [F]resh start (archive existing todos)")
            print("3. [V]iew full todo.md file")

            while True:
                try:
                    choice = input("\nChoice [C/f/v]: ").strip().lower()

                    if choice in ['', 'c', 'continue']:
                        print("✅ Continuing with existing todos...")
                        return True
                    elif choice in ['f', 'fresh']:
                        # Archive todos
                        import asyncio
                        result = asyncio.run(self.todo_ops.handle_archive_todos({"keep_active": False}))
                        if result["success"]:
                            print("✅ Cleared all todos, starting fresh...")
                        else:
                            print(f"⚠️  Error clearing todos: {result['error']}")
                        return True
                    elif choice in ['v', 'view']:
                        print(f"\n📄 **Current todo.md content:**\n")
                        print(content)
                        print(f"\n📁 File location: {self.todo_ops.todo_file}")
                        continue
                    else:
                        print("Please enter 'c' for continue, 'f' for fresh, or 'v' to view")

                except (KeyboardInterrupt, EOFError):
                    print("\n👋 Session cancelled")
                    return False

        except Exception as e:
            print(f"⚠️  Error showing continuation prompt: {e}")
            return True