# data/applets/example_grid/init.py
from invisibleui import BaseWidget

class WidgetGrid(BaseWidget):
    def __init__(self, speak_func, view=None):
        super().__init__(speak_func)
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
        old_pos = self.current_pos[:]
        
        if direction == 'up':
            if self.current_pos[0] > 0:
                self.current_pos[0] -= 1
            else:
                return False, self.current_pos[1], cols  # Krawędź
        elif direction == 'down':
            if self.current_pos[0] < rows - 1:
                self.current_pos[0] += 1
            else:
                return False, self.current_pos[1], cols
        elif direction == 'left':
            if self.current_pos[1] > 0:
                self.current_pos[1] -= 1
            else:
                return False, self.current_pos[1], cols
        elif direction == 'right':
            if self.current_pos[1] < cols - 1:
                self.current_pos[1] += 1
            else:
                return False, self.current_pos[1], cols
        
        # NIE mów tutaj - navigate_widget() w invisibleui.py będzie mówić z pozycjonowaniem
        # return True z informacją o pozycji dla stereo pozycjonowania
        return True, self.current_pos[1], cols

    def activate_current_element(self):
        """Aktywuje bieżący element siatki."""
        element = self.get_current_element()
        
        # Użyj pozycjonowania stereo dla aktywacji
        cols = len(self.grid[0]) if self.grid else 1
        position = (self.current_pos[1] / (cols - 1) * 2.0) - 1.0 if cols > 1 else 0.0
        
        # Teraz dziedziczymy z BaseWidget więc mamy speak_with_position
        self.speak_with_position(f"Activated: {element}", position=position)
        
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
