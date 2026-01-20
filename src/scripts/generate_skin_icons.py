"""
Icon Generator for TCE Skins

This script generates icon sets for all TCE skins with appropriate colors
and styles matching each skin's theme.
"""

import os
import sys
from PIL import Image, ImageDraw, ImageFont

# Get project root
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
SKINS_DIR = os.path.join(PROJECT_ROOT, 'skins')

# Icon definitions with simple shapes for each icon
ICON_DEFINITIONS = {
    # Main UI icons
    'apps': {'shape': 'grid', 'desc': 'Applications grid'},
    'games': {'shape': 'gamepad', 'desc': 'Game controller'},
    'titan': {'shape': 'star', 'desc': 'Titan logo'},
    'start': {'shape': 'windows', 'desc': 'Start button'},

    # System icons
    'settings': {'shape': 'gear', 'desc': 'Settings gear'},
    'components': {'shape': 'puzzle', 'desc': 'Puzzle piece'},
    'help': {'shape': 'question', 'desc': 'Question mark'},
    'shutdown': {'shape': 'power', 'desc': 'Power button'},
    'restart': {'shape': 'refresh_circle', 'desc': 'Circular arrows'},
    'logout': {'shape': 'exit', 'desc': 'Exit door'},
    'lock': {'shape': 'lock', 'desc': 'Padlock'},

    # Network icons
    'network': {'shape': 'globe', 'desc': 'Globe'},
    'telegram': {'shape': 'paper_plane', 'desc': 'Paper airplane'},
    'messenger': {'shape': 'chat_bubble', 'desc': 'Chat bubble'},
    'whatsapp': {'shape': 'phone', 'desc': 'Phone'},
    'titannet': {'shape': 'network_nodes', 'desc': 'Network nodes'},
    'wifi': {'shape': 'wifi', 'desc': 'WiFi signal'},
    'bluetooth': {'shape': 'bluetooth', 'desc': 'Bluetooth symbol'},

    # Notification and status icons
    'notifications': {'shape': 'bell', 'desc': 'Bell'},
    'volume': {'shape': 'speaker', 'desc': 'Speaker'},
    'battery': {'shape': 'battery', 'desc': 'Battery'},
    'time': {'shape': 'clock', 'desc': 'Clock'},
    'updates': {'shape': 'download', 'desc': 'Download arrow'},

    # File and folder icons
    'folder': {'shape': 'folder', 'desc': 'Folder'},
    'file': {'shape': 'document', 'desc': 'Document'},
    'search': {'shape': 'magnifier', 'desc': 'Magnifying glass'},
    'recent': {'shape': 'history', 'desc': 'History clock'},

    # Action icons
    'add': {'shape': 'plus', 'desc': 'Plus sign'},
    'remove': {'shape': 'minus', 'desc': 'Minus sign'},
    'edit': {'shape': 'pencil', 'desc': 'Pencil'},
    'save': {'shape': 'floppy', 'desc': 'Floppy disk'},
    'open': {'shape': 'folder_open', 'desc': 'Open folder'},
    'delete': {'shape': 'trash', 'desc': 'Trash can'},
    'refresh': {'shape': 'refresh', 'desc': 'Refresh arrows'},
    'back': {'shape': 'arrow_left', 'desc': 'Left arrow'},
    'forward': {'shape': 'arrow_right', 'desc': 'Right arrow'},
    'close': {'shape': 'x', 'desc': 'X mark'},

    # Utility icons
    'calculator': {'shape': 'calculator', 'desc': 'Calculator'},
    'notepad': {'shape': 'notepad', 'desc': 'Notepad'},
    'taskmanager': {'shape': 'chart', 'desc': 'Bar chart'},
    'terminal': {'shape': 'terminal', 'desc': 'Command prompt'},
    'browser': {'shape': 'compass', 'desc': 'Compass'},

    # Controller icons
    'controller': {'shape': 'gamepad', 'desc': 'Game controller'},
    'joystick': {'shape': 'joystick', 'desc': 'Joystick'},

    # User icons
    'user': {'shape': 'person', 'desc': 'Person silhouette'},
    'profile': {'shape': 'person_card', 'desc': 'Person with card'},
}

