"""A current event loop for the thread that imports the network clients.

Python 3.14 no longer makes an event loop on demand: ``asyncio.get_event_loop()``
on a thread with none set raises instead of creating one, and some of the
libraries behind Titan's messengers ask for the loop while they are being
imported or constructed. ``main.py`` used to answer that by importing
asyncio and making a loop at line 1 - which is 10 MB and a third of a
second of startup (asyncio brings ssl, socket, selectors and
concurrent.futures with it) paid by every user, whether or not they ever
open a messenger. The modules that need it call :func:`ensure_event_loop`
at their own top instead, so the loop exists exactly where and when the
old line made it exist, and nowhere else.
"""


def ensure_event_loop():
    """Make sure this thread has a current event loop; return it."""
    import asyncio
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        pass
    try:
        import warnings
        with warnings.catch_warnings():
            # 3.12 and 3.13 warn when there is no loop; 3.14 raises.
            warnings.simplefilter('ignore', DeprecationWarning)
            loop = asyncio.get_event_loop()
        if loop is not None and not loop.is_closed():
            return loop
    except Exception:
        pass
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop
