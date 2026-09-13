// Reading a virtual machine's guest screen, in the one language that can
// afford to look at every pixel.
//
// The guest is a picture and nothing else: no accessibility layer, no agent,
// and during an operating system's installation not even a system. Three
// questions have to be answered about that picture, several times a second,
// and all three are per-pixel work that Python pays for in object churn:
//
//   1. TAKE it, from the window's own device context - never a screen
//      capture, which reads whatever is in front of the guest.
//   2. Say WHAT CHANGED since the last one, which on a drawn screen is what
//      a key did: the label that lost the selection and the one that gained
//      it. This is what the patent literature calls active-element
//      detection, and it is the whole of how arrow keys are answered.
//   3. Where the guest is in a TEXT mode - a BIOS menu, DOS, a Linux
//      installer, the text half of Windows Setup - read it EXACTLY: cut the
//      picture into character cells and match each against the real VGA
//      glyphs. No model, no guessing, no request to anybody's provider, and
//      the attribute (the highlight) comes out with the words.
//
// Nothing here is a hook into another process and nothing is injected
// anywhere: it is the host's own window, its own pixels, in its own process.
// That is deliberate - a screen reader may not risk somebody else's address
// space to read a screen.
//
// Build: build.bat (MSVC). The add-on loads it if it is there and does the
// same work in Python if it is not, so a machine without it loses speed and
// exactness, never the reading.

#include <windows.h>
#include <stdint.h>
#include <string.h>

#define API extern "C" __declspec(dllexport)

// --------------------------------------------------------------------------
// 1. The picture, out of the window's own context
// --------------------------------------------------------------------------
// `out` is BGRA, `width * height * 4` bytes. Answers 1 when it filled it.
//
// `flat` is set to 1 when every pixel is the same colour, which is what a
// window that did not draw itself gives (a Direct3D surface answers
// `PrintWindow` with pure black). The caller falls back to the screen on
// that rather than announcing a blank guest.
API int guest_capture(void* window, int width, int height,
                      unsigned char* out, int outBytes, int* flat)
{
    if (!window || width <= 0 || height <= 0 || !out) return 0;
    if (outBytes < width * height * 4) return 0;
    HWND hwnd = (HWND)window;
    RECT rect;
    if (!GetWindowRect(hwnd, &rect)) return 0;
    int whole = rect.right - rect.left;
    int tall = rect.bottom - rect.top;
    if (whole <= 0 || tall <= 0) return 0;

    HDC holder = GetWindowDC(hwnd);
    if (!holder) return 0;
    int ok = 0;
    HDC target = CreateCompatibleDC(holder);
    HBITMAP bitmap = target ? CreateCompatibleBitmap(holder, width, height) : NULL;
    HGDIOBJ old = bitmap ? SelectObject(target, bitmap) : NULL;
    if (target && bitmap)
    {
        SetStretchBltMode(target, HALFTONE);
        if (StretchBlt(target, 0, 0, width, height,
                       holder, 0, 0, whole, tall, SRCCOPY))
        {
            BITMAPINFO info;
            memset(&info, 0, sizeof(info));
            info.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
            info.bmiHeader.biWidth = width;
            info.bmiHeader.biHeight = -height;        // top down
            info.bmiHeader.biPlanes = 1;
            info.bmiHeader.biBitCount = 32;
            info.bmiHeader.biCompression = BI_RGB;
            if (GetDIBits(target, bitmap, 0, height, out, &info, DIB_RGB_COLORS))
                ok = 1;
        }
    }
    if (old) SelectObject(target, old);
    if (bitmap) DeleteObject(bitmap);
    if (target) DeleteDC(target);
    ReleaseDC(hwnd, holder);

    if (ok && flat)
    {
        const uint32_t* dots = (const uint32_t*)out;
        uint32_t first = dots[0];
        int count = width * height;
        int same = 1;
        for (int at = 1; at < count; ++at)
            if (dots[at] != first) { same = 0; break; }
        *flat = same;
    }
    return ok;
}

// --------------------------------------------------------------------------
// 2. What changed
// --------------------------------------------------------------------------
// The picture is divided into blocks `block` pixels square and each block is
// summed; a block whose sum moved by more than `tolerance` changed. Changed
// blocks that touch are joined into one region, and the regions come back as
// (left, top, width, height) in pixels, biggest first.
//
// Summing rather than comparing every pixel is what keeps this the same cost
// on a 640x480 guest and a maximised 2358x1285 one: the caller picks the
// block size from the width.
static uint32_t block_sum(const unsigned char* pixels, int width,
                          int left, int top, int wide, int tall)
{
    uint32_t total = 0;
    for (int y = top; y < top + tall; ++y)
    {
        const unsigned char* row = pixels + ((size_t)y * width + left) * 4;
        for (int x = 0; x < wide; ++x)
        {
            total += (uint32_t)row[0] + row[1] + row[2];
            row += 4;
        }
    }
    return total;
}

