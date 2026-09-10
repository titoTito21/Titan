# -*- coding: utf-8 -*-
"""The desktop as the compositor sees it - the only way to photograph a game.

**It runs in a process of its own, and that is a decision rather than an
accident.** The Desktop Duplication API is COM, and COM is reference
counting: the frame handed over for an empty update, the staging texture,
the surface mapped from it and the device that owns them all have lifetimes
that have to be exactly right. Getting one wrong here is not a wrong answer
but an access violation inside a deallocator - measured, repeatedly, while
this was being written - and the two programs that would call this are a
screen reader and the desktop a blind user depends on. Neither may be put
at risk of a corrupted heap to take a screenshot.

So the COM lives in a short-lived child process which grabs one frame,
writes it out and exits. If it crashes, it crashes alone; Titan reads a
file or does not. A capture happens once per reading, and the recogniser
skips a screen that has not changed, so a few hundred milliseconds of
process start is paid rarely and buys certainty.

`capture.py` has two routes and neither can see an exclusive full-screen
program. Copying from the desktop (`BitBlt`) reads the window Windows draws
for the desktop, and a game that has taken the display outright is not
drawn there at all: what comes back is a rectangle of black, which is
exactly what `_looks_blank` reports and what the user hears as "the capture
came back empty". Asking the window to render itself (`PrintWindow`) fails
for the same reason from the other side: the game does not draw with GDI,
so there is nothing for the call to draw.

**The answer is the Desktop Duplication API**, which is what Windows'
own screen recorders, remote desktops and game bars use: the compositor
hands over the frame it has just composed, whatever produced it and
however full-screen it is. It costs no polling and no window - a frame is
asked for and either arrives or does not.

Written with `comtypes`, which Titan already depends on (`pycaw` uses it),
so this adds nothing to install and nothing to the packaged build but one
module.

Two things about it are worth knowing before changing any of it:

* **The vtable order IS the interface.** Every method of every interface
  above the one being called has to be declared, in order, or the call
  goes to the wrong function pointer - which is not an exception, it is
  whatever happens next. The methods that are never called are declared
  with the arguments they really take for that reason and no other.
* **A frame must be released.** `AcquireNextFrame` holds the desktop until
  `ReleaseFrame`, and a frame left held stops the compositor handing out
  another - to this process or to anything else on the machine. Every path
  out of here releases, including the ones that fail.
"""

import ctypes
from ctypes import wintypes

try:
    import comtypes
    from comtypes import GUID, COMMETHOD, HRESULT, IUnknown
except Exception:                                    # pragma: no cover
    comtypes = None
    IUnknown = object

#: How long to wait for the compositor to compose a frame. A screen that is
#: not changing produces none at all, which is not a failure: it means what
#: was there last is still there, and the caller already has that picture.
FRAME_WAIT_MS = 300

#: Given up on after this. The desktop moves under a full-screen game, so
#: one of these is nearly always enough; the loop is for the case where the
#: first answer is the mouse cursor moving and nothing else.
FRAME_TRIES = 4

_DXGI_ERROR_WAIT_TIMEOUT = -2005270902      # 0x887A0027
_DXGI_ERROR_ACCESS_LOST = -2005270895       # 0x887A0026
_DXGI_ERROR_UNSUPPORTED = -2005270524       # 0x887A0004


