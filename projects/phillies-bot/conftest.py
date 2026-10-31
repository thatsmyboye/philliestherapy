"""
Pytest configuration — adds the project root to sys.path so that `cogs.*` and
`utils.*` imports resolve when tests are run from the project root directory.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