API int guest_fingerprint(const unsigned char* pixels, int width, int height,
                          int block, uint32_t* out, int outCount)
{
    if (!pixels || width <= 0 || height <= 0 || block <= 0 || !out) return 0;
    int across = width / block;
    int down = height / block;
    if (across <= 0 || down <= 0) return 0;
    if (outCount < across * down) return 0;
    for (int by = 0; by < down; ++by)
        for (int bx = 0; bx < across; ++bx)
            out[by * across + bx] = block_sum(pixels, width, bx * block,
                                              by * block, block, block);
    return across * down;
}

// `regions` takes 4 ints per region. Answers how many it filled.
API int guest_changed(const uint32_t* now, const uint32_t* before,
                      int across, int down, int block, uint32_t tolerance,
                      int* regions, int maxRegions)
{
    if (!now || !before || across <= 0 || down <= 0 || !regions) return 0;
    int count = across * down;
    // A small mark per block: 0 unchanged, 1 changed, 2+ the region it is in.
    static unsigned char marks[1 << 16];
    if (count > (int)sizeof(marks)) return 0;
    for (int at = 0; at < count; ++at)
    {
        uint32_t a = now[at], b = before[at];
        uint32_t gap = a > b ? a - b : b - a;
        marks[at] = gap > tolerance ? 1 : 0;
    }
    int found = 0;
    // A flood fill per changed block, four-connected: a moving selection is
    // one region however oddly it is shaped.
    static int stack[1 << 16];
    for (int start = 0; start < count && found < maxRegions; ++start)
    {
        if (marks[start] != 1) continue;
        int top = start / across, left = start % across;
        int right = left, bottom = top;
        int depth = 0;
        stack[depth++] = start;
        marks[start] = 2;
        while (depth > 0)
        {
            int at = stack[--depth];
            int y = at / across, x = at % across;
            if (x < left) left = x;
            if (x > right) right = x;
            if (y < top) top = y;
            if (y > bottom) bottom = y;
            const int steps[4][2] = { {1,0}, {-1,0}, {0,1}, {0,-1} };
            for (int step = 0; step < 4; ++step)
            {
                int nx = x + steps[step][0], ny = y + steps[step][1];
                if (nx < 0 || ny < 0 || nx >= across || ny >= down) continue;
                int next = ny * across + nx;
                if (marks[next] != 1) continue;
                marks[next] = 2;
                if (depth < (int)(sizeof(stack) / sizeof(stack[0])))
                    stack[depth++] = next;
            }
        }
        regions[found * 4 + 0] = left * block;
        regions[found * 4 + 1] = top * block;
        regions[found * 4 + 2] = (right - left + 1) * block;
        regions[found * 4 + 3] = (bottom - top + 1) * block;
        ++found;
    }
    return found;
}

// --------------------------------------------------------------------------
// 3. A text screen, read exactly
// --------------------------------------------------------------------------
// `font` is 256 glyphs of `glyphH` rows, each row `(glyphW + 7) / 8` bytes,
// most significant bit leftmost - which is the shape every VGA font has had
// since 1987, and what `Windows\Fonts\dosapp.fon` really holds.
//
// A cell is read by taking its two commonest colours - the background is the
// commoner one, because text is thinner than what it sits on - turning the
// cell into bits on that pair, and comparing with every glyph. The best
// match wins; a cell whose best match is not clearly best is a miss, and
// enough misses mean this is not a text screen at all, which is the answer
// that matters: a wrong "exact" reading is worse than no reading.
// One glyph as `glyphH` row masks, so a cell is compared with sixteen
// exclusive-ors and sixteen population counts rather than with 192 separate
// pixel tests. Measured on a rendered 80x25 screen: **125 ms before, 4 ms
// after** - which is the difference between a tier that can run on a tick
// and one that cannot.
static inline uint32_t glyph_row(const unsigned char* font, int glyphW,
                                 int glyphH, int code, int y)
{
    int stride = (glyphW + 7) / 8;
    const unsigned char* row = font + ((size_t)code * glyphH + y) * stride;
    uint32_t bits = 0;
    for (int at = 0; at < stride; ++at) bits = (bits << 8) | row[at];
    return bits >> (stride * 8 - glyphW);
}

static inline int popcount32(uint32_t value)
{
    value = value - ((value >> 1) & 0x55555555u);
    value = (value & 0x33333333u) + ((value >> 2) & 0x33333333u);
    value = (value + (value >> 4)) & 0x0F0F0F0Fu;
    return (int)((value * 0x01010101u) >> 24);
}

