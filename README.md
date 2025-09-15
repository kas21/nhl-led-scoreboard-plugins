# Board Plugins

This directory contains dynamically loadable board plugins for the NHL LED Scoreboard.

## Plugin Structure

Each plugin should be in its own subdirectory with the following structure:

```
plugin_name/
├── __init__.py          # Plugin metadata and requirements
├── board.py            # Board implementation (must inherit from BoardPlugin)  
├── config.json         # Plugin-specific configuration (optional)
└── layout.json         # Layout settings (optional)
```

## Creating a Plugin

1. **Create plugin directory**: Make a new directory with your plugin name
2. **Create `__init__.py`**: Define plugin metadata
3. **Create `board.py`**: Implement your board class inheriting from `BoardPlugin`
4. **Add configuration**: Optional `config.json` for plugin settings

### Example Plugin Class

```python
from boards.base_plugin import BoardPlugin

class MyPlugin(BoardPlugin):
    def __init__(self, data, matrix, sleepEvent):
        super().__init__(data, matrix, sleepEvent)
        self.plugin_name = "My Plugin"
        self.plugin_version = "1.0.0"
        
    def render(self):
        self.matrix.clear()
        self.matrix.draw_text_centered(32, "Hello World!", self.data.config.layout.font)
        self.matrix.render()
        self.sleepEvent.wait(5)
```

## Using Plugins

1. **Drop in plugin folder**: Copy your plugin directory to `src/boards/plugins/`
2. **Add to config**: Include plugin name in board state lists in `config.json`
3. **Restart application**: Plugins are loaded on startup

Example config usage:
```json
{
  "states": {
    "off_day": [
      "my_plugin",
      "clock"
    ]
  }
}
```

## Plugin Configuration

Plugins can have their own `config.json` file which is automatically loaded and available as `self.plugin_config` in the plugin class.

## Available Examples

- `example_plugin/` - Simple demonstration plugin showing basic functionality