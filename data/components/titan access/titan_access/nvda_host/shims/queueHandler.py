# -*- coding: utf-8 -*-
"""NVDA's `queueHandler`: work queued for the reader's own thread."""

eventQueue = 'event'
generators = {}


def queueFunction(queue, func, *args, **kwargs):
    try:
        from titan_access.engine import get_engine
        engine = get_engine()
        engine.post_to_worker(lambda: func(*args, **kwargs))
        return
    except Exception:                                # noqa: BLE001
        pass
    import threading
    threading.Thread(target=func, args=args, kwargs=kwargs,
                     daemon=True).start()


def registerGeneratorObject(generatorObj):
    def run():
        try:
            next(generatorObj)
        except StopIteration:
            return
        queueFunction(eventQueue, run)
    queueFunction(eventQueue, run)


def isPendingItems(queue=None):
    return False


from . import permissive as _permissive  # noqa: E402
_permissive(globals())
