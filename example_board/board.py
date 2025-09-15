"""
Example board module implementation.
"""
from boards.base_board import BoardBase
from . import __version__, __description__, __board_name__
import datetime


class ExampleBoard(BoardBase):
    """
    Example board module that displays the current time and a custom message.
    
    This demonstrates:
    - Inheriting from BoardBase
    - Using board configuration
    - Basic matrix rendering
    - Standard board interface
    """
    
    def __init__(self, data, matrix, sleepEvent):
        super().__init__(data, matrix, sleepEvent)
        
        # Board metadata from package
        self.board_name = __board_name__
        self.board_version = __version__
        self.board_description = __description__
        
        # Get configuration values with defaults
        self.display_message = self.board_config.get("message", "Hello World!")
        self.text_color = self.board_config.get("text_color", "white")
        self.display_seconds = self.board_config.get("display_seconds", 5)
        
        # Access standard application config
        self.font = data.config.layout.font
        self.font_large = data.config.layout.font_large
    
    def render(self):
        """
        Render the example board content using the matrix renderer's layout system.
        """
        self.matrix.clear()
        
        # Get current time
        now = datetime.datetime.now()
        time_str = now.strftime("%H:%M:%S")
        date_str = now.strftime("%m/%d/%Y")
        
        # Get the layout for this plugin
        layout = self.get_board_layout('example')
        
        if layout:
            # Use matrix renderer's layout-aware drawing methods
            if 'message' in layout:
                self.matrix.draw_text_layout(layout['message'], self.display_message, fillColor=self.text_color)
            
            if 'time' in layout:
                self.matrix.draw_text_layout(layout['time'], time_str, fillColor='cyan')
            
            if 'date' in layout:
                self.matrix.draw_text_layout(layout['date'], date_str, fillColor=self.text_color)
            
            # Show layout info
            if 'plugin_info' in layout:
                info_text = f"Layout: {self.display_width}x{self.display_height}"
                self.matrix.draw_text_layout(layout['plugin_info'], info_text, fillColor='gray')
        else:
            # Fallback rendering without layout
            self.matrix.draw_text_centered(16, self.display_message, self.font, self.text_color)
            self.matrix.draw_text_centered(28, time_str, self.font_large, 'cyan')
            self.matrix.draw_text_centered(40, date_str, self.font, self.text_color)
            self.matrix.draw_text_centered(52, f"No layout ({self.display_width}x{self.display_height})", self.font, 'gray')
        
        # Render to display
        self.matrix.render()
        
        # Wait for configured display time
        self.sleepEvent.wait(self.display_seconds)