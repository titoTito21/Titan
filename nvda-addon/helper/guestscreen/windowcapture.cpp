// Capturing a window that will not draw into a device context.
//
// `guest_capture` reads a window through GetWindowDC + StretchBlt, which is
// right for a window that paints with GDI and gives one flat colour for one
// that paints with Direct3D, DXGI, OpenGL or Vulkan - a VMware or VirtualBox
// guest, a Unity or SDL or Godot game, anything on a graphics library. Those
// are exactly the windows a screen reader cannot read any other way, and the
// one thing that DOES capture them is Windows Graphics Capture's
// CreateForWindow: the compositor hands over the window's own composed
// surface, whatever produced it and whether or not it is covered.
//
// This is per-WINDOW capture, not the monitor capture NVDA's own _wgcCapture
// does - so it is not fooled by a window in front, which is the whole point
// for a guest sitting behind a terminal. Nothing is injected into the target
// and its memory is never read: the compositor is asked, in this process.
//
// Windows 10 1903+ (WinRT Graphics.Capture). `wc_supported` says so; the
// caller falls back to the device-context path where it is not.

#include <windows.h>
#include <d3d11.h>
#include <dxgi1_2.h>
#include <inspectable.h>
#include <windows.graphics.capture.interop.h>
#include <windows.graphics.directx.direct3d11.interop.h>

#include <winrt/Windows.Foundation.h>
#include <winrt/Windows.Graphics.h>
#include <winrt/Windows.Graphics.Capture.h>
#include <winrt/Windows.Graphics.DirectX.h>
#include <winrt/Windows.Graphics.DirectX.Direct3D11.h>

#include <mutex>

#pragma comment(lib, "d3d11.lib")
#pragma comment(lib, "dxgi.lib")
#pragma comment(lib, "windowsapp.lib")

#define API extern "C" __declspec(dllexport)

namespace wgc = winrt::Windows::Graphics::Capture;
namespace wgd = winrt::Windows::Graphics::DirectX;
namespace wgdd = winrt::Windows::Graphics::DirectX::Direct3D11;

// The D3D device is expensive to make and safe to keep, so it is made once
// and shared. Everything else (the item, the pool, the session) belongs to
// one capture and is torn down with it.
static std::mutex g_lock;
static winrt::com_ptr<ID3D11Device> g_device;
static wgdd::IDirect3DDevice g_rt{ nullptr };
static bool g_apartment = false;

static bool ensure_device()
{
    if (g_device && g_rt) return true;
    if (!g_apartment)
    {
        // Multi-threaded: Python calls this from a worker of its own, and a
        // single-threaded apartment would want a message pump this thread
        // has not got. RPC_E_CHANGED_MODE means it is already initialised
        // some other way, which is fine.
        winrt::init_apartment(winrt::apartment_type::multi_threaded);
        g_apartment = true;
    }
    winrt::com_ptr<ID3D11Device> device;
    HRESULT hr = D3D11CreateDevice(
        nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr,
        D3D11_CREATE_DEVICE_BGRA_SUPPORT, nullptr, 0, D3D11_SDK_VERSION,
        device.put(), nullptr, nullptr);
    if (FAILED(hr))
        hr = D3D11CreateDevice(
            nullptr, D3D_DRIVER_TYPE_WARP, nullptr,
            D3D11_CREATE_DEVICE_BGRA_SUPPORT, nullptr, 0, D3D11_SDK_VERSION,
            device.put(), nullptr, nullptr);
    if (FAILED(hr)) return false;
    auto dxgi = device.as<IDXGIDevice>();
    winrt::com_ptr<IInspectable> inspectable;
    if (FAILED(CreateDirect3D11DeviceFromDXGIDevice(dxgi.get(),
                                                    inspectable.put())))
        return false;
    g_device = device;
    g_rt = inspectable.as<wgdd::IDirect3DDevice>();
    return true;
}

API int wc_supported()
{
    try
    {
        if (!ensure_device()) return 0;
        return wgc::GraphicsCaptureSession::IsSupported() ? 1 : 0;
    }
    catch (...) { return 0; }
}

static void scale_into(const unsigned char* src, int srcPitch, int srcW,
                       int srcH, int sx, int sy, int sw, int sh,
                       unsigned char* out, int destW, int destH)
{
    // Nearest-neighbour from the [sx,sy,sw,sh] region of the captured
    // surface into destW x destH, top-down BGRA, tightly packed. Nearest
    // rather than averaged because the recogniser reads text and a box
    // filter softens the very edges it looks for.
    if (sw <= 0 || sh <= 0) { sw = srcW; sh = srcH; sx = 0; sy = 0; }
    for (int y = 0; y < destH; ++y)
    {
        int fy = sy + (int)((long long)y * sh / destH);
        if (fy < 0) fy = 0; if (fy >= srcH) fy = srcH - 1;
        const unsigned char* srow = src + (size_t)fy * srcPitch;
        unsigned char* drow = out + (size_t)y * destW * 4;
        for (int x = 0; x < destW; ++x)
        {
            int fx = sx + (int)((long long)x * sw / destW);
            if (fx < 0) fx = 0; if (fx >= srcW) fx = srcW - 1;
            const unsigned char* p = srow + (size_t)fx * 4;
            drow[0] = p[0]; drow[1] = p[1]; drow[2] = p[2]; drow[3] = 255;
            drow += 4;
        }
    }
}

