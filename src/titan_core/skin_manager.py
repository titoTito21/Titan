"""
TCE Skin Manager - Comprehensive theming system for Titan Control Environment

This module provides a centralized skin management system that handles:
- Color schemes
- Font configurations
- Icon sets
- UI styling
- Sound themes

All UI elements should use this module to maintain visual consistency.
"""

import os
import sys
import configparser
import wx
from src.settings.settings import load_settings, set_setting

# Get project root directory
def get_project_root():
    """Get the project root directory, supporting PyInstaller and Nuitka."""
    # For both PyInstaller and Nuitka, use executable directory
    # (data directories are placed next to exe for backward compatibility)
    if hasattr(sys, '_MEIPASS') or getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        # Development mode - get project root (2 levels up from src/titan_core/)
        return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

PROJECT_ROOT = get_project_root()
SKINS_DIR = os.path.join(PROJECT_ROOT, 'skins')
DEFAULT_SKIN_NAME = "Default"

# Global skin instance
_current_skin = None


class Skin:
    """Represents a complete skin configuration."""

    def __init__(self, name):
        """Initialize skin with given name."""
        self.name = name
        self.path = os.path.join(SKINS_DIR, name) if name != DEFAULT_SKIN_NAME else None

        # Skin data
        self.colors = {}
        self.fonts = {}
        self.icons = {}
        self.start_menu = {}
        self.sounds = {}
        self.interface = {}

        # Load skin data
        self._load()

    def _load(self):
        """Load skin configuration from skin.ini file."""
        if self.name == DEFAULT_SKIN_NAME or not self.path:
            self._load_default()
            return

        skin_ini = os.path.join(self.path, 'skin.ini')
        if not os.path.exists(skin_ini):
            print(f"Warning: skin.ini not found at {skin_ini}, using defaults")
            self._load_default()
            return

        try:
            config = configparser.ConfigParser()
            config.read(skin_ini, encoding='utf-8')

            # Load colors
            if 'Colors' in config:
                for key, value in config['Colors'].items():
                    try:
                        self.colors[key] = self._parse_color(value)
                    except Exception as e:
                        print(f"Error parsing color {key}={value}: {e}")
                        self.colors[key] = wx.NullColour

            # Load fonts
            if 'Fonts' in config:
                for key, value in config['Fonts'].items():
                    self.fonts[key] = value

            # Load icons
            if 'Icons' in config:
                for key, value in config['Icons'].items():
                    icon_path = os.path.join(self.path, value)
                    if os.path.exists(icon_path):
                        self.icons[key] = icon_path
                    else:
                        print(f"Warning: Icon not found: {icon_path}")
                        self.icons[key] = None

            # Load start menu config
            if 'StartMenu' in config:
                self.start_menu = dict(config['StartMenu'])

            # Load sounds config
            if 'Sounds' in config:
                self.sounds = dict(config['Sounds'])

            # Load interface config
            if 'Interface' in config:
                self.interface = dict(config['Interface'])

        except Exception as e:
            print(f"Error loading skin {self.name}: {e}")
            self._load_default()

    def _load_default(self):
        """Load default system colors and fonts."""
        # Default colors
        self.colors = {
            'frame_background_color': wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNFACE),
            'panel_background_color': wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNFACE),
            'listbox_background_color': wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW),
            'listbox_foreground_color': wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT),
            'listbox_selection_background_color': wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT),
            'listbox_selection_foreground_color': wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHTTEXT),
            'label_foreground_color': wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT),
            'toolbar_background_color': wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNFACE),
            'button_face_color': wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNFACE),
            'button_shadow_color': wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNSHADOW),
            'button_highlight_color': wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNHIGHLIGHT),
            'text_color': wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT),
            'window_background_color': wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW),
        }

        # Default fonts
        default_font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
        self.fonts = {
            'default_font_size': str(default_font.GetPointSize()),
            'default_font_face': default_font.GetFaceName(),
            'listbox_font_face': default_font.GetFaceName(),
            'statusbar_font_face': default_font.GetFaceName(),
            'title_font_face': default_font.GetFaceName(),
            'button_font_face': default_font.GetFaceName(),
            'menu_font_face': default_font.GetFaceName(),
        }

        # Default interface
        self.interface = {
            'button_style': 'default',
            'border_style': 'default',
            'scroll_style': 'default',
            'menu_style': 'default',
        }

    def _parse_color(self, color_string):
        """Parse color string to wx.Colour."""
        color_string = color_string.strip()

        # Hex format: #RRGGBB
        if color_string.startswith('#'):
            if len(color_string) == 7:
                r = int(color_string[1:3], 16)
                g = int(color_string[3:5], 16)
                b = int(color_string[5:7], 16)
                return wx.Colour(r, g, b)

        # RGB format: rgb(r, g, b)
        elif color_string.startswith('rgb('):
            rgb_values = color_string[4:-1].split(',')
            if len(rgb_values) == 3:
                r = int(rgb_values[0].strip())
                g = int(rgb_values[1].strip())
                b = int(rgb_values[2].strip())
                return wx.Colour(r, g, b)

        raise ValueError(f"Invalid color format: {color_string}")

    def get_color(self, key, default=None):
        """Get color by key."""
        return self.colors.get(key, default or wx.NullColour)

    def get_font(self, key, default_size=10):
        """Get font by key, returns wx.Font object."""
        face = self.fonts.get(f'{key}_font_face', 'Segoe UI')

        # Get size
        size = default_size
        if 'default_font_size' in self.fonts:
            try:
                size = int(self.fonts['default_font_size'])
            except ValueError:
                pass

        return wx.Font(size, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL,
                      wx.FONTWEIGHT_NORMAL, False, face)

    def get_icon(self, key, size=(16, 16)):
        """Get icon bitmap by key."""
        icon_path = self.icons.get(key)

        if icon_path and os.path.exists(icon_path):
            try:
                # Load image and scale to requested size
                img = wx.Image(icon_path)
                if img.IsOk():
                    img = img.Scale(size[0], size[1], wx.IMAGE_QUALITY_HIGH)
                    return wx.Bitmap(img)
            except Exception as e:
                print(f"Error loading icon {key} from {icon_path}: {e}")

        # Fallback to default wx icon
        return wx.ArtProvider.GetBitmap(wx.ART_QUESTION, wx.ART_OTHER, size)

    def get_icon_path(self, key):
        """Get icon file path by key."""
        return self.icons.get(key)

    def apply_to_window(self, window):
        """Apply skin colors to a window."""
        try:
            bg_color = self.get_color('window_background_color')
            if bg_color and bg_color.IsOk():
                window.SetBackgroundColour(bg_color)

            fg_color = self.get_color('text_color')
            if fg_color and fg_color.IsOk():
                window.SetForegroundColour(fg_color)

            window.Refresh()
        except Exception as e:
            print(f"Error applying skin to window: {e}")

    def apply_to_listbox(self, listbox):
        """Apply skin colors to a listbox."""
        try:
            bg_color = self.get_color('listbox_background_color')
            if bg_color and bg_color.IsOk():
                listbox.SetBackgroundColour(bg_color)

            fg_color = self.get_color('listbox_foreground_color')
            if fg_color and fg_color.IsOk():
                listbox.SetForegroundColour(fg_color)

            font = self.get_font('listbox')
            if font.IsOk():
                listbox.SetFont(font)

            listbox.Refresh()
        except Exception as e:
            print(f"Error applying skin to listbox: {e}")

    def apply_to_button(self, button):
        """Apply skin colors to a button."""
        try:
            bg_color = self.get_color('button_face_color')
            if bg_color and bg_color.IsOk():
                button.SetBackgroundColour(bg_color)

            fg_color = self.get_color('text_color')
            if fg_color and fg_color.IsOk():
                button.SetForegroundColour(fg_color)

            font = self.get_font('button')
            if font.IsOk():
                button.SetFont(font)

            button.Refresh()
        except Exception as e:
            print(f"Error applying skin to button: {e}")


