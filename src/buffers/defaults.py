# -*- coding: utf-8 -*-
"""
Titan Buffer System - contextual category registration helpers.

Categories register CONTEXTUALLY, so the review cycle only shows what is
actually active (a logged-in Titan-Net, a connected Telegram, an opened Elten,
a loaded component / IM module / app). Each built-in service calls its
register_* on connect/login and remove_* on disconnect/logout, so its category
(with empty buffers) appears immediately when the context becomes active and
disappears when it ends - instead of every category showing at all times.

Components, Titan IM modules and apps register their own categories on demand
through the injected `buffers` API (see buffer_bus.make_module_api).
"""

from src.buffers import buffer_bus


def _t():
    try:
        from src.titan_core.translation import set_language
        from src.settings.settings import get_setting
        return set_language(get_setting('language', 'pl'))
    except Exception:
        return lambda s: s


def _register(cat_id, cat_name, buffers):
    """buffers: [(buffer_id, buffer_name, kind), ...]. Idempotent."""
    try:
        buffer_bus.register_category(cat_id, cat_name)
        for buf_id, buf_name, kind in buffers:
            buffer_bus.ensure_buffer(cat_id, buf_id, buf_name, kind=kind)
    except Exception as e:
        print(f"[BufferDefaults] register '{cat_id}' error: {e}")


# --- Titan-Net ------------------------------------------------------------- #
def register_titannet():
    _ = _t()
    _register('titannet', _("Titan-Net"), [
        ('chat', _("Chat"), 'message'),
        ('pm', _("Private messages"), 'private'),
        ('notifications', _("Notifications"), 'notification'),
    ])


def remove_titannet():
    buffer_bus.remove_category('titannet')


# --- Telegram -------------------------------------------------------------- #
def register_telegram():
    _ = _t()
    _register('telegram', _("Telegram"), [
        ('chat', _("Chat"), 'message'),
        ('pm', _("Private messages"), 'private'),
    ])


def remove_telegram():
    buffer_bus.remove_category('telegram')


# --- Elten ----------------------------------------------------------------- #
def register_elten():
    _ = _t()
    _register('elten', _("Elten"), [
        ('pm', _("Private messages"), 'private'),
    ])


def remove_elten():
    buffer_bus.remove_category('elten')
