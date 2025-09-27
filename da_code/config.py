"""Configuration management for da_code CLI tool."""

import os
import logging
from pathlib import Path
from typing import Optional

from .models import AgentConfig

logger = logging.getLogger(__name__)


class ConfigManager:
    """Manages configuration loading and environment variables."""

    def __init__(self):
        """Initialize configuration manager."""
        self._load_environment()

    def _load_environment(self) -> None:
        """Load environment variables from .env file if present."""
        env_file = Path('.env')
        if env_file.exists():
            try:
                with open(env_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            key, value = line.split('=', 1)
                            # Only set if not already in environment
                            if key not in os.environ:
                                os.environ[key] = value
                logger.info("Loaded environment variables from .env file")
            except Exception as e:
                logger.error(f"Failed to load .env file: {e}")

    def create_agent_config(self) -> AgentConfig:
        """Create agent configuration from environment variables."""
        # Required Azure OpenAI settings
        azure_endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')
        api_key = os.getenv('AZURE_OPENAI_API_KEY')
        deployment_name = os.getenv('AZURE_OPENAI_DEPLOYMENT', 'gpt-4')

        if not azure_endpoint:
            raise ValueError(
                "AZURE_OPENAI_ENDPOINT environment variable is required. "
                "Set it to your Azure OpenAI endpoint URL."
            )

        if not api_key:
            raise ValueError(
                "AZURE_OPENAI_API_KEY environment variable is required. "
                "Set it to your Azure OpenAI API key."
            )

        # Optional settings with defaults
        api_version = os.getenv('AZURE_OPENAI_API_VERSION', '2023-12-01-preview')
        temperature = float(os.getenv('DA_CODE_TEMPERATURE', '0.7'))
        max_tokens = os.getenv('DA_CODE_MAX_TOKENS')
        agent_timeout = int(os.getenv('DA_CODE_AGENT_TIMEOUT', '600'))
        max_retries = int(os.getenv('DA_CODE_MAX_RETRIES', '2'))
        command_timeout = int(os.getenv('DA_CODE_COMMAND_TIMEOUT', '300'))
        require_confirmation = os.getenv('DA_CODE_REQUIRE_CONFIRMATION', 'true').lower() == 'true'

        return AgentConfig(
            azure_endpoint=azure_endpoint,
            api_key=api_key,
            api_version=api_version,
            deployment_name=deployment_name,
            temperature=temperature,
            max_tokens=int(max_tokens) if max_tokens else None,
            agent_timeout=agent_timeout,
            max_retries=max_retries,
            command_timeout=command_timeout,
            require_confirmation=require_confirmation
        )

    def create_sample_env(self, env_path: Optional[str] = None) -> None:
        """Create a sample .env file with required variables."""
        if env_path is None:
            env_path = '.env'

        sample_content = """# da_code Configuration

# Azure OpenAI Configuration (Required)
AZURE_OPENAI_ENDPOINT=https://your-resource-name.openai.azure.com/
AZURE_OPENAI_API_KEY=your_azure_openai_api_key_here
AZURE_OPENAI_DEPLOYMENT=gpt-4
AZURE_OPENAI_API_VERSION=2023-12-01-preview

# Agent Behavior Settings (Optional)
DA_CODE_TEMPERATURE=0.7
DA_CODE_MAX_TOKENS=
DA_CODE_AGENT_TIMEOUT=600
DA_CODE_MAX_RETRIES=2
DA_CODE_COMMAND_TIMEOUT=300
DA_CODE_REQUIRE_CONFIRMATION=true

# MongoDB Tracking (Optional)
MONGO_HOST=localhost
MONGO_PORT=8004

# Logging
LOG_LEVEL=INFO
"""

        try:
            with open(env_path, 'w') as f:
                f.write(sample_content)
            logger.info(f"Created sample environment file at {env_path}")
            print(f"Sample environment file created at {env_path}")
            print("Please update the Azure OpenAI settings with your actual values.")
        except Exception as e:
            logger.error(f"Failed to create sample .env file: {e}")
            raise

    def validate_config(self) -> bool:
        """Validate that all required configuration is present."""
        try:
            config = self.create_agent_config()
            logger.info("Configuration validation successful")
            return True
        except ValueError as e:
            logger.error(f"Configuration validation failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during configuration validation: {e}")
            return False

    def print_config_status(self) -> None:
        """Print current configuration status."""
        print("\\n=== da_code Configuration Status ===")

        # Check Azure OpenAI settings
        azure_endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')
        api_key = os.getenv('AZURE_OPENAI_API_KEY')
        deployment = os.getenv('AZURE_OPENAI_DEPLOYMENT', 'gpt-4')

        print(f"Azure OpenAI Endpoint: {'✓' if azure_endpoint else '✗'} {azure_endpoint or 'Not set'}")
        print(f"Azure OpenAI API Key: {'✓' if api_key else '✗'} {'Set' if api_key else 'Not set'}")
        print(f"Azure OpenAI Deployment: {deployment}")

        # Check MongoDB settings
        mongo_host = os.getenv('MONGO_HOST', 'localhost')
        mongo_port = os.getenv('MONGO_PORT', '8004')
        print(f"MongoDB Tracking: {mongo_host}:{mongo_port}")

        # Check file existence
        env_file = Path('.env')
        da_md = Path('DA.md')
        da_json = Path('DA.json')

        print(f"\\n=== Project Files ===")
        print(f".env file: {'✓' if env_file.exists() else '✗'} {env_file.absolute()}")
        print(f"DA.md file: {'✓' if da_md.exists() else '✗'} {da_json.absolute()}")
        print(f"DA.json file: {'✓' if da_json.exists() else '✗'} {da_json.absolute()}")

        if not azure_endpoint or not api_key:
            print("\\n⚠️  Missing required Azure OpenAI configuration!")
            print("Run 'da_code --setup' to create a sample configuration file.")


def setup_logging(log_level: str = "INFO") -> None:
    """Setup logging configuration."""
    # Set minimal logging - only show errors by default
    if log_level.upper() in ["DEBUG", "INFO"]:
        log_level = "ERROR"

    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.ERROR),
        format="%(message)s",
        handlers=[
            logging.StreamHandler(),
        ],
    )

    # Silence noisy loggers
    logging.getLogger('httpx').setLevel(logging.ERROR)
    logging.getLogger('openai').setLevel(logging.ERROR)
    logging.getLogger('azure').setLevel(logging.ERROR)
    logging.getLogger('langchain').setLevel(logging.ERROR)
    logging.getLogger('da_code.chat_memory').setLevel(logging.ERROR)
    logging.getLogger('da_code.agent').setLevel(logging.ERROR)
    logging.getLogger('da_code.monitoring').setLevel(logging.ERROR)