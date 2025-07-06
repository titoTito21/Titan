# data/applets/example_grid/init.py

class WidgetGrid:
    def __init__(self, speak_func, view=None):
        self.speak = speak_func
        self.view = view
        # Przykładowa siatka 2x2
        self.grid = [
            ["Top-Left", "Top-Right"],
            ["Bottom-Left", "Bottom-Right"]
        ]
        self.current_pos = [0, 0]  # [wiersz, kolumna]

    def set_border(self):
        if self.view:
            try:
                # To jest miejsce na kod, który ustawi obramowanie w przyszłości
                # np. self.view.SetSizerAndFit(some_sizer_with_a_border)
                pass
            except Exception as e:
                print(f"Could not set border on widget: {e}")

    def navigate(self, direction):
        """Nawigacja po siatce (up, down, left, right)."""
        rows = len(self.grid)
        cols = len(self.grid[0])
        
        if direction == 'up':
            if self.current_pos[0] > 0:
                self.current_pos[0] -= 1
            else:
                return False  # Krawędź
        elif direction == 'down':
            if self.current_pos[0] < rows - 1:
                self.current_pos[0] += 1
            else:
                return False
        elif direction == 'left':
            if self.current_pos[1] > 0:
                self.current_pos[1] -= 1
            else:
                return False
        elif direction == 'right':
            if self.current_pos[1] < cols - 1:
                self.current_pos[1] += 1
            else:
                return False
        
        self.speak(self.get_current_element())
        return True

    def activate_current_element(self):
        """Aktywuje bieżący element siatki."""
        element = self.get_current_element()
        self.speak(f"Activated: {element}")
        print(f"Grid widget element activated: {element}")

    def get_current_element(self):
        return self.grid[self.current_pos[0]][self.current_pos[1]]

def get_widget_info():
    """Zwraca informacje o widgecie."""
    return {
        "name": "Example Grid",
        "type": "grid",
    }

def get_widget_instance(speak_func, view=None):
    """Zwraca instancję klasy widgetu."""
    return WidgetGrid(speak_func, view)