# Skin color schemes
SKIN_COLORS = {
    'dark_theme': {
        'bg': (46, 46, 46),
        'fg': (224, 224, 224),
        'accent': (0, 128, 128),
    },
    'modern_blue': {
        'bg': (240, 248, 255),
        'fg': (0, 51, 102),
        'accent': (0, 102, 204),
    },
    'retro': {
        'bg': (192, 192, 192),
        'fg': (0, 0, 0),
        'accent': (0, 0, 128),
    },
    'windows95': {
        'bg': (192, 192, 192),
        'fg': (0, 0, 0),
        'accent': (0, 0, 128),
    },
    'high_contrast': {
        'bg': (0, 0, 0),
        'fg': (255, 255, 0),
        'accent': (255, 255, 255),
    },
}


def draw_shape(draw, shape_name, size, color, accent_color):
    """Draw a specific shape icon."""
    width, height = size
    margin = int(width * 0.15)

    if shape_name == 'gear':
        # Settings gear
        center_x, center_y = width // 2, height // 2
        outer_radius = width // 2 - margin
        inner_radius = outer_radius // 2
        draw.ellipse([center_x - outer_radius, center_y - outer_radius,
                     center_x + outer_radius, center_y + outer_radius],
                    outline=color, width=3)
        draw.ellipse([center_x - inner_radius, center_y - inner_radius,
                     center_x + inner_radius, center_y + inner_radius],
                    fill=color)

    elif shape_name == 'grid':
        # Application grid (3x3)
        spacing = (width - 2 * margin) // 4
        for row in range(3):
            for col in range(3):
                x = margin + col * spacing
                y = margin + row * spacing
                size_box = spacing // 2
                draw.rectangle([x, y, x + size_box, y + size_box], fill=color)

    elif shape_name == 'gamepad':
        # Game controller shape
        draw.ellipse([margin, margin + height // 4,
                     width - margin, height - margin],
                    outline=color, width=3)
        draw.rectangle([margin + width // 4, margin,
                       width - margin - width // 4, height - margin],
                      outline=color, width=2)

    elif shape_name == 'star':
        # Star shape (Titan logo)
        center_x, center_y = width // 2, height // 2
        points = []
        for i in range(5):
            angle = i * 144 - 90
            import math
            x = center_x + int((width // 2 - margin) * math.cos(math.radians(angle)))
            y = center_y + int((height // 2 - margin) * math.sin(math.radians(angle)))
            points.append((x, y))
        draw.polygon(points, fill=accent_color, outline=color)

    elif shape_name == 'windows':
        # Windows start button (4 squares)
        half_w, half_h = width // 2, height // 2
        gap = 4
        draw.rectangle([margin, margin, half_w - gap, half_h - gap], fill=color)
        draw.rectangle([half_w + gap, margin, width - margin, half_h - gap], fill=color)
        draw.rectangle([margin, half_h + gap, half_w - gap, height - margin], fill=color)
        draw.rectangle([half_w + gap, half_h + gap, width - margin, height - margin], fill=color)

    elif shape_name == 'puzzle':
        # Puzzle piece
        draw.rectangle([margin, margin, width - margin, height - margin],
                      outline=color, width=3)
        draw.ellipse([width // 2 - 8, margin - 8, width // 2 + 8, margin + 8], fill=color)

    elif shape_name == 'question':
        # Question mark
        try:
            font = ImageFont.truetype("arial.ttf", int(height * 0.7))
        except:
            font = ImageFont.load_default()
        draw.text((width // 2, height // 2), "?", fill=color, font=font, anchor="mm")

    elif shape_name == 'power':
        # Power button
        draw.arc([margin, margin, width - margin, height - margin],
                start=45, end=315, fill=color, width=3)
        draw.line([width // 2, margin, width // 2, height // 2], fill=color, width=3)

    elif shape_name == 'lock':
        # Padlock
        draw.rectangle([margin + width // 4, height // 2,
                       width - margin - width // 4, height - margin],
                      fill=color)
        draw.arc([margin + width // 4, margin,
                 width - margin - width // 4, height // 2],
                start=180, end=0, fill=color, width=3)

    elif shape_name == 'bell':
        # Notification bell
        draw.polygon([(width // 2, margin + 5),
                     (margin + 5, height - margin - 5),
                     (width - margin - 5, height - margin - 5)],
                    outline=color, fill=None)
        draw.ellipse([width // 2 - 3, margin, width // 2 + 3, margin + 6], fill=color)

    elif shape_name == 'folder':
        # Folder
        draw.rectangle([margin, height // 3, width - margin, height - margin],
                      fill=color, outline=accent_color)
        draw.polygon([(margin, height // 3),
                     (margin + width // 4, margin),
                     (width // 2, margin),
                     (width // 2 + 5, height // 3)],
                    fill=color, outline=accent_color)

    elif shape_name == 'magnifier':
        # Magnifying glass
        draw.ellipse([margin, margin, width - margin - 10, height - margin - 10],
                    outline=color, width=3)
        draw.line([width - margin - 10, height - margin - 10,
                  width - margin, height - margin], fill=color, width=3)

    elif shape_name == 'plus':
        # Plus sign
        draw.line([width // 2, margin, width // 2, height - margin], fill=color, width=4)
        draw.line([margin, height // 2, width - margin, height // 2], fill=color, width=4)

    elif shape_name == 'minus':
        # Minus sign
        draw.line([margin, height // 2, width - margin, height // 2], fill=color, width=4)

    elif shape_name == 'x':
        # X mark
        draw.line([margin, margin, width - margin, height - margin], fill=color, width=4)
        draw.line([width - margin, margin, margin, height - margin], fill=color, width=4)

    elif shape_name == 'arrow_left':
        # Left arrow
        draw.polygon([(margin, height // 2),
                     (width - margin, margin),
                     (width - margin, height - margin)],
                    fill=color)

    elif shape_name == 'arrow_right':
        # Right arrow
        draw.polygon([(width - margin, height // 2),
                     (margin, margin),
                     (margin, height - margin)],
                    fill=color)

    else:
        # Default: simple circle
        draw.ellipse([margin, margin, width - margin, height - margin],
                    outline=color, fill=accent_color, width=2)


def generate_icon(skin_name, icon_name, shape, size=(32, 32)):
    """Generate a single icon for a skin."""
    colors = SKIN_COLORS.get(skin_name, SKIN_COLORS['dark_theme'])

    # Create image with transparency
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Draw the shape
    draw_shape(draw, shape, size, colors['fg'], colors['accent'])

    return img


def generate_all_icons():
    """Generate all icons for all skins."""
    print("Generating TCE skin icons...")

    for skin_name in SKIN_COLORS.keys():
        skin_icons_dir = os.path.join(SKINS_DIR, skin_name, 'icons')

        if not os.path.exists(skin_icons_dir):
            os.makedirs(skin_icons_dir)
            print(f"Created directory: {skin_icons_dir}")

        print(f"\nGenerating icons for {skin_name}...")

        for icon_name, icon_info in ICON_DEFINITIONS.items():
            shape = icon_info['shape']
            icon_path = os.path.join(skin_icons_dir, f'{icon_name}.png')

            # Generate icon
            img = generate_icon(skin_name, icon_name, shape)
            img.save(icon_path)
            print(f"  - Created {icon_name}.png ({icon_info['desc']})")

    print("\nAll icons generated successfully!")


if __name__ == '__main__':
    generate_all_icons()