if comtypes is not None:

    # **Every pointer that crosses this boundary is a comtypes interface
    # pointer, never a `c_void_p` that is cast afterwards.** Casting a raw
    # pointer to `POINTER(IUnknown)` makes comtypes believe it owns a
    # reference it never took, and the Release that follows when the
    # temporary is collected decrements somebody else's - which arrives as
    # an access violation inside a deallocator, a long way from the cast.
    # Declaring the real types is also what makes the reference counting
    # correct without a single AddRef being written here.

    class _DXGI_OUTPUT_DESC(ctypes.Structure):
        _fields_ = [('DeviceName', wintypes.WCHAR * 32),
                    ('DesktopCoordinates', wintypes.RECT),
                    ('AttachedToDesktop', wintypes.BOOL),
                    ('Rotation', ctypes.c_uint),
                    ('Monitor', ctypes.c_void_p)]

    class _DXGI_MODE_DESC(ctypes.Structure):
        # 28 bytes. Written out rather than reserved as a block, because
        # getting its SIZE wrong moves every field after it - and the one
        # after it decides which of the two routes below is taken.
        _fields_ = [('Width', ctypes.c_uint), ('Height', ctypes.c_uint),
                    ('RefreshRateNumerator', ctypes.c_uint),
                    ('RefreshRateDenominator', ctypes.c_uint),
                    ('Format', ctypes.c_uint),
                    ('ScanlineOrdering', ctypes.c_uint),
                    ('Scaling', ctypes.c_uint)]

    class _DXGI_OUTDUPL_DESC(ctypes.Structure):
        _fields_ = [('ModeDesc', _DXGI_MODE_DESC),
                    ('Rotation', ctypes.c_uint),
                    ('DesktopImageInSystemMemory', wintypes.BOOL)]

    class _DXGI_OUTDUPL_FRAME_INFO(ctypes.Structure):
        _fields_ = [('LastPresentTime', ctypes.c_longlong),
                    ('LastMouseUpdateTime', ctypes.c_longlong),
                    ('AccumulatedFrames', ctypes.c_uint),
                    ('RectsCoalesced', wintypes.BOOL),
                    ('ProtectedContentMaskedOut', wintypes.BOOL),
                    ('PointerPositionX', ctypes.c_long),
                    ('PointerPositionY', ctypes.c_long),
                    ('PointerVisible', wintypes.BOOL),
                    ('TotalMetadataBufferSize', ctypes.c_uint),
                    ('PointerShapeBufferSize', ctypes.c_uint)]

    class _DXGI_MAPPED_RECT(ctypes.Structure):
        _fields_ = [('Pitch', ctypes.c_int),
                    ('pBits', ctypes.POINTER(ctypes.c_ubyte))]

    class _D3D11_TEXTURE2D_DESC(ctypes.Structure):
        _fields_ = [('Width', ctypes.c_uint), ('Height', ctypes.c_uint),
                    ('MipLevels', ctypes.c_uint),
                    ('ArraySize', ctypes.c_uint),
                    ('Format', ctypes.c_uint),
                    ('SampleDescCount', ctypes.c_uint),
                    ('SampleDescQuality', ctypes.c_uint),
                    ('Usage', ctypes.c_uint),
                    ('BindFlags', ctypes.c_uint),
                    ('CPUAccessFlags', ctypes.c_uint),
                    ('MiscFlags', ctypes.c_uint)]

    _OBJECT_METHODS = [
        COMMETHOD([], HRESULT, 'SetPrivateData',
                  (['in'], ctypes.POINTER(GUID), 'Name'),
                  (['in'], ctypes.c_uint, 'DataSize'),
                  (['in'], ctypes.c_void_p, 'pData')),
        COMMETHOD([], HRESULT, 'SetPrivateDataInterface',
                  (['in'], ctypes.POINTER(GUID), 'Name'),
                  (['in'], ctypes.POINTER(IUnknown), 'pUnknown')),
        COMMETHOD([], HRESULT, 'GetPrivateData',
                  (['in'], ctypes.POINTER(GUID), 'Name'),
                  (['in'], ctypes.POINTER(ctypes.c_uint), 'pDataSize'),
                  (['in'], ctypes.c_void_p, 'pData')),
        COMMETHOD([], HRESULT, 'GetParent',
                  (['in'], ctypes.POINTER(GUID), 'riid'),
                  (['out'], ctypes.POINTER(ctypes.c_void_p), 'ppParent')),
    ]

    class IDXGIObject(IUnknown):
        _iid_ = GUID('{aec22fb8-76f3-4639-9be0-28eb43a67a2e}')
        _methods_ = _OBJECT_METHODS

    class IDXGIOutputDuplication(IDXGIObject):
        _iid_ = GUID('{191cfac3-a341-470d-b26e-a864f428319c}')
        _methods_ = [
            COMMETHOD([], None, 'GetDesc',
                      (['out'], ctypes.POINTER(_DXGI_OUTDUPL_DESC), 'pDesc')),
            COMMETHOD([], HRESULT, 'AcquireNextFrame',
                      (['in'], ctypes.c_uint, 'TimeoutInMilliseconds'),
                      (['out'], ctypes.POINTER(_DXGI_OUTDUPL_FRAME_INFO),
                       'pFrameInfo'),
                      (['out'], ctypes.POINTER(ctypes.POINTER(IUnknown)),
                       'ppDesktopResource')),
            COMMETHOD([], HRESULT, 'GetFrameDirtyRects',
                      (['in'], ctypes.c_uint, 'DirtyRectsBufferSize'),
                      (['in'], ctypes.c_void_p, 'pDirtyRectsBuffer'),
                      (['in'], ctypes.POINTER(ctypes.c_uint), 'pRequired')),
            COMMETHOD([], HRESULT, 'GetFrameMoveRects',
                      (['in'], ctypes.c_uint, 'MoveRectsBufferSize'),
                      (['in'], ctypes.c_void_p, 'pMoveRectBuffer'),
                      (['in'], ctypes.POINTER(ctypes.c_uint), 'pRequired')),
            COMMETHOD([], HRESULT, 'GetFramePointerShape',
                      (['in'], ctypes.c_uint, 'PointerShapeBufferSize'),
                      (['in'], ctypes.c_void_p, 'pPointerShapeBuffer'),
                      (['in'], ctypes.POINTER(ctypes.c_uint), 'pRequired'),
                      (['in'], ctypes.c_void_p, 'pPointerShapeInfo')),
            COMMETHOD([], HRESULT, 'MapDesktopSurface',
                      (['out'], ctypes.POINTER(_DXGI_MAPPED_RECT),
                       'pLockedRect')),
            COMMETHOD([], HRESULT, 'UnMapDesktopSurface'),
            COMMETHOD([], HRESULT, 'ReleaseFrame'),
        ]

    class IDXGIOutput(IDXGIObject):
        _iid_ = GUID('{ae02eedb-c735-4690-8d52-5a8dc20213aa}')
        _methods_ = [
            COMMETHOD([], HRESULT, 'GetDesc',
                      (['out'], ctypes.POINTER(_DXGI_OUTPUT_DESC), 'pDesc')),
            COMMETHOD([], HRESULT, 'GetDisplayModeList',
                      (['in'], ctypes.c_uint, 'EnumFormat'),
                      (['in'], ctypes.c_uint, 'Flags'),
                      (['in'], ctypes.POINTER(ctypes.c_uint), 'pNumModes'),
                      (['in'], ctypes.c_void_p, 'pDesc')),
            COMMETHOD([], HRESULT, 'FindClosestMatchingMode',
                      (['in'], ctypes.c_void_p, 'pModeToMatch'),
                      (['in'], ctypes.c_void_p, 'pClosestMatch'),
                      (['in'], ctypes.POINTER(IUnknown), 'pConcernedDevice')),
            COMMETHOD([], HRESULT, 'WaitForVBlank'),
            COMMETHOD([], HRESULT, 'TakeOwnership',
                      (['in'], ctypes.POINTER(IUnknown), 'pDevice'),
                      (['in'], wintypes.BOOL, 'Exclusive')),
            COMMETHOD([], None, 'ReleaseOwnership'),
            COMMETHOD([], HRESULT, 'GetGammaControlCapabilities',
                      (['in'], ctypes.c_void_p, 'pGammaCaps')),
            COMMETHOD([], HRESULT, 'SetGammaControl',
                      (['in'], ctypes.c_void_p, 'pArray')),
            COMMETHOD([], HRESULT, 'GetGammaControl',
                      (['in'], ctypes.c_void_p, 'pArray')),
            COMMETHOD([], HRESULT, 'SetDisplaySurface',
                      (['in'], ctypes.POINTER(IUnknown), 'pScanoutSurface')),
            COMMETHOD([], HRESULT, 'GetDisplaySurfaceData',
                      (['in'], ctypes.POINTER(IUnknown), 'pDestination')),
            COMMETHOD([], HRESULT, 'GetFrameStatistics',
                      (['in'], ctypes.c_void_p, 'pStats')),
        ]

    class IDXGIOutput1(IDXGIOutput):
        _iid_ = GUID('{00cddea8-939b-4b83-a340-a685226666cc}')
        _methods_ = [
            COMMETHOD([], HRESULT, 'GetDisplayModeList1',
                      (['in'], ctypes.c_uint, 'EnumFormat'),
                      (['in'], ctypes.c_uint, 'Flags'),
                      (['in'], ctypes.POINTER(ctypes.c_uint), 'pNumModes'),
                      (['in'], ctypes.c_void_p, 'pDesc')),
            COMMETHOD([], HRESULT, 'FindClosestMatchingMode1',
                      (['in'], ctypes.c_void_p, 'pModeToMatch'),
                      (['in'], ctypes.c_void_p, 'pClosestMatch'),
                      (['in'], ctypes.POINTER(IUnknown), 'pConcernedDevice')),
            COMMETHOD([], HRESULT, 'GetDisplaySurfaceData1',
                      (['in'], ctypes.POINTER(IUnknown), 'pDestination')),
            COMMETHOD([], HRESULT, 'DuplicateOutput',
                      (['in'], ctypes.POINTER(IUnknown), 'pDevice'),
                      (['out'],
                       ctypes.POINTER(ctypes.POINTER(IDXGIOutputDuplication)),
                       'ppOutputDuplication')),
        ]

    class IDXGIAdapter(IDXGIObject):
        _iid_ = GUID('{2411e7e1-12ac-4ccf-bd14-9798e8534dc9}')
        _methods_ = [
            COMMETHOD([], HRESULT, 'EnumOutputs',
                      (['in'], ctypes.c_uint, 'Output'),
                      (['out'], ctypes.POINTER(ctypes.POINTER(IDXGIOutput)),
                       'ppOutput')),
            COMMETHOD([], HRESULT, 'GetDesc',
                      (['in'], ctypes.c_void_p, 'pDesc')),
            COMMETHOD([], HRESULT, 'CheckInterfaceSupport',
                      (['in'], ctypes.POINTER(GUID), 'InterfaceName'),
                      (['in'], ctypes.c_void_p, 'pUMDVersion')),
        ]

    class IDXGIDevice(IDXGIObject):
        _iid_ = GUID('{54ec77fa-1377-44e6-8c32-88fd5f44c84c}')
        _methods_ = [
            COMMETHOD([], HRESULT, 'GetAdapter',
                      (['out'], ctypes.POINTER(ctypes.POINTER(IDXGIAdapter)),
                       'pAdapter')),
            COMMETHOD([], HRESULT, 'CreateSurface',
                      (['in'], ctypes.c_void_p, 'pDesc'),
                      (['in'], ctypes.c_uint, 'NumSurfaces'),
                      (['in'], ctypes.c_uint, 'Usage'),
                      (['in'], ctypes.c_void_p, 'pSharedResource'),
                      (['out'], ctypes.POINTER(ctypes.c_void_p),
                       'ppSurface')),
            COMMETHOD([], HRESULT, 'QueryResourceResidency',
                      (['in'], ctypes.c_void_p, 'ppResources'),
                      (['in'], ctypes.c_void_p, 'pResidencyStatus'),
                      (['in'], ctypes.c_uint, 'NumResources')),
            COMMETHOD([], HRESULT, 'SetGPUThreadPriority',
                      (['in'], ctypes.c_int, 'Priority')),
            COMMETHOD([], HRESULT, 'GetGPUThreadPriority',
                      (['in'], ctypes.c_void_p, 'pPriority')),
        ]

    class IDXGISurface(IDXGIObject):
        _iid_ = GUID('{cafcb56c-6ac3-4889-bf47-9e23bbd260ec}')
        _methods_ = [
            COMMETHOD([], HRESULT, 'GetDevice',
                      (['in'], ctypes.POINTER(GUID), 'riid'),
                      (['out'], ctypes.POINTER(ctypes.c_void_p), 'ppDevice')),
            COMMETHOD([], HRESULT, 'GetDesc',
                      (['in'], ctypes.c_void_p, 'pDesc')),
            COMMETHOD([], HRESULT, 'Map',
                      (['out'], ctypes.POINTER(_DXGI_MAPPED_RECT),
                       'pLockedRect'),
                      (['in'], ctypes.c_uint, 'MapFlags')),
            COMMETHOD([], HRESULT, 'Unmap'),
        ]

    class ID3D11Texture2D(IUnknown):
        #: Only ever passed, never called - but it has to be ASKED for.
        #: `AcquireNextFrame` hands over an `IDXGIResource`, and
        #: `CopyResource` takes an `ID3D11Resource`: two interfaces on one
        #: object. Handing the DXGI one straight to D3D copies nothing at
        #: all and reports success, which arrives as a frame of pure black
        #: - the exact thing this whole module exists to stop being.
        _iid_ = GUID('{6f15aaf2-d208-4e89-9ab4-489535d34f9c}')
        _methods_ = []

    class ID3D11Device(IUnknown):
        _iid_ = GUID('{db6f6ddb-ac77-4e88-8253-819df9bbf140}')
        _methods_ = [
            COMMETHOD([], HRESULT, 'CreateBuffer',
                      (['in'], ctypes.c_void_p, 'pDesc'),
                      (['in'], ctypes.c_void_p, 'pInitialData'),
                      (['out'], ctypes.POINTER(ctypes.c_void_p), 'ppBuffer')),
            COMMETHOD([], HRESULT, 'CreateTexture1D',
                      (['in'], ctypes.c_void_p, 'pDesc'),
                      (['in'], ctypes.c_void_p, 'pInitialData'),
                      (['out'], ctypes.POINTER(ctypes.c_void_p), 'ppTex1D')),
            COMMETHOD([], HRESULT, 'CreateTexture2D',
                      (['in'], ctypes.POINTER(_D3D11_TEXTURE2D_DESC),
                       'pDesc'),
                      (['in'], ctypes.c_void_p, 'pInitialData'),
                      (['out'], ctypes.POINTER(ctypes.POINTER(IUnknown)),
                       'ppTexture2D')),
        ]

    #: `CopyResource` is the forty-first method of `ID3D11DeviceContext`,
    #: and a COM interface IS its vtable order - so the forty before it
    #: must occupy their slots or the call lands somewhere else entirely.
    #: They are empty slots on purpose: nothing here calls them, and forty
    #: real signatures would be forty more chances to get one wrong.
    _CONTEXT_METHODS = [
        COMMETHOD([], None, 'GetDevice',
                  (['out'], ctypes.POINTER(ctypes.c_void_p), 'ppDevice')),
        COMMETHOD([], HRESULT, 'GetPrivateData',
                  (['in'], ctypes.POINTER(GUID), 'guid'),
                  (['in'], ctypes.POINTER(ctypes.c_uint), 'pDataSize'),
                  (['in'], ctypes.c_void_p, 'pData')),
        COMMETHOD([], HRESULT, 'SetPrivateData',
                  (['in'], ctypes.POINTER(GUID), 'guid'),
                  (['in'], ctypes.c_uint, 'DataSize'),
                  (['in'], ctypes.c_void_p, 'pData')),
        COMMETHOD([], HRESULT, 'SetPrivateDataInterface',
                  (['in'], ctypes.POINTER(GUID), 'guid'),
                  (['in'], ctypes.POINTER(IUnknown), 'pData')),
    ] + [COMMETHOD([], None, '_slot%02d' % index) for index in range(40)] + [
        COMMETHOD([], None, 'CopyResource',
                  (['in'], ctypes.POINTER(IUnknown), 'pDstResource'),
                  (['in'], ctypes.POINTER(IUnknown), 'pSrcResource')),
    ]

    class ID3D11DeviceContext(IUnknown):
        _iid_ = GUID('{c0bfa96c-e089-44fb-8eaf-26f8796190da}')
        _methods_ = _CONTEXT_METHODS


