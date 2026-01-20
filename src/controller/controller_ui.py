"""
Controller UI integration for TCE Launcher
Handles controller input and provides haptic feedback for UI interactions
"""

import wx
import pygame
import threading
import time
from typing import Dict, Callable, Optional, Any
from src.controller.controller_vibrations import vibration_controller
from src.titan_core.translation import _
from src.titan_core.sound import play_sound
from accessible_output3 import outputs
from src.titan_core.stereo_speech import get_stereo_speech
from src.settings.settings import get_setting
from src.controller.controller_modes import get_mode_manager, ControllerMode

class ControllerUI:
    """Controller integration for wxPython UI with vibration feedback"""

    def __init__(self, parent_window: wx.Window = None):
        self.parent_window = parent_window
        self.controller_enabled = True
        self.controller_input_timer = None
        self._polling_active = False
        self.button_mappings: Dict[int, Callable] = {}
        self.axis_deadzone = 0.3
        self.last_axis_values = {}
        self.input_polling_interval = 50  # milliseconds
        self.startup_time = time.time()  # Record startup time

        # Navigation state
        self.navigation_enabled = True
        self.current_focus = None

        # Controller detection
        self.connected_controllers = set()
        self.output = outputs.auto.Auto()
        self.stereo_speech = get_stereo_speech()
        self.initial_check_done = False  # Track if initial check completed

        # Mode manager integration
        self.mode_manager = get_mode_manager()

        # Trigger state tracking for mode changes
        self.trigger_states = {}

        # Initialize pygame joystick system
        try:
            pygame.init()
            pygame.joystick.init()
        except Exception as e:
            print(f"Failed to initialize pygame joystick system: {e}")

        # Start controller input polling
        self.start_input_polling()

    def start_input_polling(self):
        """Start polling for controller input"""
        if self.controller_input_timer is None:
            if self.parent_window:
                # Use wx.Timer if we have a parent window
                self.controller_input_timer = wx.Timer()
                self.controller_input_timer.Bind(wx.EVT_TIMER, self.poll_controller_input)
                self.controller_input_timer.Start(self.input_polling_interval)
                print("Using wx.Timer for controller polling")
            else:
                # Use threading.Timer as fallback
                self._start_threading_poll()
                print("Using threading.Timer for controller polling")

    def stop_input_polling(self):
        """Stop polling for controller input"""
        if self.controller_input_timer:
            self.controller_input_timer.Stop()
            self.controller_input_timer = None

        # Stop threading poll if running
        if hasattr(self, '_polling_active'):
            self._polling_active = False

    def _start_threading_poll(self):
        """Start polling using threading.Timer"""
        self._polling_active = True
        print("[CONTROLLER] Starting background thread polling")

        def poll_loop():
            while getattr(self, '_polling_active', False):
                try:
                    self.poll_controller_input()
                    time.sleep(self.input_polling_interval / 1000.0)  # Convert ms to seconds
                except Exception as e:
                    print(f"Threading poll error: {e}")
                    time.sleep(1.0)

        poll_thread = threading.Thread(target=poll_loop, daemon=True)
        poll_thread.start()
        print("[CONTROLLER] Background polling thread started")

    def poll_controller_input(self, event=None):
        """Poll controller input and handle events"""
        if not self.controller_enabled:
            return

        try:
            pygame.event.pump()

            # Check for controller connections/disconnections after 6 seconds from startup
            elapsed_time = time.time() - self.startup_time
            if elapsed_time >= 6.0:
                if not self.initial_check_done:
                    # First check - detect already connected controllers
                    print("Starting initial controller check after 6 seconds")
                    self._check_initial_controllers()
                    self.initial_check_done = True
                else:
                    # Regular monitoring for changes
                    self._check_controller_connections()

            # Handle controller input only if we have parent window for wxPython events
            if self.parent_window:
                joystick_count = pygame.joystick.get_count()
                for i in range(joystick_count):
                    try:
                        controller = pygame.joystick.Joystick(i)
                        if not controller.get_init():
                            controller.init()

                        # Check triggers for mode changing
                        # Xbox controllers have triggers as axes 4 (RT) and 5 (LT) in pygame
                        num_axes = controller.get_numaxes()

                        # Initialize trigger detection on first run
                        if not hasattr(self, '_trigger_axes_detected'):
                            self._trigger_axes_detected = True
                            # Xbox controller in pygame:
                            # Axis 0: Left stick X
                            # Axis 1: Left stick Y
                            # Axis 2: Right stick X
                            # Axis 3: Right stick Y
                            # Axis 4: Right Trigger (RT)
                            # Axis 5: Left Trigger (LT)
                            self._left_trigger_axis = 5   # Left Trigger
                            self._right_trigger_axis = 4  # Right Trigger
                            self._last_trigger_values = (0.0, 0.0)
                            print(f"[CONTROLLER] Controller has {num_axes} axes")
                            print(f"[CONTROLLER] Trigger mapping: LT=axis {self._left_trigger_axis}, RT=axis {self._right_trigger_axis}")

                        if num_axes >= 6:  # Xbox controller has 6 axes
                            # Get trigger values
                            left_trigger = controller.get_axis(self._left_trigger_axis)
                            right_trigger = controller.get_axis(self._right_trigger_axis)

                            # Debug: Print trigger values when they change significantly
                            if abs(left_trigger - self._last_trigger_values[0]) > 0.2 or \
                               abs(right_trigger - self._last_trigger_values[1]) > 0.2:
                                print(f"[TRIGGER] LT={left_trigger:+.2f}, RT={right_trigger:+.2f}")
                                self._last_trigger_values = (left_trigger, right_trigger)

                            # Trigger values in pygame for Xbox controllers:
                            # Unpressed: -1.0 (or 0.0 before first use on some systems)
                            # Fully pressed: +1.0
                            #
                            # We consider trigger "pressed" when value > 0.0 (about 50% pressed)
                            # This ensures intentional pressing, not accidental touches
                            left_pressed = left_trigger > 0.0
                            right_pressed = right_trigger > 0.0

                            self.mode_manager.handle_trigger_press(is_left=True, pressed=left_pressed)
                            self.mode_manager.handle_trigger_press(is_left=False, pressed=right_pressed)
                        elif num_axes >= 4:
                            # Fallback for controllers with fewer axes
                            # Try using the last two axes as triggers
                            left_trigger = controller.get_axis(num_axes - 1)
                            right_trigger = controller.get_axis(num_axes - 2)

                            left_pressed = left_trigger > 0.0
                            right_pressed = right_trigger > 0.0

                            self.mode_manager.handle_trigger_press(is_left=True, pressed=left_pressed)
                            self.mode_manager.handle_trigger_press(is_left=False, pressed=right_pressed)

                        # Handle button presses and releases
                        for button_id in range(controller.get_numbuttons()):
                            button_pressed = controller.get_button(button_id)
                            button_key = f"btn_{i}_{button_id}"

                            # Track button state
                            if not hasattr(self, '_button_states'):
                                self._button_states = {}

                            was_pressed = self._button_states.get(button_key, False)

                            if button_pressed and not was_pressed:
                                # Button just pressed
                                self.handle_button_press(button_id, controller, pressed=True)
                            elif not button_pressed and was_pressed:
                                # Button just released
                                self.handle_button_press(button_id, controller, pressed=False)

                            self._button_states[button_key] = button_pressed

                        # Handle analog stick movement
                        for axis_id in range(controller.get_numaxes()):
                            axis_value = controller.get_axis(axis_id)
                            self.handle_axis_movement(axis_id, axis_value, controller)

                        # Handle D-pad (hat)
                        for hat_id in range(controller.get_numhats()):
                            hat_value = controller.get_hat(hat_id)
                            self.handle_hat_movement(hat_id, hat_value, controller)

                    except Exception as controller_error:
                        print(f"Error handling controller {i}: {controller_error}")

        except Exception as e:
            print(f"Controller input polling error: {e}")

    def _check_controller_connections(self):
        """Check for controller connections and disconnections"""
        try:
            joystick_count = pygame.joystick.get_count()
            current_controllers = set()

            # Get currently connected controllers
            for i in range(joystick_count):
                joystick = pygame.joystick.Joystick(i)
                joystick_id = joystick.get_instance_id()
                current_controllers.add(joystick_id)

                # Check for new connections
                if joystick_id not in self.connected_controllers:
                    self._on_controller_connected(joystick)

            # Check for disconnections
            disconnected = self.connected_controllers - current_controllers
            for joystick_id in disconnected:
                self._on_controller_disconnected(joystick_id)

            # Update connected controllers set
            self.connected_controllers = current_controllers

        except Exception as e:
            print(f"Controller connection check error: {e}")

    def _on_controller_connected(self, joystick):
        """Handle controller connection"""
        try:
            if not joystick.get_init():
                joystick.init()

            controller_name = joystick.get_name()

            # Play sound
            play_sound('joystick/detected.ogg')

            # Vibrate 3 times with 40ms pulses
            self._vibrate_connection_sequence(joystick)

            # Screen reader announcement
            message = _("Game pad connected")
            self._announce_joystick_status(message, connected=True)

        except Exception as e:
            print(f"Error handling controller connection: {e}")

    def _on_controller_disconnected(self, joystick_id):
        """Handle controller disconnection"""
        try:

            # Play sound
            play_sound('joystick/removed.ogg')

            # Screen reader announcement
            message = _("Game pad disconnected")
            self._announce_joystick_status(message, connected=False)

        except Exception as e:
            print(f"Error handling controller disconnection: {e}")

    def _vibrate_connection_sequence(self, joystick):
        """Vibrate controller 3 times with 40ms pulses during connection"""
        def vibrate_sequence():
            try:
                for i in range(3):
                    # Vibrate for 40ms
                    vibration_controller.vibrate(duration=0.04, intensity=0.7, vibration_type="connection")
                    time.sleep(0.04)

                    # Pause between vibrations (except after the last one)
                    if i < 2:
                        time.sleep(0.1)

            except Exception as e:
                print(f"Vibration sequence error: {e}")

        # Run vibration in background thread
        vibrate_thread = threading.Thread(target=vibrate_sequence, daemon=True)
        vibrate_thread.start()

    def _announce_joystick_status(self, message: str, connected: bool):
        """Announce joystick status with stereo speech support"""
        try:
            # Check if stereo speech is enabled in settings
            stereo_enabled = get_setting('stereo_speech', 'False', 'invisible_interface').lower() in ['true', '1']

            if stereo_enabled and self.stereo_speech:
                # Use stereo positioning for joystick events
                if connected:
                    position = 0.5   # Center-right for connection
                    pitch_offset = 2   # Higher pitch for connection
                else:
                    position = -0.5  # Center-left for disconnection
                    pitch_offset = -2  # Lower pitch for disconnection

                try:
                    self.stereo_speech.speak_async(message, position=position, pitch_offset=pitch_offset, use_fallback=True)
                except Exception as stereo_e:
                    print(f"Stereo speech failed: {stereo_e}")
                    # Fallback to regular accessible_output3
                    self.output.speak(message)
            else:
                # Use regular accessible_output3 if stereo is disabled
                self.output.speak(message)

        except Exception as e:
            print(f"Error announcing joystick status: {e}")

    def _check_initial_controllers(self):
        """Check for controllers that are already connected at startup"""
        try:
            pygame.event.pump()
            joystick_count = pygame.joystick.get_count()
            print(f"Initial controller check: Found {joystick_count} controllers")

            for i in range(joystick_count):
                try:
                    joystick = pygame.joystick.Joystick(i)
                    joystick_id = joystick.get_instance_id()

                    if joystick_id not in self.connected_controllers:
                        print(f"Announcing connection for controller {i}: {joystick.get_name()}")
                        self._on_controller_connected(joystick)
                        self.connected_controllers.add(joystick_id)

                except Exception as e:
                    print(f"Error checking controller {i} at startup: {e}")

        except Exception as e:
            print(f"Error during initial controller check: {e}")


    def handle_button_press(self, button_id: int, controller: pygame.joystick.Joystick, pressed: bool = True):
        """Handle controller button press/release with vibration feedback"""
        # Check if mode manager handles this button (for non-system modes)
        if self.mode_manager.handle_button_press(button_id, pressed=pressed):
            return  # Mode manager handled it

        # Only handle press events for default actions
        if not pressed:
            return

        # System mode or button not handled by mode manager
        if button_id in self.button_mappings:
            vibration_controller.vibrate_selection()
            self.button_mappings[button_id]()
        else:
            # Default button actions (only in system mode)
            if self.mode_manager.current_mode == ControllerMode.SYSTEM:
                if button_id == 0:  # A button (usually)
                    self.activate_current_item()
                elif button_id == 1:  # B button (usually)
                    self.go_back()
                elif button_id == 2:  # X button (usually)
                    self.open_context_menu()
                elif button_id == 3:  # Y button (usually)
                    self.toggle_menu()
                elif button_id == 4:  # Left shoulder
                    self.previous_page()
                elif button_id == 5:  # Right shoulder
                    self.next_page()
                elif button_id == 6:  # Back/Select
                    self.show_settings()
                elif button_id == 7:  # Start
                    self.show_main_menu()

    def handle_axis_movement(self, axis_id: int, value: float, controller: pygame.joystick.Joystick):
        """Handle analog stick movement for navigation"""
        # Skip trigger axes (4 and 5 on Xbox controllers) - they're handled separately
        if axis_id == 4 or axis_id == 5:
            return

        if not self.navigation_enabled:
            return

        # Check if mode manager handles this axis (for non-system modes)
        if self.mode_manager.handle_axis_movement(axis_id, value, controller.get_id()):
            return  # Mode manager handled it

        # System mode - use default navigation
        if self.mode_manager.current_mode == ControllerMode.SYSTEM:
            # Apply deadzone
            if abs(value) < self.axis_deadzone:
                value = 0.0

            # Get previous value for this axis
            axis_key = f"{controller.get_id()}_{axis_id}"
            previous_value = self.last_axis_values.get(axis_key, 0.0)

            # Only trigger on crossing deadzone threshold
            if abs(previous_value) < self.axis_deadzone and abs(value) >= self.axis_deadzone:
                if axis_id == 0:  # Left stick X-axis
                    if value < 0:
                        self.navigate_left()
                    else:
                        self.navigate_right()
                elif axis_id == 1:  # Left stick Y-axis
                    if value < 0:
                        self.navigate_up()
                    else:
                        self.navigate_down()
                elif axis_id == 3:  # Right stick Y-axis (custom actions)
                    if value < 0:
                        self.secondary_action_up()
                    else:
                        self.secondary_action_down()
                elif axis_id == 4:  # Right stick X-axis (custom actions)
                    if value < 0:
                        self.secondary_action_left()
                    else:
                        self.secondary_action_right()

            self.last_axis_values[axis_key] = value

    def handle_hat_movement(self, hat_id: int, value: tuple, controller: pygame.joystick.Joystick):
        """Handle D-pad movement"""
        if not self.navigation_enabled or value == (0, 0):
            return

        # Check if mode manager handles this hat movement
        if self.mode_manager.handle_hat_movement(hat_id, value):
            return  # Mode manager handled it

        # System mode - use default navigation
        if self.mode_manager.current_mode == ControllerMode.SYSTEM:
            x, y = value

            if x == -1:
                self.navigate_left()
            elif x == 1:
                self.navigate_right()

            if y == 1:
                self.navigate_up()
            elif y == -1:
                self.navigate_down()

    # Navigation methods
    def navigate_up(self):
        """Navigate up in the current view"""
        vibration_controller.vibrate_cursor_move()
        if self.parent_window:
            self.parent_window.Navigate(wx.NavigationKeyEvent.IsUpDirection)

    def navigate_down(self):
        """Navigate down in the current view"""
        vibration_controller.vibrate_cursor_move()
        if self.parent_window:
            self.parent_window.Navigate(wx.NavigationKeyEvent.IsDownDirection)

    def navigate_left(self):
        """Navigate left in the current view"""
        vibration_controller.vibrate_cursor_move()
        if self.parent_window:
            self.parent_window.Navigate(wx.NavigationKeyEvent.IsBackwardDirection)

    def navigate_right(self):
        """Navigate right in the current view"""
        vibration_controller.vibrate_cursor_move()
        if self.parent_window:
            self.parent_window.Navigate(wx.NavigationKeyEvent.IsForwardDirection)

    def activate_current_item(self):
        """Activate the currently focused item"""
        vibration_controller.vibrate_selection()
        focused_window = wx.Window.FindFocus()
        if focused_window:
            # Simulate Enter key press
            key_event = wx.KeyEvent(wx.wxEVT_KEY_DOWN)
            key_event.SetKeyCode(wx.WXK_RETURN)
            focused_window.GetEventHandler().ProcessEvent(key_event)

    def go_back(self):
        """Go back or cancel current action"""
        vibration_controller.vibrate_menu_close()
        if self.parent_window:
            # Simulate Escape key press
            key_event = wx.KeyEvent(wx.wxEVT_KEY_DOWN)
            key_event.SetKeyCode(wx.WXK_ESCAPE)
            self.parent_window.GetEventHandler().ProcessEvent(key_event)

    def open_context_menu(self):
        """Open context menu for current item"""
        vibration_controller.vibrate_menu_open()
        focused_window = wx.Window.FindFocus()
        if focused_window:
            # Simulate right-click
            pos = focused_window.GetPosition()
            menu_event = wx.ContextMenuEvent(wx.wxEVT_CONTEXT_MENU, focused_window.GetId(), pos)
            focused_window.GetEventHandler().ProcessEvent(menu_event)

    def toggle_menu(self):
        """Toggle main menu"""
        vibration_controller.vibrate_menu_open()
        if self.parent_window and hasattr(self.parent_window, 'toggle_menu'):
            self.parent_window.toggle_menu()

    def show_main_menu(self):
        """Show main application menu"""
        vibration_controller.vibrate_menu_open()
        if self.parent_window and hasattr(self.parent_window, 'show_main_menu'):
            self.parent_window.show_main_menu()

    def show_settings(self):
        """Show settings dialog"""
        vibration_controller.vibrate_menu_open()
        if self.parent_window and hasattr(self.parent_window, 'show_settings'):
            self.parent_window.show_settings()

    def previous_page(self):
        """Navigate to previous page/tab"""
        vibration_controller.vibrate_selection()
        if self.parent_window and hasattr(self.parent_window, 'previous_page'):
            self.parent_window.previous_page()

    def next_page(self):
        """Navigate to next page/tab"""
        vibration_controller.vibrate_selection()
        if self.parent_window and hasattr(self.parent_window, 'next_page'):
            self.parent_window.next_page()

    # Secondary actions (right stick)
    def secondary_action_up(self):
        """Custom secondary action - up"""
        vibration_controller.vibrate_focus_change()

    def secondary_action_down(self):
        """Custom secondary action - down"""
        vibration_controller.vibrate_focus_change()

    def secondary_action_left(self):
        """Custom secondary action - left"""
        vibration_controller.vibrate_focus_change()

    def secondary_action_right(self):
        """Custom secondary action - right"""
        vibration_controller.vibrate_focus_change()

    # Configuration methods
    def set_button_mapping(self, button_id: int, callback: Callable):
        """Set custom button mapping"""
        self.button_mappings[button_id] = callback

    def clear_button_mapping(self, button_id: int):
        """Clear button mapping"""
        if button_id in self.button_mappings:
            del self.button_mappings[button_id]

    def set_deadzone(self, deadzone: float):
        """Set analog stick deadzone (0.0-1.0)"""
        self.axis_deadzone = max(0.0, min(1.0, deadzone))

    def set_controller_enabled(self, enabled: bool):
        """Enable or disable controller input"""
        self.controller_enabled = enabled

    def set_navigation_enabled(self, enabled: bool):
        """Enable or disable controller navigation"""
        self.navigation_enabled = enabled

    def set_polling_interval(self, interval_ms: int):
        """Set input polling interval in milliseconds"""
        self.input_polling_interval = max(10, interval_ms)
        if self.controller_input_timer and self.controller_input_timer.IsRunning():
            self.controller_input_timer.Stop()
            self.controller_input_timer.Start(self.input_polling_interval)

    # Event handlers for specific UI events
    def on_window_focus(self, window: wx.Window):
        """Handle window focus change"""
        self.current_focus = window
        vibration_controller.vibrate_focus_change()

    def on_menu_opened(self):
        """Handle menu opened event"""
        vibration_controller.vibrate_menu_open()

    def on_menu_closed(self):
        """Handle menu closed event"""
        vibration_controller.vibrate_menu_close()

    def on_error_occurred(self):
        """Handle error event"""
        vibration_controller.vibrate_error()

    def on_notification(self):
        """Handle notification event"""
        vibration_controller.vibrate_notification()

    def on_startup_complete(self):
        """Handle startup completion event"""
        vibration_controller.vibrate_startup()

    def cleanup(self):
        """Clean up controller UI resources"""
        self.stop_input_polling()
        self.button_mappings.clear()

