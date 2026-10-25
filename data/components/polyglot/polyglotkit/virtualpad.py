# -*- coding: utf-8 -*-
"""A gamepad that is not there, as far as Titan can tell.

Titan reads a pad by polling SDL (through pygame): ``get_count``, then
``get_button`` on every joystick, every 50 ms. SDL can attach a VIRTUAL
joystick (``SDL_JoystickAttachVirtual``, SDL 2.0.14+) that it reports exactly
like a USB one, so a button set on it is read by Titan's own polling loop and
travels the same way a real button does - the controller UI, the mode
manager, the active gamepad mode. Only the cable is missing.

Used by ``polyglot.check_addon`` to try a gamepad mode without a pad.
"""

import ctypes
import os
import time

SDL_JOYSTICK_TYPE_GAMECONTROLLER = 1


def _sdl():
    import pygame
    path = os.path.join(os.path.dirname(pygame.__file__), 'SDL2.dll')
    library = ctypes.CDLL(path) if os.path.isfile(path) else None
    if library is None:
        raise RuntimeError('SDL is not reachable.')
    for name in ('SDL_JoystickAttachVirtual', 'SDL_JoystickDetachVirtual',
                 'SDL_JoystickSetVirtualButton', 'SDL_JoystickFromInstanceID',
                 'SDL_JoystickGetDeviceInstanceID'):
        if not hasattr(library, name):
            raise RuntimeError('This SDL has no virtual joysticks.')
    library.SDL_JoystickFromInstanceID.restype = ctypes.c_void_p
    library.SDL_JoystickSetVirtualButton.argtypes = [ctypes.c_void_p,
                                                     ctypes.c_int,
                                                     ctypes.c_uint8]
    return library


def press(button, hold=0.4, wait_for_titan=15.0):
    """Attach a virtual pad, wait until Titan has opened it, press and
    release ``button``, detach it. Answers a sentence of what happened."""
    sdl = _sdl()
    index = sdl.SDL_JoystickAttachVirtual(SDL_JOYSTICK_TYPE_GAMECONTROLLER,
                                          6, 15, 1)
    if index < 0:
        raise RuntimeError('SDL refused a virtual pad.')
    try:
        instance = sdl.SDL_JoystickGetDeviceInstanceID(index)
        end = time.time() + wait_for_titan
        pad = None
        # Titan's polling loop opens every joystick it sees; until it has,
        # there is nobody reading the buttons.
        while time.time() < end:
            pad = sdl.SDL_JoystickFromInstanceID(instance)
            if pad:
                break
            time.sleep(0.1)
        if not pad:
            raise RuntimeError("Titan's gamepad loop did not open the pad.")
        time.sleep(0.3)
        sdl.SDL_JoystickSetVirtualButton(pad, int(button), 1)
        time.sleep(hold)
        sdl.SDL_JoystickSetVirtualButton(pad, int(button), 0)
        time.sleep(0.3)
        return 'virtual pad: button %d pressed and released' % button
    finally:
        sdl.SDL_JoystickDetachVirtual(index)