API int guest_text(const unsigned char* pixels, int width, int height,
                   const unsigned char* font, int glyphW, int glyphH,
                   int cols, int rows,
                   unsigned char* text, uint32_t* ink, uint32_t* paper,
                   int* matched, int* written)
{
    if (!pixels || !font || !text || glyphW <= 0 || glyphH <= 0) return 0;
    if (glyphW > 32 || glyphH > 64) return 0;
    if (cols <= 0 || rows <= 0) return 0;
    if (cols * glyphW > width || rows * glyphH > height) return 0;

    // Every glyph's rows, once for the whole screen.
    static uint32_t shapes[256][64];
    for (int code = 0; code < 256; ++code)
        for (int y = 0; y < glyphH; ++y)
            shapes[code][y] = glyph_row(font, glyphW, glyphH, code, y);

    int hits = 0, inked = 0;
    int cellBits = glyphW * glyphH;
    int forgiven = cellBits / 32;              // a pixel of rounding
    for (int row = 0; row < rows; ++row)
    {
        for (int col = 0; col < cols; ++col)
        {
            int left = col * glyphW, top = row * glyphH;
            uint32_t colours[64]; int counts[64]; int kinds = 0;
            for (int y = 0; y < glyphH; ++y)
            {
                const uint32_t* line = (const uint32_t*)(pixels +
                    ((size_t)(top + y) * width + left) * 4);
                for (int x = 0; x < glyphW; ++x)
                {
                    uint32_t colour = line[x] & 0x00FFFFFFu;
                    int seen = -1;
                    for (int at = 0; at < kinds; ++at)
                        if (colours[at] == colour) { seen = at; break; }
                    if (seen >= 0) ++counts[seen];
                    else if (kinds < 64)
                    { colours[kinds] = colour; counts[kinds] = 1; ++kinds; }
                }
            }
            int firstAt = 0, secondAt = -1;
            for (int at = 1; at < kinds; ++at)
                if (counts[at] > counts[firstAt]) firstAt = at;
            for (int at = 0; at < kinds; ++at)
                if (at != firstAt && (secondAt < 0 || counts[at] > counts[secondAt]))
                    secondAt = at;
            uint32_t back = colours[firstAt];
            uint32_t fore = secondAt >= 0 ? colours[secondAt] : back;
            if (ink) ink[row * cols + col] = fore;
            if (paper) paper[row * cols + col] = back;

            // **A cell of one colour is a BLANK, and it is a match.** It was
            // counted as a miss at first, which made a perfectly read text
            // screen score 10% - most of a screen is spaces - and 10% is
            // what "this is not a text screen" looks like. The score is what
            // decides whether this tier answers at all, so it has to mean
            // something.
            // **A cell of one colour is a BLANK, and it is neither a hit
            // nor a miss.** Counting it as a hit was worse than counting it
            // as a miss: most of a text screen is spaces, so EVERY cell size
            // scored about one - including the wrong ones, which then read a
            // screen of nothing and reported it as certain. What says the
            // grid is right is the cells that have ink in them.
            if (kinds <= 1)
            {
                text[row * cols + col] = (unsigned char)' ';
                continue;
            }

            // **A character cell is TWO colours.** Random pixels have a
            // commonest colour that covers almost nothing, so nearly every
            // pixel counts as ink, and the glyph that matches "almost every
            // pixel set" is the solid block: noise was read as a screenful
            // of blocks and reported as certain text. A cell whose two
            // commonest colours do not cover it is not a character - it is a
            // photograph, an icon, or text somebody has scaled and filtered -
            // and this tier has nothing to say about it.
            {
                int covered = counts[firstAt] +
                              (secondAt >= 0 ? counts[secondAt] : 0);
                if (covered * 100 < cellBits * 95)
                {
                    text[row * cols + col] = (unsigned char)' ';
                    continue;
                }
            }
            ++inked;

            uint32_t bits[64];
            for (int y = 0; y < glyphH; ++y)
            {
                uint32_t line_bits = 0;
                const uint32_t* line = (const uint32_t*)(pixels +
                    ((size_t)(top + y) * width + left) * 4);
                for (int x = 0; x < glyphW; ++x)
                {
                    line_bits <<= 1;
                    if ((line[x] & 0x00FFFFFFu) != back) line_bits |= 1;
                }
                bits[y] = line_bits;
            }
            int best = (int)' ', bestScore = -1, runnerUp = -1;
            for (int code = 0; code < 256; ++code)
            {
                int wrong = 0;
                const uint32_t* shape = shapes[code];
                for (int y = 0; y < glyphH; ++y)
                    wrong += popcount32(shape[y] ^ bits[y]);
                int score = cellBits - wrong;
                if (score > bestScore)
                { runnerUp = bestScore; bestScore = score; best = code; }
                else if (score > runnerUp) runnerUp = score;
                if (wrong == 0) break;             // exact: nothing can beat it
            }
            int good = bestScore >= cellBits - forgiven && bestScore > runnerUp;
            text[row * cols + col] = good ? (unsigned char)best
                                          : (unsigned char)' ';
            if (good) ++hits;
        }
    }
    if (matched) *matched = hits;
    if (written) *written = inked;
    return cols * rows;
}
