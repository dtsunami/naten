"""Parser for ignore files used by the da_code agent.

This module supports reading ignore patterns from multiple files and prefers them
in the following order when present:

  1) .daignore
  2) .aiignore
  3) .agentignore

If more than one of these files exists a warning is emitted and the preferred
file (according to the order above) is used.

Patterns from the chosen ignore file are appended to a set of built-in default
patterns and compiled using pathspec (gitwildmatch) for matching.
"""

import logging
from pathlib import Path
from typing import Optional
from pathspec import PathSpec
from pathspec.patterns import GitWildMatchPattern

logger = logging.getLogger(__name__)


class DaIgnore:
    """Parser and matcher for ignore files using gitignore-style syntax."""

    def __init__(self, project_root: str = None):
        """
        Initialize the DaIgnore parser.

        Args:
            project_root: Root directory of the project (defaults to cwd)
        """
        self.project_root = Path(project_root) if project_root else Path.cwd()
        self.spec: Optional[PathSpec] = None

        # Default patterns (always ignored even if no ignore file exists)
        self.default_patterns = [
            '.git/',
            '.da/',
            '__pycache__/',
            '*.pyc',
            '*.pyo',
            '*.pyd',
            '.Python',
            'node_modules/',
            '.venv/',
            'venv/',
            'env/',
            '.env',
            '*.log',
            '.DS_Store',
            'Thumbs.db',
        ]

        self.load()

    def load(self):
        """Load patterns from ignore files (.daignore, .aiignore, .agentignore).

        Preference order:
          1) .daignore
          2) .aiignore
          3) .agentignore

        If multiple exist, a warning is printed and the preferred file is used.
        """
        daignore_path = self.project_root / '.daignore'
        aiignore_path = self.project_root / '.aiignore'
        agentignore_path = self.project_root / '.agentignore'

        patterns = self.default_patterns.copy()

        # Collect candidates that exist
        candidates = [p for p in (daignore_path, aiignore_path, agentignore_path) if p.exists()]

        chosen = None
        if candidates:
            # Choose based on preference order (daignore > aiignore > agentignore)
            if daignore_path.exists():
                chosen = daignore_path
            elif aiignore_path.exists():
                chosen = aiignore_path
            else:
                chosen = agentignore_path

            if len(candidates) > 1:
                names = ', '.join([p.name for p in candidates])
                msg = (
                    f"Multiple ignore files found: {names}. "
                    f"Using {chosen.name} (preference: .daignore > .aiignore > .agentignore)."
                )
                logger.warning(msg)

            # Read the chosen file and append non-empty, non-comment lines
            try:
                with open(chosen, 'r', encoding='utf-8') as f:
                    for raw in f:
                        s = raw.strip()
                        if s and not s.startswith('#'):
                            patterns.append(s)
                logger.info(f"Loaded {len(patterns)} patterns from {chosen.name}")
            except Exception as e:
                logger.error(f"Error loading {chosen.name if chosen else 'ignore file'}: {e}")
        else:
            logger.debug("No ignore file (.daignore/.aiignore/.agentignore) found, using default patterns")

        # Create PathSpec from patterns
        self.spec = PathSpec.from_lines(GitWildMatchPattern, patterns)

    def is_ignored(self, path: str) -> bool:
        """
        Check if a path should be ignored.

        Args:
            path: Path to check (can be relative or absolute)

        Returns:
            True if path should be ignored
        """
        if not self.spec:
            return False

        try:
            # Convert to Path object
            path_obj = Path(path)

            # Try to get relative path from project root
            try:
                if path_obj.is_absolute():
                    rel_path = path_obj.relative_to(self.project_root)
                else:
                    rel_path = path_obj
            except ValueError:
                # Path is outside project root - don't ignore
                return False

            # Use pathspec to match (normalize path separators)
            rel_path_str = str(rel_path).replace('\\', '/')
            return self.spec.match_file(rel_path_str)

        except Exception as e:
            logger.error(f"Error checking if path is ignored: {e}")
            return False

    def reload(self):
        """Reload patterns from ignore files."""
        self.load()


def create_example_daignore(project_root: str = None):
    """
    Create an example .da.ignore file.

    Args:
        project_root: Root directory of the project (defaults to cwd)
    """
    root = Path(project_root) if project_root else Path.cwd()
    daignore_path = root / '.da.ignore'

    example_content = """# .da.ignore - Files and directories to exclude from da_code agent access
#
# Syntax same as .gitignore:
#   - Lines starting with # are comments
#   - Blank lines are ignored
#   - Use / for directories
#   - Use * for wildcards
#   - Use ** for recursive wildcards
#   - Use ! to negate patterns
#
# Default patterns (always active even if not listed):
#   .git/, .da/, __pycache__/, *.pyc, node_modules/, .venv/, .env

# Secrets and credentials
*.key
*.pem
*.p12
*.pfx
secrets.json
credentials.json
*.secret

# Large binary files
*.bin
*.exe
*.dll
*.so
*.dylib
*.zip
*.tar.gz
*.rar
*.7z

# Media files
*.mp4
*.avi
*.mov
*.mp3
*.wav
*.flac
*.png
*.jpg
*.jpeg
*.gif
*.bmp
*.svg

# Build artifacts
dist/
build/
*.egg-info/
.pytest_cache/
.mypy_cache/
.tox/
htmlcov/
.coverage
target/
out/

# IDE files
.vscode/
.idea/
*.swp
*.swo
*~
*.sublime-*

# OS files
.DS_Store
Thumbs.db
desktop.ini

# Temporary files
*.tmp
*.bak
*.old
*.orig

# Large data files
*.csv
*.json.gz
*.parquet
*.h5
*.hdf5
data/
datasets/

# Documentation builds
docs/_build/
site/
_site/

# Package managers
package-lock.json
yarn.lock
Pipfile.lock
poetry.lock

# Database files
*.db
*.sqlite
*.sqlite3
"""

    try:
        with open(daignore_path, 'w', encoding='utf-8') as f:
            f.write(example_content)
        logger.info(f"Created example .da.ignore at {daignore_path}")
        return True
    except Exception as e:
        logger.error(f"Error creating .da.ignore: {e}")
        return False

