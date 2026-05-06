/*
 * BeSTspeech 32-bit Bridge with Audio Capture
 * =============================================
 * Compiled as x86 (32-bit) to load 32-bit BeSTspeech DLLs.
 * Uses IAT hooking on waveOut functions to capture audio data
 * instead of playing it, enabling stereo positioning and pitch control.
 *
 * Compile:
 *   C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe /platform:x86 /optimize /nologo /out:bst_bridge.exe bst_bridge.cs
 *
 * Protocol (JSON lines over stdin/stdout):
 *   -> {"cmd":"init","dll":"C:\\path\\dll_eng.dll"}
 *   <- {"ok":true}
 *
 *   -> {"cmd":"say","text":"Hello world"}
 *   <- {"ok":true,"wav":"C:\\...\\tmp1234.wav"}
 *
 *   -> {"cmd":"switch","dll":"C:\\path\\dll_pol.dll"}
 *   <- {"ok":true}
 *
 *   -> {"cmd":"quit"}
 *   (process exits)
 */

using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;

class BSTBridge
{
    // ======================== P/Invoke ========================

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern IntPtr LoadLibraryW(string lpFileName);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    static extern bool FreeLibrary(IntPtr hModule);

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Ansi)]
    static extern IntPtr GetProcAddress(IntPtr hModule, string lpProcName);

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool VirtualProtect(IntPtr lpAddress, uint dwSize, uint flNewProtect, out uint lpflOldProtect);

    [DllImport("kernel32.dll")]
    static extern void SetEvent(IntPtr hEvent);

    [DllImport("user32.dll")]
    static extern bool PostMessageW(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);

    [DllImport("kernel32.dll")]
    static extern bool PostThreadMessage(uint idThread, uint Msg, IntPtr wParam, IntPtr lParam);

    const uint PAGE_READWRITE = 0x04;

    // ======================== BST DLL Delegates ========================

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    delegate void InitTTSDelegate();

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    delegate void SayTTSDelegate([MarshalAs(UnmanagedType.LPWStr)] string text);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    delegate void DeInitTTSDelegate();

    // ======================== waveOut Delegates ========================

    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    delegate uint WaveOutOpenDel(IntPtr lphWaveOut, uint uDeviceID, IntPtr lpFormat,
                                 IntPtr dwCallback, IntPtr dwInstance, uint fdwOpen);

    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    delegate uint WaveOutPrepHdrDel(IntPtr hwo, IntPtr pwh, uint cbwh);

    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    delegate uint WaveOutWriteDel(IntPtr hwo, IntPtr pwh, uint cbwh);

    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    delegate uint WaveOutUnprepHdrDel(IntPtr hwo, IntPtr pwh, uint cbwh);

    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    delegate uint WaveOutResetDel(IntPtr hwo);

    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    delegate uint WaveOutCloseDel(IntPtr hwo);

    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    delegate void WaveOutProcDel(IntPtr hwo, uint uMsg, IntPtr dwInst, IntPtr p1, IntPtr p2);

    // Sleep delegate (for KERNEL32.dll hook)
    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    delegate void SleepDel(uint dwMilliseconds);

    // ======================== State ========================

    static IntPtr _hModule = IntPtr.Zero;
    static InitTTSDelegate _initTTS;
    static SayTTSDelegate _sayTTS;
    static DeInitTTSDelegate _deInitTTS;

    // Original function delegates (for pass-through)
    static WaveOutOpenDel _realWaveOutOpen;
    static WaveOutPrepHdrDel _realWaveOutPrepHdr;
    static WaveOutWriteDel _realWaveOutWrite;
    static WaveOutUnprepHdrDel _realWaveOutUnprepHdr;
    static WaveOutResetDel _realWaveOutReset;
    static WaveOutCloseDel _realWaveOutClose;
    static SleepDel _realSleep;

    // Hook delegates (prevent GC)
    static WaveOutOpenDel _hookOpenDel;
    static WaveOutPrepHdrDel _hookPrepDel;
    static WaveOutWriteDel _hookWriteDel;
    static WaveOutUnprepHdrDel _hookUnprepDel;
    static WaveOutResetDel _hookResetDel;
    static WaveOutCloseDel _hookCloseDel;
    static SleepDel _hookSleepDel;
    static List<GCHandle> _gcHandles = new List<GCHandle>();

    // Capture state
    static bool _capturing = false;
    static MemoryStream _captureStream;
    static ushort _captureChannels;
    static uint _captureSampleRate;
    static ushort _captureBitsPerSample;
    static ushort _captureBlockAlign;

    // waveOut callback info (from waveOutOpen)
    static IntPtr _fakeHandle = new IntPtr(0xBE57);
    static uint _cbType;
    static IntPtr _cbAddr;
    static IntPtr _cbInst;

    // WAVEHDR offsets (32-bit)
    const int OFF_lpData = 0;
    const int OFF_dwBufLen = 4;
    const int OFF_dwFlags = 16;
    const uint WHDR_DONE = 0x01;
    const uint WHDR_PREPARED = 0x02;

    // Callback type masks
    const uint CALLBACK_TYPEMASK = 0x00070000;
    const uint CALLBACK_NULL = 0x00000000;
    const uint CALLBACK_WINDOW = 0x00010000;
    const uint CALLBACK_THREAD = 0x00020000;
    const uint CALLBACK_FUNCTION = 0x00030000;
    const uint CALLBACK_EVENT = 0x00050000;
    const uint WOM_OPEN = 0x3BB;
    const uint WOM_CLOSE = 0x3BC;
    const uint WOM_DONE = 0x3BD;

    // Hooks installed flag
    static bool _hooksInstalled = false;

    // IAT original values (for restore)
    struct IATPatch { public IntPtr Addr; public IntPtr Orig; }
    static List<IATPatch> _patches = new List<IATPatch>();

    // ======================== Hook Implementations ========================

    static uint HookWaveOutOpen(IntPtr lphWaveOut, uint uDeviceID, IntPtr lpFormat,
                                IntPtr dwCallback, IntPtr dwInstance, uint fdwOpen)
    {
        if (_capturing)
        {
            // Read WAVEFORMATEX from lpFormat
            _captureChannels = (ushort)Marshal.ReadInt16(lpFormat, 2);
            _captureSampleRate = (uint)Marshal.ReadInt32(lpFormat, 4);
            _captureBitsPerSample = (ushort)Marshal.ReadInt16(lpFormat, 14);
            _captureBlockAlign = (ushort)Marshal.ReadInt16(lpFormat, 12);

            // Save callback info
            _cbType = fdwOpen & CALLBACK_TYPEMASK;
            _cbAddr = dwCallback;
            _cbInst = dwInstance;

            // Return fake handle
            Marshal.WriteIntPtr(lphWaveOut, _fakeHandle);

            // Fire WOM_OPEN callback
            FireCallback(WOM_OPEN, IntPtr.Zero);
            return 0;
        }
        return _realWaveOutOpen(lphWaveOut, uDeviceID, lpFormat, dwCallback, dwInstance, fdwOpen);
    }

    static uint HookWaveOutPrepHdr(IntPtr hwo, IntPtr pwh, uint cbwh)
    {
        if (_capturing && hwo == _fakeHandle)
        {
            // Set WHDR_PREPARED flag
            uint flags = (uint)Marshal.ReadInt32(pwh, OFF_dwFlags);
            flags |= WHDR_PREPARED;
            Marshal.WriteInt32(pwh, OFF_dwFlags, (int)flags);
            return 0;
        }
        return _realWaveOutPrepHdr(hwo, pwh, cbwh);
    }

    static uint HookWaveOutWrite(IntPtr hwo, IntPtr pwh, uint cbwh)
    {
        if (_capturing && hwo == _fakeHandle)
        {
            // Read audio data from WAVEHDR
            IntPtr lpData = Marshal.ReadIntPtr(pwh, OFF_lpData);
            int bufLen = Marshal.ReadInt32(pwh, OFF_dwBufLen);

            if (bufLen > 0 && lpData != IntPtr.Zero)
            {
                byte[] buf = new byte[bufLen];
                Marshal.Copy(lpData, buf, 0, bufLen);
                _captureStream.Write(buf, 0, bufLen);
            }

            // Mark buffer as done
            uint flags = (uint)Marshal.ReadInt32(pwh, OFF_dwFlags);
            flags |= WHDR_DONE;
            flags &= ~(uint)0x10; // clear WHDR_INQUEUE
            Marshal.WriteInt32(pwh, OFF_dwFlags, (int)flags);

            // Fire WOM_DONE callback
            FireCallback(WOM_DONE, pwh);
            return 0;
        }
        return _realWaveOutWrite(hwo, pwh, cbwh);
    }

    static uint HookWaveOutUnprepHdr(IntPtr hwo, IntPtr pwh, uint cbwh)
    {
        if (_capturing && hwo == _fakeHandle)
        {
            // Clear WHDR_PREPARED flag
            uint flags = (uint)Marshal.ReadInt32(pwh, OFF_dwFlags);
            flags &= ~WHDR_PREPARED;
            Marshal.WriteInt32(pwh, OFF_dwFlags, (int)flags);
            return 0;
        }
        return _realWaveOutUnprepHdr(hwo, pwh, cbwh);
    }

    static uint HookWaveOutReset(IntPtr hwo)
    {
        if (_capturing && hwo == _fakeHandle)
            return 0;
        return _realWaveOutReset(hwo);
    }

    static uint HookWaveOutClose(IntPtr hwo)
    {
        if (_capturing && hwo == _fakeHandle)
        {
            FireCallback(WOM_CLOSE, IntPtr.Zero);
            return 0;
        }
        return _realWaveOutClose(hwo);
    }

    static void FireCallback(uint msg, IntPtr param1)
    {
        if (_cbType == CALLBACK_FUNCTION && _cbAddr != IntPtr.Zero)
        {
            var proc = (WaveOutProcDel)Marshal.GetDelegateForFunctionPointer(_cbAddr, typeof(WaveOutProcDel));
            proc(_fakeHandle, msg, _cbInst, param1, IntPtr.Zero);
        }
        else if (_cbType == CALLBACK_EVENT && _cbAddr != IntPtr.Zero)
        {
            SetEvent(_cbAddr);
        }
        else if (_cbType == CALLBACK_WINDOW && _cbAddr != IntPtr.Zero)
        {
            PostMessageW(_cbAddr, msg, _fakeHandle, param1);
        }
        else if (_cbType == CALLBACK_THREAD)
        {
            PostThreadMessage((uint)_cbAddr.ToInt32(), msg, _fakeHandle, param1);
        }
    }

    // ======================== Sleep Hook ========================

    static void HookSleep(uint dwMilliseconds)
    {
        if (_capturing)
            return; // skip all sleeps during capture for maximum speed
        _realSleep(dwMilliseconds);
    }

    // ======================== IAT Hooking ========================

    static void InstallHooks(IntPtr hModule)
    {
        if (_hooksInstalled) return;

        // Create hook delegates and prevent GC
        _hookOpenDel = new WaveOutOpenDel(HookWaveOutOpen);
        _hookPrepDel = new WaveOutPrepHdrDel(HookWaveOutPrepHdr);
        _hookWriteDel = new WaveOutWriteDel(HookWaveOutWrite);
        _hookUnprepDel = new WaveOutUnprepHdrDel(HookWaveOutUnprepHdr);
        _hookResetDel = new WaveOutResetDel(HookWaveOutReset);
        _hookCloseDel = new WaveOutCloseDel(HookWaveOutClose);

        _hookSleepDel = new SleepDel(HookSleep);

        _gcHandles.Add(GCHandle.Alloc(_hookOpenDel));
        _gcHandles.Add(GCHandle.Alloc(_hookPrepDel));
        _gcHandles.Add(GCHandle.Alloc(_hookWriteDel));
        _gcHandles.Add(GCHandle.Alloc(_hookUnprepDel));
        _gcHandles.Add(GCHandle.Alloc(_hookResetDel));
        _gcHandles.Add(GCHandle.Alloc(_hookCloseDel));
        _gcHandles.Add(GCHandle.Alloc(_hookSleepDel));

        // Hook WINMM.dll waveOut functions
        var hookMap = new Dictionary<string, IntPtr>();
        hookMap["waveOutOpen"] = Marshal.GetFunctionPointerForDelegate(_hookOpenDel);
        hookMap["waveOutPrepareHeader"] = Marshal.GetFunctionPointerForDelegate(_hookPrepDel);
        hookMap["waveOutWrite"] = Marshal.GetFunctionPointerForDelegate(_hookWriteDel);
        hookMap["waveOutUnprepareHeader"] = Marshal.GetFunctionPointerForDelegate(_hookUnprepDel);
        hookMap["waveOutReset"] = Marshal.GetFunctionPointerForDelegate(_hookResetDel);
        hookMap["waveOutClose"] = Marshal.GetFunctionPointerForDelegate(_hookCloseDel);

        var origMap = new Dictionary<string, Action<IntPtr>>();
        origMap["waveOutOpen"] = (p) => { _realWaveOutOpen = (WaveOutOpenDel)Marshal.GetDelegateForFunctionPointer(p, typeof(WaveOutOpenDel)); };
        origMap["waveOutPrepareHeader"] = (p) => { _realWaveOutPrepHdr = (WaveOutPrepHdrDel)Marshal.GetDelegateForFunctionPointer(p, typeof(WaveOutPrepHdrDel)); };
        origMap["waveOutWrite"] = (p) => { _realWaveOutWrite = (WaveOutWriteDel)Marshal.GetDelegateForFunctionPointer(p, typeof(WaveOutWriteDel)); };
        origMap["waveOutUnprepareHeader"] = (p) => { _realWaveOutUnprepHdr = (WaveOutUnprepHdrDel)Marshal.GetDelegateForFunctionPointer(p, typeof(WaveOutUnprepHdrDel)); };
        origMap["waveOutReset"] = (p) => { _realWaveOutReset = (WaveOutResetDel)Marshal.GetDelegateForFunctionPointer(p, typeof(WaveOutResetDel)); };
        origMap["waveOutClose"] = (p) => { _realWaveOutClose = (WaveOutCloseDel)Marshal.GetDelegateForFunctionPointer(p, typeof(WaveOutCloseDel)); };

        PatchIAT(hModule, "WINMM.dll", hookMap, origMap);

        // Hook KERNEL32.dll Sleep to skip delays during capture
        var sleepHookMap = new Dictionary<string, IntPtr>();
        sleepHookMap["Sleep"] = Marshal.GetFunctionPointerForDelegate(_hookSleepDel);

        var sleepOrigMap = new Dictionary<string, Action<IntPtr>>();
        sleepOrigMap["Sleep"] = (p) => { _realSleep = (SleepDel)Marshal.GetDelegateForFunctionPointer(p, typeof(SleepDel)); };

        PatchIAT(hModule, "KERNEL32.dll", sleepHookMap, sleepOrigMap);

        _hooksInstalled = true;
    }

    static void PatchIAT(IntPtr hModule, string targetDll,
                         Dictionary<string, IntPtr> hookMap,
                         Dictionary<string, Action<IntPtr>> origMap)
    {
        // Parse PE headers in memory
        int e_lfanew = Marshal.ReadInt32(hModule, 0x3C);
        IntPtr ntHdr = new IntPtr(hModule.ToInt64() + e_lfanew);

        // PE signature (4) + COFF header: NumberOfSections at offset 2, SizeOfOptionalHeader at offset 16
        IntPtr coffHdr = new IntPtr(ntHdr.ToInt64() + 4);
        IntPtr optHdr = new IntPtr(coffHdr.ToInt64() + 20);

        // PE32: Import directory RVA at optHdr + 104
        int importRVA = Marshal.ReadInt32(optHdr, 104);
        if (importRVA == 0) return;

        IntPtr importDesc = new IntPtr(hModule.ToInt64() + importRVA);

        // Walk IMAGE_IMPORT_DESCRIPTOR array (20 bytes each)
        while (true)
        {
            int nameRVA = Marshal.ReadInt32(importDesc, 12); // Name field
            if (nameRVA == 0) break; // end of array

            string dllName = Marshal.PtrToStringAnsi(new IntPtr(hModule.ToInt64() + nameRVA));
            if (dllName != null && dllName.Equals(targetDll, StringComparison.OrdinalIgnoreCase))
            {
                int iltRVA = Marshal.ReadInt32(importDesc, 0);  // OriginalFirstThunk (ILT)
                int iatRVA = Marshal.ReadInt32(importDesc, 16); // FirstThunk (IAT)

                IntPtr ilt = new IntPtr(hModule.ToInt64() + iltRVA);
                IntPtr iat = new IntPtr(hModule.ToInt64() + iatRVA);

                int entrySize = 4; // 32-bit
                int idx = 0;

                while (true)
                {
                    int iltEntry = Marshal.ReadInt32(ilt, idx * entrySize);
                    if (iltEntry == 0) break;

                    // Check if import by name (bit 31 = 0)
                    if ((iltEntry & 0x80000000) == 0)
                    {
                        // IMAGE_IMPORT_BY_NAME: 2-byte Hint + null-terminated name
                        IntPtr namePtr = new IntPtr(hModule.ToInt64() + iltEntry + 2);
                        string funcName = Marshal.PtrToStringAnsi(namePtr);

                        if (funcName != null && hookMap.ContainsKey(funcName))
                        {
                            IntPtr iatEntryAddr = new IntPtr(iat.ToInt64() + idx * entrySize);
                            IntPtr origAddr = Marshal.ReadIntPtr(iatEntryAddr);

                            // Save original
                            if (origMap.ContainsKey(funcName))
                                origMap[funcName](origAddr);
                            _patches.Add(new IATPatch { Addr = iatEntryAddr, Orig = origAddr });

                            // Patch IAT
                            uint oldProtect;
                            VirtualProtect(iatEntryAddr, (uint)entrySize, PAGE_READWRITE, out oldProtect);
                            Marshal.WriteIntPtr(iatEntryAddr, hookMap[funcName]);
                            VirtualProtect(iatEntryAddr, (uint)entrySize, oldProtect, out oldProtect);
                        }
                    }
                    idx++;
                }
                break; // found target DLL, done
            }

            importDesc = new IntPtr(importDesc.ToInt64() + 20);
        }
    }

    static void RestoreHooks()
    {
        foreach (var p in _patches)
        {
            uint oldProtect;
            VirtualProtect(p.Addr, 4, PAGE_READWRITE, out oldProtect);
            Marshal.WriteIntPtr(p.Addr, p.Orig);
            VirtualProtect(p.Addr, 4, oldProtect, out oldProtect);
        }
        _patches.Clear();
        foreach (var h in _gcHandles)
        {
            if (h.IsAllocated) h.Free();
        }
        _gcHandles.Clear();
        _hooksInstalled = false;
    }

    // ======================== WAV File Writer ========================

    static string WriteWav(byte[] pcmData)
    {
        string path = Path.Combine(Path.GetTempPath(), "bst_" + Guid.NewGuid().ToString("N").Substring(0, 8) + ".wav");
        using (var fs = new FileStream(path, FileMode.Create))
        using (var w = new BinaryWriter(fs))
        {
            int dataLen = pcmData.Length;
            int fmtSize = 16;

            w.Write(new char[] { 'R', 'I', 'F', 'F' });
            w.Write((uint)(36 + dataLen));
            w.Write(new char[] { 'W', 'A', 'V', 'E' });
            w.Write(new char[] { 'f', 'm', 't', ' ' });
            w.Write((uint)fmtSize);
            w.Write((ushort)1); // PCM
            w.Write(_captureChannels);
            w.Write(_captureSampleRate);
            w.Write((uint)(_captureSampleRate * _captureChannels * _captureBitsPerSample / 8));
            w.Write((ushort)(_captureChannels * _captureBitsPerSample / 8));
            w.Write(_captureBitsPerSample);
            w.Write(new char[] { 'd', 'a', 't', 'a' });
            w.Write((uint)dataLen);
            w.Write(pcmData);
        }
        return path;
    }

    // ======================== BST DLL Management ========================

    static void DeInit()
    {
        if (_hModule != IntPtr.Zero)
        {
            if (_hooksInstalled) RestoreHooks();
            try { if (_deInitTTS != null) _deInitTTS(); } catch { }
            FreeLibrary(_hModule);
            _hModule = IntPtr.Zero;
            _initTTS = null;
            _sayTTS = null;
            _deInitTTS = null;
        }
    }

    static bool Init(string dllPath)
    {
        DeInit();

        if (!File.Exists(dllPath))
            return false;

        try
        {
            _hModule = LoadLibraryW(dllPath);
            if (_hModule == IntPtr.Zero) return false;

            IntPtr pInit = GetProcAddress(_hModule, "Init_TTS");
            IntPtr pSay = GetProcAddress(_hModule, "Say_TTS");
            IntPtr pDeInit = GetProcAddress(_hModule, "DeInit_TTS");

            if (pInit == IntPtr.Zero || pSay == IntPtr.Zero || pDeInit == IntPtr.Zero)
            {
                FreeLibrary(_hModule);
                _hModule = IntPtr.Zero;
                return false;
            }

            _initTTS = (InitTTSDelegate)Marshal.GetDelegateForFunctionPointer(pInit, typeof(InitTTSDelegate));
            _sayTTS = (SayTTSDelegate)Marshal.GetDelegateForFunctionPointer(pSay, typeof(SayTTSDelegate));
            _deInitTTS = (DeInitTTSDelegate)Marshal.GetDelegateForFunctionPointer(pDeInit, typeof(DeInitTTSDelegate));

            // Install waveOut hooks BEFORE Init_TTS (in case it opens audio)
            InstallHooks(_hModule);

            _initTTS();
            return true;
        }
        catch
        {
            if (_hModule != IntPtr.Zero)
            {
                FreeLibrary(_hModule);
                _hModule = IntPtr.Zero;
            }
            return false;
        }
    }

    static string SayCapture(string text)
    {
        if (_sayTTS == null) return null;

        _captureStream = new MemoryStream();
        _capturing = true;

        try
        {
            _sayTTS(text);
        }
        catch { }

        _capturing = false;

        byte[] data = _captureStream.ToArray();
        _captureStream.Dispose();
        _captureStream = null;

        if (data.Length == 0 || _captureSampleRate == 0 || _captureChannels == 0)
            return null;

        return WriteWav(data);
    }

    // ======================== JSON Helpers ========================

    static void Respond(string json)
    {
        Console.WriteLine(json);
        Console.Out.Flush();
    }

    static string GetJsonString(string json, string key)
    {
        string pattern = "\"" + key + "\"";
        int idx = json.IndexOf(pattern, StringComparison.Ordinal);
        if (idx < 0) return null;

        idx += pattern.Length;
        while (idx < json.Length && (json[idx] == ' ' || json[idx] == ':')) idx++;
        if (idx >= json.Length || json[idx] != '"') return null;
        idx++;

        var sb = new System.Text.StringBuilder();
        while (idx < json.Length)
        {
            char c = json[idx];
            if (c == '\\' && idx + 1 < json.Length)
            {
                char next = json[idx + 1];
                if (next == '"') { sb.Append('"'); idx += 2; continue; }
                if (next == '\\') { sb.Append('\\'); idx += 2; continue; }
                if (next == '/') { sb.Append('/'); idx += 2; continue; }
                if (next == 'n') { sb.Append('\n'); idx += 2; continue; }
                if (next == 'r') { sb.Append('\r'); idx += 2; continue; }
                if (next == 't') { sb.Append('\t'); idx += 2; continue; }
                sb.Append(c); idx++;
            }
            else if (c == '"') { break; }
            else { sb.Append(c); idx++; }
        }
        return sb.ToString();
    }

    static string EscapeJson(string s)
    {
        if (s == null) return "";
        return s.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\n", "\\n").Replace("\r", "\\r");
    }

    // ======================== Main ========================

    static void Main(string[] args)
    {
        Console.OutputEncoding = System.Text.Encoding.UTF8;
        Console.InputEncoding = System.Text.Encoding.UTF8;

        Respond("{\"ready\":true}");

        string line;
        while ((line = Console.ReadLine()) != null)
        {
            line = line.Trim();
            if (line.Length == 0) continue;

            string cmd = GetJsonString(line, "cmd");
            if (cmd == null)
            {
                Respond("{\"ok\":false,\"error\":\"missing cmd\"}");
                continue;
            }

            if (cmd == "init" || cmd == "switch")
            {
                string dll = GetJsonString(line, "dll");
                if (dll == null || !File.Exists(dll))
                {
                    Respond("{\"ok\":false,\"error\":\"dll not found\"}");
                    continue;
                }
                Respond(Init(dll) ? "{\"ok\":true}" : "{\"ok\":false,\"error\":\"failed to load dll\"}");
            }
            else if (cmd == "say")
            {
                string text = GetJsonString(line, "text");
                if (text == null || text.Length == 0 || _sayTTS == null)
                {
                    Respond("{\"ok\":false,\"error\":\"no text or dll not loaded\"}");
                    continue;
                }
                try
                {
                    string wavPath = SayCapture(text);
                    if (wavPath != null)
                        Respond("{\"ok\":true,\"wav\":\"" + EscapeJson(wavPath) + "\"}");
                    else
                        Respond("{\"ok\":false,\"error\":\"capture failed\"}");
                }
                catch (Exception ex)
                {
                    Respond("{\"ok\":false,\"error\":\"" + EscapeJson(ex.Message) + "\"}");
                }
            }
            else if (cmd == "quit")
            {
                DeInit();
                return;
            }
            else
            {
                Respond("{\"ok\":false,\"error\":\"unknown cmd\"}");
            }
        }

        DeInit();
    }
}
