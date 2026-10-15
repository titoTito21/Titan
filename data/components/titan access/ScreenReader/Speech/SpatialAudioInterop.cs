using System.Runtime.InteropServices;

namespace ScreenReader.Speech;

#region COM Interfaces

/// <summary>
/// ISpatialAudioClient - Windows Spatial Audio API
/// GUID: bbf8e066-aaaa-49be-9a4d-fd2a858ea27f
/// </summary>
[ComImport, Guid("bbf8e066-aaaa-49be-9a4d-fd2a858ea27f")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface ISpatialAudioClient
{
    [PreserveSig]
    int GetStaticObjectPosition(uint objectIndex, out float x, out float y, out float z);

    [PreserveSig]
    int GetNativeStaticObjectTypeMask(out uint mask);

    [PreserveSig]
    int GetMaxDynamicObjectCount(out uint value);

    [PreserveSig]
    int GetSupportedAudioObjectFormatEnumerator([MarshalAs(UnmanagedType.Interface)] out object enumerator);

    [PreserveSig]
    int GetMaxFrameCount([In] ref WaveFormatEx format, out uint frameCountPerBuffer);

    [PreserveSig]
    int IsAudioObjectFormatSupported([In] ref WaveFormatEx format);

    [PreserveSig]
    int ActivateSpatialAudioStream(
        [In] ref SpatialAudioObjectRenderStreamActivationParams activationParams,
        [In] ref Guid riid,
        [MarshalAs(UnmanagedType.Interface)] out object stream);
}

/// <summary>
/// ISpatialAudioObjectRenderStream - Strumień renderowania obiektów przestrzennych
/// GUID: bab8e0e7-38d7-4e17-919a-2f30a8bbf962
/// </summary>
[ComImport, Guid("bab8e0e7-38d7-4e17-919a-2f30a8bbf962")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface ISpatialAudioObjectRenderStream
{
    [PreserveSig]
    int GetAvailableDynamicObjectCount(out uint value);

    [PreserveSig]
    int ActivateSpatialAudioObject(
        uint type,
        [MarshalAs(UnmanagedType.Interface)] out ISpatialAudioObject audioObject);

    [PreserveSig]
    int BeginUpdatingAudioObjects(
        out uint availableDynamicObjectCount,
        out uint frameCountPerBuffer);

    [PreserveSig]
    int EndUpdatingAudioObjects();
}

/// <summary>
/// ISpatialAudioObject - Pojedynczy obiekt dźwiękowy w przestrzeni 3D
/// GUID: dde28967-521b-46e5-8f00-bd6f36691d86
/// </summary>
[ComImport, Guid("dde28967-521b-46e5-8f00-bd6f36691d86")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface ISpatialAudioObject
{
    [PreserveSig]
    int GetBuffer(out IntPtr buffer, out uint bufferLength);

    [PreserveSig]
    int SetEndOfStream(uint frameCount);

    [PreserveSig]
    int IsActive(out bool isActive);

    [PreserveSig]
    int GetAudioObjectType(out uint audioObjectType);

    [PreserveSig]
    int SetPosition(float x, float y, float z);

    [PreserveSig]
    int SetVolume(float volume);
}

#endregion

#region Structures

/// <summary>
/// Parametry aktywacji strumienia renderowania przestrzennego
/// </summary>
[StructLayout(LayoutKind.Sequential)]
public struct SpatialAudioObjectRenderStreamActivationParams
{
    public WaveFormatEx ObjectFormat;
    public uint StaticObjectTypeMask;
    public uint MinDynamicObjectCount;
    public uint MaxDynamicObjectCount;
    public uint Category; // AUDIO_STREAM_CATEGORY
    public IntPtr EventHandle;
    public IntPtr NotifyObject;
}

/// <summary>
/// Format audio WAVEFORMATEX
/// </summary>
[StructLayout(LayoutKind.Sequential)]
public struct WaveFormatEx
{
    public ushort wFormatTag;      // 3 = IEEE Float
    public ushort nChannels;       // 1 = Mono (dla obiektów przestrzennych)
    public uint nSamplesPerSec;    // 48000 Hz (standardowa częstotliwość)
    public uint nAvgBytesPerSec;   // nSamplesPerSec * nBlockAlign
    public ushort nBlockAlign;     // nChannels * wBitsPerSample / 8
    public ushort wBitsPerSample;  // 32 bit (float)
    public ushort cbSize;          // 0 dla podstawowego WAVEFORMATEX
}

/// <summary>
/// IMMDevice - Core Audio Device
/// </summary>
[ComImport, Guid("D666063F-1587-4E43-81F1-B948E807363F")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IMMDevice
{
    [PreserveSig]
    int Activate(
        [In, MarshalAs(UnmanagedType.LPStruct)] Guid iid,
        [In] CLSCTX dwClsCtx,
        [In] IntPtr pActivationParams,
        [Out, MarshalAs(UnmanagedType.IUnknown)] out object ppInterface);

    // Other methods omitted for brevity
}

/// <summary>
/// CLSCTX - Class context for COM activation
/// </summary>
[Flags]
public enum CLSCTX : uint
{
    CLSCTX_INPROC_SERVER = 0x1,
    CLSCTX_INPROC_HANDLER = 0x2,
    CLSCTX_LOCAL_SERVER = 0x4,
    CLSCTX_REMOTE_SERVER = 0x10,
    CLSCTX_ALL = CLSCTX_INPROC_SERVER | CLSCTX_INPROC_HANDLER | CLSCTX_LOCAL_SERVER | CLSCTX_REMOTE_SERVER
}

#endregion

#region P/Invoke & Constants

/// <summary>
/// Funkcje i stałe P/Invoke dla Windows Spatial Audio
/// </summary>
public static class SpatialAudioNative
{
    /// <summary>
    /// Inicjalizacja COM
    /// </summary>
    [DllImport("ole32.dll")]
    public static extern int CoInitializeEx(IntPtr pvReserved, uint dwCoInit);

    /// <summary>
    /// Deinicjalizacja COM
    /// </summary>
    [DllImport("ole32.dll")]
    public static extern void CoUninitialize();

    // Stałe COM
    public const uint COINIT_APARTMENTTHREADED = 0x2;
    public const uint COINIT_MULTITHREADED = 0x0;

    // AUDIO_STREAM_CATEGORY
    public const uint AudioCategory_Other = 0;
    public const uint AudioCategory_ForegroundOnlyMedia = 1;
    public const uint AudioCategory_BackgroundCapableMedia = 2;
    public const uint AudioCategory_Communications = 3;
    public const uint AudioCategory_Alerts = 4;
    public const uint AudioCategory_SoundEffects = 5;
    public const uint AudioCategory_GameEffects = 6;
    public const uint AudioCategory_GameMedia = 7;
    public const uint AudioCategory_GameChat = 8;
    public const uint AudioCategory_Speech = 9;
    public const uint AudioCategory_Movie = 10;
    public const uint AudioCategory_Media = 11;

    // AudioObjectType
    public const uint AudioObjectType_None = 0x00000000;
    public const uint AudioObjectType_Dynamic = 0x00000001;
    public const uint AudioObjectType_FrontLeft = 0x00000002;
    public const uint AudioObjectType_FrontRight = 0x00000004;
    public const uint AudioObjectType_FrontCenter = 0x00000008;

    // HRESULT codes
    public const int S_OK = 0;
    public const int E_INVALIDARG = unchecked((int)0x80070057);
    public const int E_OUTOFMEMORY = unchecked((int)0x8007000E);
}

#endregion