class SkinManager:
    """Manages skin loading and switching."""

    def __init__(self):
        """Initialize the skin manager."""
        self.current_skin = None
        self.available_skins = []
        self._discover_skins()
        self._load_current_skin()

    def _discover_skins(self):
        """Discover all available skins."""
        self.available_skins = [DEFAULT_SKIN_NAME]

        if os.path.exists(SKINS_DIR):
            for item in os.listdir(SKINS_DIR):
                skin_path = os.path.join(SKINS_DIR, item)
                if os.path.isdir(skin_path):
                    skin_ini = os.path.join(skin_path, 'skin.ini')
                    if os.path.exists(skin_ini):
                        self.available_skins.append(item)

    def _load_current_skin(self):
        """Load the currently selected skin from settings."""
        try:
            settings = load_settings()
            skin_name = settings.get('interface', {}).get('skin', DEFAULT_SKIN_NAME)
        except Exception:
            skin_name = DEFAULT_SKIN_NAME

        self.load_skin(skin_name)

    def load_skin(self, skin_name):
        """Load a skin by name."""
        if skin_name not in self.available_skins:
            print(f"Warning: Skin '{skin_name}' not found, using default")
            skin_name = DEFAULT_SKIN_NAME

        try:
            self.current_skin = Skin(skin_name)
            print(f"Loaded skin: {skin_name}")

            # Apply sound theme if specified
            if 'theme' in self.current_skin.sounds:
                try:
                    from src.titan_core.sound import set_theme
                    set_theme(self.current_skin.sounds['theme'])
                except Exception as e:
                    print(f"Error applying sound theme: {e}")

            return True
        except Exception as e:
            print(f"Error loading skin {skin_name}: {e}")
            self.current_skin = Skin(DEFAULT_SKIN_NAME)
            return False

    def switch_skin(self, skin_name):
        """Switch to a different skin and save to settings."""
        if self.load_skin(skin_name):
            try:
                set_setting('skin', skin_name, 'interface')
                return True
            except Exception as e:
                print(f"Error saving skin setting: {e}")
                return False
        return False

    def get_available_skins(self):
        """Get list of available skins."""
        return self.available_skins.copy()

    def get_current_skin(self):
        """Get the current skin object."""
        if not self.current_skin:
            self._load_current_skin()
        return self.current_skin


# Global skin manager instance
_skin_manager = None


def get_skin_manager():
    """Get the global skin manager instance."""
    global _skin_manager
    if _skin_manager is None:
        _skin_manager = SkinManager()
    return _skin_manager


def get_current_skin():
    """Get the current skin (convenience function)."""
    return get_skin_manager().get_current_skin()


def get_skin_color(key, default=None):
    """Get a color from the current skin."""
    return get_current_skin().get_color(key, default)


def get_skin_font(key, default_size=10):
    """Get a font from the current skin."""
    return get_current_skin().get_font(key, default_size)


def get_skin_icon(key, size=(16, 16)):
    """Get an icon bitmap from the current skin."""
    return get_current_skin().get_icon(key, size)


def get_skin_icon_path(key):
    """Get an icon file path from the current skin."""
    return get_current_skin().get_icon_path(key)


def apply_skin_to_window(window):
    """Apply current skin to a window."""
    get_current_skin().apply_to_window(window)


def apply_skin_to_listbox(listbox):
    """Apply current skin to a listbox."""
    get_current_skin().apply_to_listbox(listbox)


def apply_skin_to_button(button):
    """Apply current skin to a button."""
    get_current_skin().apply_to_button(button)