_staging = {'surface': None, 'texture': None}


def _through_a_staging_texture(device, context, resource, width, height):
    """Copy the frame off the graphics card and map it. ``(pitch, bits)``.

    The ordinary case: a desktop composed on the GPU cannot be read by the
    processor where it lies, so a texture the processor IS allowed to read
    is made, the frame is copied into it by the card, and that is mapped.
    The copy costs a fraction of a millisecond; what would be slow is doing
    it a pixel at a time here.
    """
    described = _D3D11_TEXTURE2D_DESC()
    described.Width = width
    described.Height = height
    described.MipLevels = 1
    described.ArraySize = 1
    described.Format = 87                    # DXGI_FORMAT_B8G8R8A8_UNORM
    described.SampleDescCount = 1
    described.SampleDescQuality = 0
    described.Usage = 3                      # D3D11_USAGE_STAGING
    described.BindFlags = 0
    described.CPUAccessFlags = 0x20000       # D3D11_CPU_ACCESS_READ
    described.MiscFlags = 0
    texture = device.CreateTexture2D(ctypes.byref(described), None)
    if not texture:
        return 0, None
    _staging['texture'] = texture
    # The frame as D3D sees it, not as DXGI handed it over.
    source = resource.QueryInterface(ID3D11Texture2D)
    context.CopyResource(texture, source)
    surface = texture.QueryInterface(IDXGISurface)
    _staging['surface'] = surface
    mapped = surface.Map(1)                  # DXGI_MAP_READ
    return int(mapped.Pitch), mapped.pBits