import logging
from pathlib import Path
from typing import Optional
from pathspec import PathSpec
from pathspec.patterns import GitWildMatchPattern

logger = logging.getLogger(__name__)


class DaIgnore:
    """Parser and matcher for .daignore files using gitignore-style syntax."""

    def __init__(self, project_root: str = None):
        """
        Initialize .daignore parser.

        Args:
            project_root: Root directory of the project (defaults to cwd)
        """
        self.project_root = Path(project_root) if project_root else Path.cwd()
        self.spec: Optional[PathSpec] = None

        # Default patterns (always ignored even if .daignore doesn't exist)
        self.default_patterns = [
            '.git/',
            '.da/',
            '__pycache__/',
            '*.pyc',
            '*.pyo',
            '*.pyd',
            '.Python',
            'node_modules/',
            '.venv/',
            'venv/',
            'env/',
            '.env',
            '*.log',
            '.DS_Store',
            'Thumbs.db',
        ]

        self.load()

    def load(self):
        """Load patterns from .daignore file."""
        daignore_path = self.project_root / '.daignore'

        patterns = self.default_patterns.copy()

        if daignore_path.exists():
            try:
                with open(daignore_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()

                # Add non-empty, non-comment lines
                for line in lines:
                    stripped = line.strip()
                    if stripped and not stripped.startswith('#'):
                        patterns.append(stripped)

                logger.info(f"Loaded {len(patterns)} patterns from .daignore")
            except Exception as e:
                logger.error(f"Error loading .daignore: {e}")
        else:
            logger.debug("No .daignore file found, using default patterns")

        # Create PathSpec from patterns
        self.spec = PathSpec.from_lines(GitWildMatchPattern, patterns)

    def is_ignored(self, path: str) -> bool:
        """
        Check if a path should be ignored.

        Args:
            path: Path to check (can be relative or absolute)

        Returns:
            True if path should be ignored
        """
        if not self.spec:
            return False

        try:
            # Convert to Path object
            path_obj = Path(path)

            # Try to get relative path from project root
            try:
                if path_obj.is_absolute():
                    rel_path = path_obj.relative_to(self.project_root)
                else:
                    rel_path = path_obj
            except ValueError:
                # Path is outside project root - don't ignore
                return False

            # Use pathspec to match (normalize path separators)
            rel_path_str = str(rel_path).replace('\\', '/')
            return self.spec.match_file(rel_path_str)

        except Exception as e:
            logger.error(f"Error checking if path is ignored: {e}")
            return False

    def reload(self):
        """Reload patterns from .daignore file."""
        self.load()


def create_example_daignore(project_root: str = None):
    """
    Create an example .daignore file.

    Args:
        project_root: Root directory of the project (defaults to cwd)
    """
    root = Path(project_root) if project_root else Path.cwd()
    daignore_path = root / '.daignore'

    example_content = """# .daignore - Files and directories to exclude from da_code agent access
#
# Syntax same as .gitignore:
#   - Lines starting with # are comments
#   - Blank lines are ignored
#   - Use / for directories
#   - Use * for wildcards
#   - Use ** for recursive wildcards
#   - Use ! to negate patterns
#
# Default patterns (always active even if not listed):
#   .git/, .da/, __pycache__/, *.pyc, node_modules/, .venv/, .env

# Secrets and credentials
*.key
*.pem
*.p12
*.pfx
secrets.json
credentials.json
*.secret

# Large binary files
*.bin
*.exe
*.dll
*.so
*.dylib
*.zip
*.tar.gz
*.rar
*.7z

# Media files
*.mp4
*.avi
*.mov
*.mp3
*.wav
*.flac
*.png
*.jpg
*.jpeg
*.gif
*.bmp
*.svg

# Build artifacts
dist/
build/
*.egg-info/
.pytest_cache/
.mypy_cache/
.tox/
htmlcov/
.coverage
target/
out/

# IDE files
.vscode/
.idea/
*.swp
*.swo
*~
*.sublime-*

# OS files
.DS_Store
Thumbs.db
desktop.ini

# Temporary files
*.tmp
*.bak
*.old
*.orig

# Large data files
*.csv
*.json.gz
*.parquet
*.h5
*.hdf5
data/
datasets/

# Documentation builds
docs/_build/
site/
_site/

# Package managers
package-lock.json
yarn.lock
Pipfile.lock
poetry.lock

# Database files
*.db
*.sqlite
*.sqlite3
"""

    try:
        with open(daignore_path, 'w', encoding='utf-8') as f:
            f.write(example_content)
        logger.info(f"Created example .daignore at {daignore_path}")
        return True
    except Exception as e:
        logger.error(f"Error creating .daignore: {e}")
        return False