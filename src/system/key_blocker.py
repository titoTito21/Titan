#!/usr/bin/env python3
"""
Legacy key blocker module - all functionality removed
Key blocking and program switching removed from invisible UI in favor of pynput hotkeys only
"""


# Legacy compatibility functions (no-op)
def start_key_blocking(keys_to_block):
    """Legacy compatibility - key blocking disabled"""
    return False


def stop_key_blocking():
    """Legacy compatibility - key blocking disabled"""
    pass


def is_key_blocking_active():
    """Legacy compatibility - key blocking disabled"""
    return False


def setup_program_switch_hook(callback_func):
    """Legacy compatibility - program switching removed"""
    return True


def cleanup_program_switch_hook():
    """Legacy compatibility - program switching removed"""
    pass


def switch_program():
    """Legacy compatibility - program switching removed"""
    return False