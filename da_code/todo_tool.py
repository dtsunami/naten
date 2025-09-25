"""Simple todo tool for direct integration with the agent."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List
from langchain.tools import Tool


class TodoManager:
    """Simple todo.md file manager with read/create/update operations."""

    def __init__(self, working_directory: str = None):
        """Initialize todo manager."""
        self.working_dir = working_directory or os.getcwd()
        self.todo_file = Path(self.working_dir) / "todo.md"

    def read_todo_file(self) -> str:
        """Read current contents of todo.md file."""
        try:
            if not self.todo_file.exists():
                return "No todo.md file exists in the current directory."

            content = self.todo_file.read_text(encoding='utf-8')
            if not content.strip():
                return "todo.md file exists but is empty."

            return content.strip()

        except Exception as e:
            return f"Error reading todo file: {str(e)}"

    def file_exists(self) -> str:
        """Check if todo.md file exists."""
        try:
            exists = self.todo_file.exists()
            if exists:
                size = self.todo_file.stat().st_size
                return f"✅ todo.md exists ({size} bytes)"
            else:
                return "❌ todo.md does not exist"

        except Exception as e:
            return f"Error checking file existence: {str(e)}"

    def create_todo_file(self, content: str) -> str:
        """Create or completely replace todo.md file with provided content."""
        try:
            # Ensure content follows proper markdown format
            if not content.strip().startswith('# '):
                content = f"# TODO\n\n{content.strip()}"

            self.todo_file.write_text(content.strip() + '\n', encoding='utf-8')
            return f"✅ Created/updated todo.md file"

        except Exception as e:
            return f"Error creating todo file: {str(e)}"

    def update_todo_file(self, new_content: str) -> str:
        """Update todo.md file by replacing its contents."""
        return self.create_todo_file(new_content)


def create_todo_tool(working_directory: str = None) -> Tool:
    """Create a LangChain tool for todo.md file operations."""
    todo_manager = TodoManager(working_directory)

    def handle_todo_operation(tool_input: str) -> str:
        """Handle todo.md file operations."""
        try:
            # Parse input
            if isinstance(tool_input, str):
                try:
                    params = json.loads(tool_input)
                except json.JSONDecodeError:
                    # Treat as raw content for create operation
                    return todo_manager.create_todo_file(tool_input)
            else:
                params = tool_input

            operation = params.get("operation", "read").strip().lower()

            if operation in ["read", "get", "show"]:
                return todo_manager.read_todo_file()

            elif operation in ["exists", "check"]:
                return todo_manager.file_exists()

            elif operation in ["create", "update", "write"]:
                content = params.get("content", "").strip()
                if not content:
                    return "Error: content parameter is required for create/update operations"
                return todo_manager.create_todo_file(content)

            else:
                return f"Error: Supported operations are 'read', 'exists', 'create', 'update'"

        except Exception as e:
            return f"Error in todo operation: {str(e)}"

    return Tool(
        name="todo_file_manager",
        description="""Manage todo.md file with READ, EXISTS, CREATE, and UPDATE operations.

MARKDOWN TODO FORMAT:
- Use standard markdown syntax
- Tasks should use checkbox format: `- [ ] Task description`
- Completed tasks use: `- [x] Task description`
- Group related tasks under headers with `## Section Name`
- Add priority indicators: 🔥 (high), ⚡ (medium), 📝 (low)

OPERATIONS:
1. READ: {"operation": "read"} - Read current todo.md contents
2. EXISTS: {"operation": "exists"} - Check if todo.md file exists
3. CREATE: {"operation": "create", "content": "markdown content"} - Create/replace todo.md
4. UPDATE: {"operation": "update", "content": "markdown content"} - Same as create

COMMON USAGE PATTERNS:
- Check if todos exist: {"operation": "exists"}
- Read current todos: {"operation": "read"}
- Create new todo file: {"operation": "create", "content": "## Tasks\\n- [ ] New task"}

INPUT FORMATS:
- JSON: {"operation": "read"} or {"operation": "create", "content": "..."}
- Raw text: Will be treated as content for create operation

EXAMPLE TODO.MD STRUCTURE:
```
# TODO

## High Priority 🔥
- [ ] Fix critical bug in authentication
- [ ] Deploy security patches

## Work Tasks ⚡
- [ ] Review pull requests
- [x] Update documentation

## Personal 📝
- [ ] Schedule team meeting
- [ ] Prepare quarterly report
```

IMPORTANT: Always use proper markdown with checkbox syntax for todos.
        """,
        func=handle_todo_operation
    )