# Global controller UI instance
_global_controller_ui = None

def initialize_controller_system(parent_window=None):
    """Initialize the global controller detection system"""
    global _global_controller_ui
    try:
        print("Initializing global controller system...")
        _global_controller_ui = ControllerUI(parent_window=parent_window)
        print("Global controller system initialized successfully")
        return True
    except Exception as e:
        print(f"Failed to initialize controller system: {e}")
        import traceback
        traceback.print_exc()
        return False

def shutdown_controller_system():
    """Shutdown the global controller detection system"""
    global _global_controller_ui
    if _global_controller_ui:
        try:
            _global_controller_ui.cleanup()
        except Exception as e:
            print(f"Error during controller system shutdown: {e}")
        finally:
            _global_controller_ui = None

class ControllerSettingsPanel(wx.Panel):
    """Settings panel for controller configuration"""

    def __init__(self, parent, controller_ui: ControllerUI):
        super().__init__(parent)
        self.controller_ui = controller_ui
        self.create_controls()

    def create_controls(self):
        """Create controller settings controls"""
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Controller info
        info_box = wx.StaticBoxSizer(wx.StaticBox(self, label=_("Controller Information")), wx.VERTICAL)

        controller_info = vibration_controller.get_controller_info()
        info_text = f"{_('Connected controllers')}: {controller_info['count']}\n"

        if controller_info['names']:
            info_text += f"{_('Controller names')}:\n"
            for name in controller_info['names']:
                info_text += f"  - {name}\n"

        info_text += f"{_('Vibration available')}: {_('Yes') if controller_info['vibration_available'] else _('No')}"

        info_label = wx.StaticText(self, label=info_text)
        info_box.Add(info_label, 0, wx.ALL, 5)

        # Vibration settings
        vibration_box = wx.StaticBoxSizer(wx.StaticBox(self, label=_("Vibration Settings")), wx.VERTICAL)

        self.vibration_enabled_cb = wx.CheckBox(self, label=_("Enable vibration"))
        self.vibration_enabled_cb.SetValue(controller_info['vibration_enabled'])
        self.vibration_enabled_cb.Bind(wx.EVT_CHECKBOX, self.on_vibration_enabled_changed)
        vibration_box.Add(self.vibration_enabled_cb, 0, wx.ALL, 5)

        strength_label = wx.StaticText(self, label=_("Vibration strength"))
        vibration_box.Add(strength_label, 0, wx.ALL, 5)

        self.vibration_strength_slider = wx.Slider(self, value=int(controller_info['strength'] * 100),
                                                   minValue=0, maxValue=100, style=wx.SL_HORIZONTAL | wx.SL_LABELS)
        self.vibration_strength_slider.Bind(wx.EVT_SLIDER, self.on_vibration_strength_changed)
        vibration_box.Add(self.vibration_strength_slider, 0, wx.EXPAND | wx.ALL, 5)

        # Controller settings
        controller_box = wx.StaticBoxSizer(wx.StaticBox(self, label=_("Controller Settings")), wx.VERTICAL)

        self.controller_enabled_cb = wx.CheckBox(self, label=_("Enable controller input"))
        self.controller_enabled_cb.SetValue(self.controller_ui.controller_enabled)
        self.controller_enabled_cb.Bind(wx.EVT_CHECKBOX, self.on_controller_enabled_changed)
        controller_box.Add(self.controller_enabled_cb, 0, wx.ALL, 5)

        self.navigation_enabled_cb = wx.CheckBox(self, label=_("Enable controller navigation"))
        self.navigation_enabled_cb.SetValue(self.controller_ui.navigation_enabled)
        self.navigation_enabled_cb.Bind(wx.EVT_CHECKBOX, self.on_navigation_enabled_changed)
        controller_box.Add(self.navigation_enabled_cb, 0, wx.ALL, 5)

        deadzone_label = wx.StaticText(self, label=_("Analog stick deadzone"))
        controller_box.Add(deadzone_label, 0, wx.ALL, 5)

        self.deadzone_slider = wx.Slider(self, value=int(self.controller_ui.axis_deadzone * 100),
                                        minValue=0, maxValue=50, style=wx.SL_HORIZONTAL | wx.SL_LABELS)
        self.deadzone_slider.Bind(wx.EVT_SLIDER, self.on_deadzone_changed)
        controller_box.Add(self.deadzone_slider, 0, wx.EXPAND | wx.ALL, 5)

        # Buttons
        button_box = wx.BoxSizer(wx.HORIZONTAL)

        refresh_btn = wx.Button(self, label=_("Refresh Controllers"))
        refresh_btn.Bind(wx.EVT_BUTTON, self.on_refresh_controllers)
        button_box.Add(refresh_btn, 0, wx.ALL, 5)

        test_vibration_btn = wx.Button(self, label=_("Test Vibration"))
        test_vibration_btn.Bind(wx.EVT_BUTTON, self.on_test_vibration)
        button_box.Add(test_vibration_btn, 0, wx.ALL, 5)

        # Layout
        sizer.Add(info_box, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(vibration_box, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(controller_box, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(button_box, 0, wx.CENTER | wx.ALL, 5)

        self.SetSizer(sizer)

    def on_vibration_enabled_changed(self, event):
        """Handle vibration enabled checkbox change"""
        vibration_controller.set_vibration_enabled(event.IsChecked())

    def on_vibration_strength_changed(self, event):
        """Handle vibration strength slider change"""
        strength = event.GetInt() / 100.0
        vibration_controller.set_vibration_strength(strength)

    def on_controller_enabled_changed(self, event):
        """Handle controller enabled checkbox change"""
        self.controller_ui.set_controller_enabled(event.IsChecked())

    def on_navigation_enabled_changed(self, event):
        """Handle navigation enabled checkbox change"""
        self.controller_ui.set_navigation_enabled(event.IsChecked())

    def on_deadzone_changed(self, event):
        """Handle deadzone slider change"""
        deadzone = event.GetInt() / 100.0
        self.controller_ui.set_deadzone(deadzone)

    def on_refresh_controllers(self, event):
        """Handle refresh controllers button"""
        vibration_controller.refresh_controllers()
        # Refresh the info display
        controller_info = vibration_controller.get_controller_info()
        info_text = f"{_('Connected controllers')}: {controller_info['count']}\n"

        if controller_info['names']:
            info_text += f"{_('Controller names')}:\n"
            for name in controller_info['names']:
                info_text += f"  - {name}\n"

        info_text += f"{_('Vibration available')}: {_('Yes') if controller_info['vibration_available'] else _('No')}"

        # Update the info label (would need reference to it)
        wx.MessageBox(_("Controllers refreshed successfully"), _("Controller Settings"))

    def on_test_vibration(self, event):
        """Handle test vibration button"""
        vibration_controller.vibrate(duration=0.5, intensity=1.0)