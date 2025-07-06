# data/applets/example_button/init.py

class WidgetButton:
    def __init__(self, speak_func, view=None):
        self.speak = speak_func
        self.view = view

    def activate_current_element(self):
        """Aktywuje widget."""
        self.speak("Example button activated!")
        print("Example button widget activated.")

    def get_current_element(self):
        return "Example Button"

def get_widget_info():
    """Zwraca informacje o widgecie."""
    return {
        "name": "Example Button",
        "type": "button",
    }

def get_widget_instance(speak_func, view=None):
    """Zwraca instancję klasy widgetu."""
    return WidgetButton(speak_func, view)
