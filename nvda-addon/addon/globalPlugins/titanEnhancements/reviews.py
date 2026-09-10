# -*- coding: utf-8 -*-
"""One review at a time.

Several things in this add-on walk something with the same arrow keys - a
terminal (:mod:`terminal`), a recognised screen (:mod:`ocrReview`), a Titan
application (:mod:`appReview`), a widget (:mod:`widgetReview`), any window
at all (:mod:`virtualWindow`) and the command palette (:mod:`palette`).
Sharing the keys is deliberate: a user should learn Up, Down, Left, Right,
Home, End, Enter, F5 and Escape once, not six times.

What that costs is this module. NVDA binds a gesture to ONE script per
plugin, so two reviews up at once means the second one's bindings replaced
the first one's - and the first is then a review that is still running,
still says it is running, and answers no key at all. Nothing about that
looks like a bug from the outside; it looks like the arrows breaking.

So starting any of them ends the others, in one place, rather than each
one knowing about the other three - which is the arrangement that would
quietly grow a fifth.
"""

_ALL = ('terminal', 'ocrReview', 'appReview', 'virtualWindow',
        'widgetReview', 'palette')


def stop_others(keep):
    """End every review but this one. Answers which were ended.

    Imported inside the call rather than at the top, because these modules
    import each other and this one is imported by all of them.
    """
    ended = []
    for name in _ALL:
        if name == keep:
            continue
        try:
            module = __import__('%s.%s' % (__package__, name), None, None,
                                [name])
            if module.reviewing():
                module.stop()
                ended.append(name)
        except Exception:                            # noqa: BLE001
            continue
    return ended
