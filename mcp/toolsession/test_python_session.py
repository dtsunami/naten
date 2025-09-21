#!/usr/bin/env python3
"""Test script to launch a Python kernel ToolSession MCP server."""

import os
import sys
import asyncio
import logging
from pathlib import Path

# Add current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from tools import ToolSession, ToolConfigModel
import mongo

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger("test_python_session")


async def test_python_session():
    """Test creating and saving a Python kernel session."""

    # Set up MongoDB environment variables for testing
    os.environ.setdefault("MONGO_HOST", "p1fm1mon306.amr.corp.intel.com")
    os.environ.setdefault("MONGO_PORT", "9194")
    os.environ.setdefault("MONGO_DATABASE", "")

    try:
        # Connect to MongoDB
        logger.info("Connecting to MongoDB...")
        connected = await mongo.connect()
        if not connected:
            logger.error("Failed to connect to MongoDB")
            return False

        # Create Python tool configuration
        logger.info("Creating Python tool configuration...")
        python_config = ToolConfigModel(
            name="python",
            launch_command="python -i",
            prompt_string=">>> ",
            working_directory="/tmp",
            timeout=60
        )

        # Save config to database
        logger.info("Saving tool config to database...")
        config_saved = await mongo.upsert_config(python_config)
        if config_saved:
            logger.info(f"Tool config saved: {python_config.name}")
        else:
            logger.warning("Failed to save tool config")

        # Create tool session
        logger.info("Creating Python tool session...")
        output_file = "/tmp/python_session_output.log"

        session = ToolSession(
            tool_config=python_config,
            output_file=output_file
        )

        # Save session to database
        logger.info("Saving session to database...")
        session_saved = await mongo.upsert_session(session)
        if session_saved:
            logger.info(f"Session saved: {session.session_id}")
        else:
            logger.warning("Failed to save session")

        # Test adding some session data
        logger.info("Testing session operations...")

        # Add some inputs
        input_id1 = session.add_input("print('Hello World')", "command")
        input_id2 = session.add_input("import math", "command")
        input_id3 = session.add_input("print(math.pi)", "command")

        logger.info(f"Added inputs: {input_id1}, {input_id2}, {input_id3}")

        # Add some outputs
        session.add_output("Hello World", input_id1)
        session.add_output("3.141592653589793", input_id3)

        # Add a script execution
        script_content = """
import numpy as np
arr = np.array([1, 2, 3, 4, 5])
print(f"Array: {arr}")
print(f"Mean: {np.mean(arr)}")
"""
        session.add_script(script_content, "exec(open('{script}').read())", "/tmp/test_script.py", "exec(open('/tmp/test_script.py').read())")

        # Add an error
        session.add_error("test_error", "This is a test error", {"context": "testing"})

        # Update session status
        session.update_status("active")

        # Save updated session
        logger.info("Saving updated session...")
        session_updated = await mongo.upsert_session(session)
        if session_updated:
            logger.info("Session updated successfully")
        else:
            logger.warning("Failed to update session")

        # Test reading session back
        logger.info("Testing session retrieval...")
        retrieved_session = await mongo.read_session(session.session_id)
        if retrieved_session:
            logger.info(f"Retrieved session: {retrieved_session.session_id}")
            logger.info(f"  Tool: {retrieved_session.tool_config.name}")
            logger.info(f"  Status: {retrieved_session.status}")
            logger.info(f"  Total commands: {retrieved_session.total_commands}")
            logger.info(f"  Total scripts: {retrieved_session.total_scripts}")
            logger.info(f"  Total errors: {retrieved_session.total_errors}")
            logger.info(f"  Inputs: {len(retrieved_session.inputs)}")
            logger.info(f"  Outputs: {len(retrieved_session.outputs)}")
            logger.info(f"  Scripts: {len(retrieved_session.scripts)}")
            logger.info(f"  Errors: {len(retrieved_session.errors)}")
        else:
            logger.error("Failed to retrieve session")

        # Test listing sessions
        logger.info("Testing session listing...")
        sessions = await mongo.list_sessions(tool_name="python", limit=10)
        logger.info(f"Found {len(sessions)} Python sessions")
        for sess in sessions:
            logger.info(f"  Session: {sess['session_id']} - Status: {sess['status']}")

        # Test database stats
        logger.info("Getting database statistics...")
        stats = await mongo.get_database_stats()
        logger.info(f"Database stats: {stats}")

        logger.info("Test completed successfully!")
        return True

    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
        return False

    finally:
        # Disconnect from MongoDB
        await mongo.disconnect()


def main():
    """Main entry point for the test."""
    logger.info("Starting Python ToolSession test...")

    # Run the async test
    success = asyncio.run(test_python_session())

    if success:
        logger.info("✅ Test completed successfully!")
        sys.exit(0)
    else:
        logger.error("❌ Test failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()