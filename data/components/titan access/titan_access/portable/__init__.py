# -*- coding: utf-8 -*-
"""What both readers on this desktop do the same way.

Somebody reading this desktop uses Titan Access, or NVDA with Titan's
add-on, or both. A control they named, a window they asked what it is
written in, a virtual machine they are reading as a picture: the answer
should not depend on which reader they happen to be in.

**These files are byte-identical to the add-on's own** - they are one
source vendored into two trees, not two implementations of one idea, and
`tests/test_shared_names.py` fails if they drift apart. Vendored rather
than imported because the two ship separately: the add-on is a
`.nvda-addon` a user installs into NVDA, and this is a Titan component,
and neither may depend on the other being present.

The only things that differ are the two shims beside them - `i18n`, which
answers through this reader's own catalogue, and nothing else. Every
module here asks for what it needs the way the add-on asks, and each of
them was written to answer honestly when the thing is not there.
"""

from . import anchors            # noqa: F401
from . import classes            # noqa: F401
from . import findControl        # noqa: F401
from . import labels             # noqa: F401
from . import layers             # noqa: F401
from . import monitors           # noqa: F401
from . import perProgram         # noqa: F401
from . import procedures         # noqa: F401
from . import schemes            # noqa: F401
from . import shared             # noqa: F401
from . import toolkit            # noqa: F401
from . import verify             # noqa: F401
from . import virtualInput       # noqa: F401
from . import windowKind         # noqa: F401
from . import windowsAndActions  # noqa: F401

__all__ = ['anchors', 'classes', 'findControl', 'labels', 'layers',
           'monitors', 'perProgram', 'procedures', 'schemes', 'shared',
           'toolkit', 'verify', 'virtualInput', 'windowKind',
           'windowsAndActions']