def _release_staging():
    surface = _staging.get('surface')
    if surface is not None:
        try:
            surface.Unmap()
        except Exception:                            # noqa: BLE001
            pass
    _staging['surface'] = None
    _staging['texture'] = None


_state = {'why': '', 'frames': 0}


def report():
    return dict(_state)


def available():
    """``(yes, why not)`` - whether a frame can be asked for at all."""
    if comtypes is None:
        return False, 'comtypes is not available'
    try:
        ctypes.windll.d3d11
    except Exception as error:                       # noqa: BLE001
        return False, 'Direct3D 11 is not available: %s' % error
    return True, ''


def _device():
    """A Direct3D 11 device and its context, as comtypes pointers.

    Asked for AS the interfaces, so comtypes owns the references from the
    first moment - a raw `c_void_p` cast to an interface later is a
    reference nobody took and everybody releases.
    """
    d3d11 = ctypes.windll.d3d11
    level = ctypes.c_uint()
    # Hardware first, then WARP - a software renderer, which is here
    # because the duplication does not need the card to DRAW anything: it
    # needs a device to own the duplication, and a machine whose display
    # driver refuses one should still be able to read its own screen.
    for driver in (1, 5):
        device = ctypes.POINTER(ID3D11Device)()
        context = ctypes.POINTER(ID3D11DeviceContext)()
        result = d3d11.D3D11CreateDevice(
            None, driver, None, 0, None, 0, 7,
            ctypes.byref(device), ctypes.byref(level), ctypes.byref(context))
        if result >= 0 and device:
            return device, context
    return None, None


