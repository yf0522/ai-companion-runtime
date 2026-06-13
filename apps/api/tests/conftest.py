"""Shared test fixtures and configuration."""
import sys
from pathlib import Path

# Ensure the app package is importable from tests
sys.path.insert(0, str(Path(__file__).parent.parent))
