# Plugin Layout Template

This template shows the structure for plugin layout files. Plugin layouts use the same format as the main system layouts.

## File Naming Convention

- `layout_128x64.json` - For 128x64 displays (most common)
- `layout_64x32.json` - For 64x32 displays (compact)
- `layout.json` - Generic fallback layout

## Layout Structure

Plugin layouts follow the same hierarchical structure as system layouts in `/config/layout/`:

```json
{
    "_default": {
        "position": [0, 0],
        "align": "left-top"
    },
    "my_plugin": {
        "title": {
            "position": ["50%", 12],
            "align": "center-top",
            "font": "large"
        },
        "subtitle": {
            "position": ["50%", 28],
            "align": "center-top",
            "font": "medium"
        },
        "content": {
            "position": [0, 2],
            "relative": {
                "to": "subtitle",
                "align": "center-bottom"
            },
            "font": "medium"
        },
        "logo": {
            "position": [4, 4],
            "align": "left-top",
            "size": [32, 32]
        }
    }
}
```

## Using Layout in Plugin Code

```python
from boards.base_plugin import BoardPlugin

class MyPlugin(BoardPlugin):
    def render(self):
        self.matrix.clear()
        
        # Get the layout for this plugin
        layout = self.get_board_layout('my_plugin')  # matches layout key in JSON
        
        if layout:
            # Use matrix renderer's layout-aware drawing methods
            if 'title' in layout:
                self.matrix.draw_text_layout(layout['title'], "My Plugin Title", fillColor="white")
            
            if 'subtitle' in layout:
                self.matrix.draw_text_layout(layout['subtitle'], "Subtitle text", fillColor="cyan")
            
            if 'content' in layout:
                self.matrix.draw_text_layout(layout['content'], "Content goes here", fillColor="gray")
        else:
            # Fallback for when no layout is available
            self.matrix.draw_text_centered(20, "My Plugin Title", self.data.config.layout.font, "white")
        
        self.matrix.render()
        self.sleepEvent.wait(5)
```

## Layout Properties

### position
Array `[x, y]` defining element position:
- Numbers: Absolute pixel coordinates
- Percentages: `"50%"` for center, `"100%"` for right/bottom edge
- Expressions: `[["50%", 15], 0]` for center + 15 pixels

### align
Text/element alignment:
- `"left-top"`, `"center-top"`, `"right-top"`
- `"left-center"`, `"center-center"`, `"right-center"`
- `"left-bottom"`, `"center-bottom"`, `"right-bottom"`

### font
Font size to use:
- `"default"` - Standard font
- `"medium"` - Medium sized font
- `"large"` - Large font for headlines
- `"wx_medium"`, `"wx_large"` - Weather-specific fonts

### relative
Position relative to another element:
```json
{
    "relative": {
        "to": "other_element_name",
        "align": "center-bottom"
    }
}
```

### size
For background areas or images:
```json
{
    "size": [width, height]
}
```

## Best Practices

1. **Use percentages** for responsive positioning across display sizes
2. **Group related elements** under the same board name in layout
3. **Test both display sizes** (128x64 and 64x32)
4. **Use relative positioning** for elements that should move together
5. **Follow system naming conventions** for fonts and alignment

## Available Methods

### Plugin Layout Methods
- `self.get_board_layout(board_name)` - Get layout object for board
- `self.has_layout()` - Check if layout is loaded
- `self.display_width` - Current display width  
- `self.display_height` - Current display height

### Matrix Renderer Layout Methods
Use these methods directly on `self.matrix`:

- `self.matrix.draw_text_layout(layout_element, text, fillColor=None)` - Draw text
- `self.matrix.draw_image_layout(layout_element, image, offset=(0,0))` - Draw image
- `self.matrix.draw_rectangle_layout(layout_element, fillColor=None, outline=None)` - Draw rectangle
- `self.matrix.draw_pixels_layout(layout_element, pixels, size)` - Draw pixel array

### Example Usage
```python
# Get layout element
layout = self.get_board_layout('my_plugin')
title_element = layout['title']

# Draw using matrix renderer
self.matrix.draw_text_layout(title_element, "Hello World", fillColor="white")

# For images (if you have logo in layout)
if 'logo' in layout:
    logo_image = Image.open("path/to/logo.png")
    self.matrix.draw_image_layout(layout['logo'], logo_image)
```