def _duplication(device):
    """The duplication for the monitor the desktop starts on.

    **The device is asked for its DXGI face, never cast to it.** An
    `ID3D11Device` is not an `IDXGIDevice`; they are two interfaces on one
    object with entirely different vtables, so casting one to the other
    and calling `GetAdapter` jumps to whatever function pointer happens to
    sit at that slot. Here that was an access violation at 0x10 - a wild
    call, not a wrong answer, which is what a cast between unrelated COM
    interfaces always is.
    """
    unknown = ctypes.cast(device, ctypes.POINTER(IUnknown))
    dxgi_device = unknown.QueryInterface(IDXGIDevice)
    adapter_pointer = dxgi_device.GetAdapter()
    adapter = ctypes.cast(adapter_pointer, ctypes.POINTER(IDXGIAdapter))
    output_pointer = adapter.EnumOutputs(0)
    output = ctypes.cast(output_pointer, ctypes.POINTER(IDXGIOutput))
    output1 = output.QueryInterface(IDXGIOutput1)
    desc = output.GetDesc()
    where = desc.DesktopCoordinates
    duplication = ctypes.cast(
        output1.DuplicateOutput(ctypes.cast(device,
                                            ctypes.POINTER(IUnknown))),
        ctypes.POINTER(IDXGIOutputDuplication))
    return duplication, (int(where.left), int(where.top),
                         int(where.right - where.left),
                         int(where.bottom - where.top))


