"""
Pytest configuration — adds the project root to sys.path so that
`from cogs.spgrader.scoring import ...` resolves correctly when tests
are run from the project root directory:

    python -m pytest cogs/spgrader/tests.py -v
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