// Capture `hwnd` and scale the [srcX,srcY,srcW,srcH] region of it (whole
// window when srcW/srcH are 0) into `out` as destW x destH top-down BGRA.
// `out` must hold destW*destH*4 bytes. `flat` is set to 1 when every pixel
// is one colour. Answers 1 on success.
API int wc_capture(void* window, int destW, int destH,
                   int srcX, int srcY, int srcW, int srcH,
                   unsigned char* out, int outBytes, int* flat)
{
    if (!window || destW <= 0 || destH <= 0 || !out) return 0;
    if (outBytes < destW * destH * 4) return 0;
    HWND hwnd = (HWND)window;
    if (!IsWindow(hwnd)) return 0;

    std::lock_guard<std::mutex> guard(g_lock);
    try
    {
        if (!ensure_device()) return 0;
        if (!wgc::GraphicsCaptureSession::IsSupported()) return 0;

        auto interop = winrt::get_activation_factory<
            wgc::GraphicsCaptureItem, IGraphicsCaptureItemInterop>();
        wgc::GraphicsCaptureItem item{ nullptr };
        HRESULT hr = interop->CreateForWindow(
            hwnd, winrt::guid_of<wgc::GraphicsCaptureItem>(),
            winrt::put_abi(item));
        if (FAILED(hr) || !item) return 0;

        auto size = item.Size();
        if (size.Width <= 0 || size.Height <= 0) return 0;

        auto pool = wgc::Direct3D11CaptureFramePool::CreateFreeThreaded(
            g_rt, wgd::DirectXPixelFormat::B8G8R8A8UIntNormalized, 2, size);
        auto session = pool.CreateCaptureSession(item);
        // No recording border and no mouse in the shot, where the build
        // allows it. Both are recent and both throw on older Windows, so
        // each is tried on its own and a refusal is not fatal.
        try { session.IsCursorCaptureEnabled(false); } catch (...) {}
        try
        {
            if (auto s3 = session.try_as<wgc::IGraphicsCaptureSession3>())
                s3.IsBorderRequired(false);
        }
        catch (...) {}

        session.StartCapture();

        // The first composed frame is what we are waiting for: TryGetNext
        // frame answers null until the compositor has handed one over, and
        // the very first can be undefined, so a second is taken when one is
        // there. Up to ~500 ms, which is a slow display warming up, not a
        // hang.
        wgc::Direct3D11CaptureFrame frame{ nullptr };
        for (int tries = 0; tries < 50; ++tries)
        {
            auto got = pool.TryGetNextFrame();
            if (got)
            {
                frame = got;
                auto again = pool.TryGetNextFrame();
                if (again) frame = again;
                break;
            }
            Sleep(10);
        }

        int ok = 0;
        if (frame)
        {
            auto access = frame.Surface().as<
                Windows::Graphics::DirectX::Direct3D11::
                IDirect3DDxgiInterfaceAccess>();
            winrt::com_ptr<ID3D11Texture2D> texture;
            if (SUCCEEDED(access->GetInterface(
                    winrt::guid_of<ID3D11Texture2D>(), texture.put_void())))
            {
                D3D11_TEXTURE2D_DESC desc{};
                texture->GetDesc(&desc);
                D3D11_TEXTURE2D_DESC staging = desc;
                staging.Usage = D3D11_USAGE_STAGING;
                staging.BindFlags = 0;
                staging.MiscFlags = 0;
                staging.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
                winrt::com_ptr<ID3D11Texture2D> readable;
                if (SUCCEEDED(g_device->CreateTexture2D(
                        &staging, nullptr, readable.put())))
                {
                    winrt::com_ptr<ID3D11DeviceContext> ctx;
                    g_device->GetImmediateContext(ctx.put());
                    ctx->CopyResource(readable.get(), texture.get());
                    D3D11_MAPPED_SUBRESOURCE mapped{};
                    if (SUCCEEDED(ctx->Map(readable.get(), 0,
                                           D3D11_MAP_READ, 0, &mapped)))
                    {
                        scale_into((const unsigned char*)mapped.pData,
                                   (int)mapped.RowPitch, (int)desc.Width,
                                   (int)desc.Height, srcX, srcY, srcW, srcH,
                                   out, destW, destH);
                        ctx->Unmap(readable.get(), 0);
                        ok = 1;
                    }
                }
            }
        }

        session.Close();
        pool.Close();

        if (ok && flat)
        {
            const uint32_t* dots = (const uint32_t*)out;
            int count = destW * destH;
            uint32_t first = dots[0];
            int same = 1;
            for (int at = 1; at < count; ++at)
                if (dots[at] != first) { same = 0; break; }
            *flat = same;
        }
        return ok;
    }
    catch (...) { return 0; }
}