def grab():
    """The desktop as the compositor last composed it.

    ``(rgb, (left, top), (width, height))`` or ``(None, reason, None)``.
    Includes whatever a full-screen program is drawing, which is the whole
    reason this exists.
    """
    ready, why = available()
    if not ready:
        _state['why'] = why
        return None, why, None
    import numpy

    device = context = duplication = None
    try:
        device, context = _device()
        if device is None:
            _state['why'] = 'Direct3D would not make a device'
            return None, _state['why'], None
        duplication, (left, top, width, height) = _duplication(device)
        described = duplication.GetDesc()
        # **Where the frame lives decides how it is read.** Some displays
        # hand the desktop over in system memory, where it can simply be
        # mapped; most hand it over on the graphics card, where it has to
        # be copied into a staging texture the processor is allowed to
        # read. Measured on this machine: the second.
        in_memory = bool(described.DesktopImageInSystemMemory)
        mapped_here = False
        for _try in range(FRAME_TRIES):
            try:
                info, resource = duplication.AcquireNextFrame(FRAME_WAIT_MS)
            except Exception as error:               # noqa: BLE001
                code = getattr(error, 'hresult', 0)
                if code == _DXGI_ERROR_WAIT_TIMEOUT:
                    continue
                _state['why'] = 'the desktop was not handed over: %s' % error
                return None, _state['why'], None
            try:
                # **A frame is not a picture until something has been
                # drawn into it.** The first `AcquireNextFrame` after a
                # duplication is made comes back with `AccumulatedFrames`
                # of zero - a frame carrying no desktop update at all,
                # whose contents are undefined and which arrives as pure
                # black. Measured here: acquire 0 accumulated=0 and every
                # pixel 0; acquire 1 accumulated=8 and a real desktop.
                # Reading the first one is the difference between this
                # module working and returning a black rectangle that
                # `_looks_blank` then reports as "the capture came back
                # empty" - the very message it was written to end.
                if not info.AccumulatedFrames and not info.LastPresentTime:
                    continue
                if in_memory:
                    mapped = duplication.MapDesktopSurface()
                    mapped_here = True
                    pitch, bits = int(mapped.Pitch), mapped.pBits
                else:
                    mapped_here = False
                    pitch, bits = _through_a_staging_texture(
                        device, context, resource, width, height)
                if not bits or pitch <= 0:
                    continue
                raw = ctypes.string_at(bits, pitch * height)
                whole = numpy.frombuffer(raw, dtype=numpy.uint8)
                whole = whole.reshape(height, pitch // 4, 4)[:, :width, :]
                rgb = whole[:, :, [2, 1, 0]].copy()   # BGRA -> RGB
                _state['frames'] += 1
                _state['why'] = ''
                return rgb, (left, top), (width, height)
            finally:
                if in_memory:
                    try:
                        duplication.UnMapDesktopSurface()
                    except Exception:                # noqa: BLE001
                        pass
                _release_staging()
                # **The frame goes back BEFORE the pointer is dropped.**
                # Releasing the interface first and only then telling DXGI
                # the frame is finished with is an access violation inside
                # a deallocator - measured, and always on the frames that
                # carry no desktop update. Held, a frame also stops the
                # compositor handing out another to anything on the
                # machine, so this happens on every path out.
                try:
                    duplication.ReleaseFrame()
                except Exception:                    # noqa: BLE001
                    pass
                resource = None
        _state['why'] = 'the screen did not change, so no frame was composed'
        return None, _state['why'], None
    except Exception as error:                       # noqa: BLE001
        _state['why'] = '%s: %s' % (type(error).__name__, error)
        return None, _state['why'], None
    finally:
        duplication = None
        context = None
        device = None


# --------------------------------------------------------------------------- #
# The safe way to call all of the above: from somewhere else
# --------------------------------------------------------------------------- #
#: How long the child is given. It has to start Python, create a Direct3D
#: device and wait for the compositor to compose a frame; a screen that is
#: busy answers in well under a second.
CHILD_SECONDS = 12.0

#: The header the child writes in front of the pixels, so the parent knows
#: what it is reading without a second file or a serialisation library.
_HEADER = 'TITANFRAME %d %d %d %d\n'


def write_frame(path):
    """Grab one frame and write it to ``path``. Returns an exit code.

    The child's whole job. Deliberately dull: a header line of plain text
    and then the rows, so the parent needs nothing but `open`.
    """
    rgb, where, size = grab()
    if rgb is None:
        try:
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write('TITANFRAME-FAILED %s\n' % (where or 'unknown'))
        except Exception:                            # noqa: BLE001
            pass
        return 1
    try:
        with open(path, 'wb') as handle:
            handle.write((_HEADER % (size[0], size[1], where[0], where[1]))
                         .encode('ascii'))
            handle.write(rgb.tobytes())
    except Exception:                                # noqa: BLE001
        return 1
    return 0


def read_frame(path):
    """The parent's half. ``(rgb, (left, top), (width, height))``."""
    import numpy
    with open(path, 'rb') as handle:
        first = handle.readline().decode('ascii', 'replace').strip()
        if not first.startswith('TITANFRAME '):
            return None, first.replace('TITANFRAME-FAILED ', ''), None
        _mark, width, height, left, top = first.split()
        width, height = int(width), int(height)
        raw = handle.read()
    wanted = width * height * 3
    if len(raw) < wanted:
        return None, 'the frame was written short', None
    rgb = numpy.frombuffer(raw[:wanted], dtype=numpy.uint8)
    return (rgb.reshape(height, width, 3), (int(left), int(top)),
            (width, height))


def _child_command(path):
    """How to start the child, from source and from a packaged Titan."""
    import sys
    if getattr(sys, 'frozen', False):
        # A packaged Titan is its own interpreter, so it re-runs itself
        # with a flag `main.py` answers before anything else starts.
        return [sys.executable, '--capture-frame', path]
    return [sys.executable, '-m', 'src.ai.ocr.duplication', path]


def grab_elsewhere():
    """One frame, grabbed in a child process. Same answer as :func:`grab`.

    Never raises, and never leaves the file behind.
    """
    import os
    import subprocess
    import sys
    import tempfile
    ready, why = available()
    if not ready:
        return None, why, None
    handle, path = tempfile.mkstemp(prefix='titan-frame-', suffix='.raw')
    os.close(handle)
    try:
        try:
            done = subprocess.run(
                _child_command(path), timeout=CHILD_SECONDS,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                cwd=_root())
        except subprocess.TimeoutExpired:
            return None, 'the screen grab took too long', None
        except Exception as error:                   # noqa: BLE001
            return None, 'the screen grab would not start: %s' % error, None
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            said = (done.stderr or b'').decode('utf-8', 'replace').strip()
            return None, said.splitlines()[-1] if said else \
                'the screen grab produced nothing', None
        return read_frame(path)
    except Exception as error:                       # noqa: BLE001
        return None, '%s: %s' % (type(error).__name__, error), None
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _root():
    import os
    return os.path.abspath(os.path.join(os.path.dirname(__file__),
                                        '..', '..', '..'))


if __name__ == '__main__':                           # pragma: no cover
    import sys
    sys.exit(write_frame(sys.argv[1]) if len(sys.argv) > 1 else 2)
