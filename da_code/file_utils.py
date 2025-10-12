"""File utility functions for da_code."""


def get_file_emoji(filename: str) -> str:
    """Get emoji for file type.

    Args:
        filename: Name of the file (with extension)

    Returns:
        Emoji representing the file type
    """
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
