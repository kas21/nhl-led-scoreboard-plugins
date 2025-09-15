"""
Board plugins package.

This package contains dynamically loadable board plugins.
Each plugin should be in its own subdirectory with the following structure:

plugin_name/
├── __init__.py          # Plugin metadata
├── board.py            # Board implementation (must inherit from BoardBase)
├── config.json         # Plugin-specific configuration (optional)
└── layout.json         # Layout settings (optional)
"""