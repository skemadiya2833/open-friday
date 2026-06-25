import mss
import base64
import ctypes
import ctypes.wintypes as wt
import struct
import threading
from io import BytesIO
from PIL import Image
from config import PRIMARY_MONITOR_INDEX, NPU_PREPROCESSING, PREPROCESS_TARGET_SIZE


# ---------------------------------------------------------------------------
# Win32 constants
# ---------------------------------------------------------------------------
WS_EX_LAYERED      = 0x00080000
WS_EX_TOPMOST      = 0x00000008
WS_EX_TOOLWINDOW   = 0x00000080
WS_EX_NOACTIVATE   = 0x08000000
WS_POPUP           = 0x80000000
WS_VISIBLE         = 0x10000000

GWL_EXSTYLE        = -20
LWA_ALPHA          = 0x00000002
LWA_COLORKEY       = 0x00000001
ULW_ALPHA          = 0x00000002

AC_SRC_OVER        = 0x00
AC_SRC_ALPHA       = 0x01

BI_RGB             = 0
DIB_RGB_COLORS     = 0

CS_HREDRAW         = 0x0002
CS_VREDRAW         = 0x0001
IDC_ARROW          = 32512
COLOR_WINDOW       = 5

WM_DESTROY         = 0x0002
WM_PAINT           = 0x000F
WM_TIMER           = 0x0113
WM_NCHITTEST       = 0x0084
HTCLIENT           = 1
PM_REMOVE          = 0x0001

SW_SHOWNOACTIVATE  = 4

# ---------------------------------------------------------------------------
# Win32 structures
# ---------------------------------------------------------------------------
class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp",             ctypes.c_byte),
        ("BlendFlags",          ctypes.c_byte),
        ("SourceConstantAlpha", ctypes.c_byte),
        ("AlphaFormat",         ctypes.c_byte),
    ]

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

class SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize",          wt.DWORD),
        ("biWidth",         wt.LONG),
        ("biHeight",        wt.LONG),
        ("biPlanes",        wt.WORD),
        ("biBitCount",      wt.WORD),
        ("biCompression",   wt.DWORD),
        ("biSizeImage",     wt.DWORD),
        ("biXPelsPerMeter", wt.LONG),
        ("biYPelsPerMeter", wt.LONG),
        ("biClrUsed",       wt.DWORD),
        ("biClrImportant",  wt.DWORD),
    ]

class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]

class WNDCLASSEX(ctypes.Structure):
    _fields_ = [
        ("cbSize",        wt.UINT),
        ("style",         wt.UINT),
        ("lpfnWndProc",   ctypes.c_void_p),
        ("cbClsExtra",    ctypes.c_int),
        ("cbWndExtra",    ctypes.c_int),
        ("hInstance",     wt.HANDLE),
        ("hIcon",         wt.HANDLE),
        ("hCursor",       wt.HANDLE),
        ("hbrBackground", wt.HANDLE),
        ("lpszMenuName",  wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR),
        ("hIconSm",       wt.HANDLE),
    ]

class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd",    wt.HWND),
        ("message", wt.UINT),
        ("wParam",  wt.WPARAM),
        ("lParam",  wt.LPARAM),
        ("time",    wt.DWORD),
        ("pt",      POINT),
    ]

# ---------------------------------------------------------------------------
# Win32 API bindings
# ---------------------------------------------------------------------------
user32   = ctypes.windll.user32
gdi32    = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

# WNDPROC signature: LRESULT (HWND, UINT, WPARAM, LPARAM)
# On 64-bit Windows, LPARAM is a signed 64-bit value. Using c_long (32-bit)
# causes OverflowError when Windows sends messages with large coordinate values
# (e.g. WM_NCHITTEST encodes screen coords that exceed INT32_MAX on some setups).
# Fix: use c_ssize_t (== LRESULT/LPARAM on both 32 and 64-bit Windows).
_WndProcType = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t,   # LRESULT
    wt.HWND,            # hWnd
    wt.UINT,            # uMsg
    ctypes.c_size_t,    # WPARAM  (unsigned pointer-sized)
    ctypes.c_ssize_t,   # LPARAM  (signed pointer-sized)  ← was c_long, caused overflow
)

# Define the wndproc ONCE at module level so ctypes keeps a stable reference.
# A lambda defined inside a function gets GC'd, which can cause a second class
# of crash. Pointing straight at DefWindowProcW is the cleanest approach.
user32.DefWindowProcW.restype  = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, ctypes.c_size_t, ctypes.c_ssize_t]

_DEFAULT_WNDPROC = _WndProcType(
    lambda h, m, w, l: user32.DefWindowProcW(h, m, w, l)
)

def _pil_to_premult_bgra(img: Image.Image) -> bytes:
    """
    Convert a PIL RGB image to a pre-multiplied BGRA byte buffer.
    UpdateLayeredWindow requires pre-multiplied alpha in the DIB bits.
    We use full opacity (alpha=255) so premult = identity.
    """
    rgba = img.convert("RGBA")
    w, h = rgba.size
    raw  = rgba.tobytes()                    # RGBA, top-down
    # Flip to bottom-up (DIB convention) and swap R↔B
    rows = [raw[i*w*4:(i+1)*w*4] for i in range(h)]
    rows.reverse()
    bgra = bytearray()
    for row in rows:
        for j in range(0, len(row), 4):
            r, g, b, a = row[j], row[j+1], row[j+2], row[j+3]
            bgra += bytes([b, g, r, a])
    return bytes(bgra)


def _create_dib_from_pil(hdc_screen, img: Image.Image):
    """
    Create a DIB section from a PIL image.
    Returns (hdc_mem, hbm_dib, w, h) — caller must clean up.
    """
    w, h   = img.size
    bits   = _pil_to_premult_bgra(img)

    bmi             = BITMAPINFO()
    bmi.bmiHeader.biSize        = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth       = w
    bmi.bmiHeader.biHeight      = h        # positive = bottom-up
    bmi.bmiHeader.biPlanes      = 1
    bmi.bmiHeader.biBitCount    = 32
    bmi.bmiHeader.biCompression = BI_RGB
    bmi.bmiHeader.biSizeImage   = w * h * 4

    p_bits = ctypes.c_void_p()
    hbm    = gdi32.CreateDIBSection(
        hdc_screen,
        ctypes.byref(bmi),
        DIB_RGB_COLORS,
        ctypes.byref(p_bits),
        None, 0
    )
    if not hbm:
        return None, None, w, h

    # Copy pixel data into the DIB
    ctypes.memmove(p_bits, bits, len(bits))

    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    gdi32.SelectObject(hdc_mem, hbm)
    return hdc_mem, hbm, w, h


def _update_layered(hwnd, hdc_mem, w: int, h: int, x: int, y: int, alpha: int = 255) -> None:
    """Call UpdateLayeredWindow to push a new frame with the given alpha."""
    hdc_screen = user32.GetDC(None)

    dst_pt  = POINT(x, y)
    src_pt  = POINT(0, 0)
    sz      = SIZE(w, h)
    blend   = BLENDFUNCTION(AC_SRC_OVER, 0, alpha, AC_SRC_ALPHA)

    user32.UpdateLayeredWindow(
        hwnd, hdc_screen,
        ctypes.byref(dst_pt),
        ctypes.byref(sz),
        hdc_mem,
        ctypes.byref(src_pt),
        0,                       # colorKey (unused)
        ctypes.byref(blend),
        ULW_ALPHA,
    )
    user32.ReleaseDC(None, hdc_screen)


def _make_thumbnail_image(img: Image.Image) -> Image.Image:
    """
    Compose the thumbnail panel: screenshot + gold border + dark bg + label.
    Returns a single PIL RGBA image ready for UpdateLayeredWindow.
    """
    THUMB_W, THUMB_H = 320, 180
    BORDER           = 3
    LABEL_H          = 26
    PANEL_W          = THUMB_W + BORDER * 2
    PANEL_H          = THUMB_H + BORDER * 2 + LABEL_H

    # Gold border background
    panel = Image.new("RGBA", (PANEL_W, PANEL_H), (200, 151, 58, 255))  # #c8973a

    # Dark inner background
    inner = Image.new("RGBA", (THUMB_W, THUMB_H + LABEL_H), (13, 29, 46, 255))  # #0d1d2e
    panel.paste(inner, (BORDER, BORDER))

    # Screenshot thumbnail
    thumb = img.copy().convert("RGB")
    thumb.thumbnail((THUMB_W, THUMB_H), Image.LANCZOS)
    tx = BORDER + (THUMB_W - thumb.width)  // 2
    ty = BORDER + (THUMB_H - thumb.height) // 2
    panel.paste(thumb, (tx, ty))

    # Label row — draw text with PIL if font available, otherwise solid bar
    try:
        from PIL import ImageDraw, ImageFont
        draw = ImageDraw.Draw(panel)
        label_y = BORDER + THUMB_H + 4
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 13)
        except Exception:
            font = ImageFont.load_default()
        draw.text((BORDER + 8, label_y), "📷  Screenshot captured", font=font, fill=(200, 151, 58, 255))
    except Exception:
        pass  # label is cosmetic — silently skip

    return panel


# ---------------------------------------------------------------------------
# Animation entry point — runs in its own daemon thread
# ---------------------------------------------------------------------------

def _run_animation(img: Image.Image, screen_w: int, screen_h: int) -> None:
    """
    Two-phase Win32 layered-window animation.

    Phase 1 — White flash (80 ms): full-screen white WS_EX_LAYERED window,
               fades in instantly then out.
    Phase 2 — Thumbnail toast (≈1.3 s): a 326x209 panel slides up from the
               bottom-right corner with an ease-out curve, holds, then fades.
    """
    try:
        hinstance = kernel32.GetModuleHandleW(None)

        # ── Register a minimal window class ──────────────────────────────
        CLASS_NAME = "FridayCaptureAnim"
        wc               = WNDCLASSEX()
        wc.cbSize        = ctypes.sizeof(WNDCLASSEX)
        wc.style         = CS_HREDRAW | CS_VREDRAW
        wc.lpfnWndProc   = ctypes.cast(_DEFAULT_WNDPROC, ctypes.c_void_p)
        wc.hInstance     = hinstance
        wc.hCursor       = user32.LoadCursorW(None, wt.LPCWSTR(IDC_ARROW))
        wc.hbrBackground = None
        wc.lpszClassName = CLASS_NAME
        user32.RegisterClassExW(ctypes.byref(wc))   # ok if already registered

        EX_STYLE = WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE

        # ── PHASE 1: Full-screen white flash ─────────────────────────────
        hwnd_flash = user32.CreateWindowExW(
            EX_STYLE, CLASS_NAME, "FridayFlash",
            WS_POPUP | WS_VISIBLE,
            0, 0, screen_w, screen_h,
            None, None, hinstance, None
        )
        if hwnd_flash:
            user32.SetLayeredWindowAttributes(hwnd_flash, 0, 90, LWA_ALPHA)
            user32.ShowWindow(hwnd_flash, SW_SHOWNOACTIVATE)
            user32.UpdateWindow(hwnd_flash)
            kernel32.Sleep(80)
            user32.DestroyWindow(hwnd_flash)

        # ── PHASE 2: Thumbnail toast ──────────────────────────────────────
        panel      = _make_thumbnail_image(img)
        MARGIN     = 20
        panel_w, panel_h = panel.size
        target_x   = screen_w - panel_w - MARGIN
        target_y   = screen_h - panel_h - MARGIN
        start_y    = screen_h          # off screen bottom

        hwnd_thumb = user32.CreateWindowExW(
            EX_STYLE, CLASS_NAME, "FridayThumb",
            WS_POPUP,
            target_x, start_y, panel_w, panel_h,
            None, None, hinstance, None
        )
        if not hwnd_thumb:
            return

        hdc_screen = user32.GetDC(None)
        hdc_mem, hbm, w, h = _create_dib_from_pil(hdc_screen, panel)
        user32.ReleaseDC(None, hdc_screen)

        if not hdc_mem:
            user32.DestroyWindow(hwnd_thumb)
            return

        user32.ShowWindow(hwnd_thumb, SW_SHOWNOACTIVATE)

        # Slide-up: 20 frames, ease-out cubic, ~120 ms
        SLIDE_FRAMES = 20
        SLIDE_MS     = 6
        for i in range(SLIDE_FRAMES + 1):
            t      = i / SLIDE_FRAMES
            eased  = 1.0 - (1.0 - t) ** 3
            cur_y  = int(start_y + (target_y - start_y) * eased)
            _update_layered(hwnd_thumb, hdc_mem, w, h, target_x, cur_y, alpha=255)
            kernel32.Sleep(SLIDE_MS)

        # Hold
        kernel32.Sleep(900)

        # Fade-out: 20 frames, ~360 ms
        FADE_FRAMES = 20
        FADE_MS     = 18
        for i in range(FADE_FRAMES + 1):
            alpha = int(255 * (1.0 - i / FADE_FRAMES))
            _update_layered(hwnd_thumb, hdc_mem, w, h, target_x, target_y, alpha=alpha)
            kernel32.Sleep(FADE_MS)

        # Cleanup
        gdi32.DeleteDC(hdc_mem)
        gdi32.DeleteObject(hbm)
        user32.DestroyWindow(hwnd_thumb)

    except Exception as exc:
        print(f"[Capture Animation] Non-fatal error: {exc}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def capture_screen(show_animation: bool = True) -> tuple[str, tuple[int, int], tuple[int, int], Image.Image]:
    """
    Captures the primary monitor.

    Args:
        show_animation: If True (default), plays the screenshot flash +
                        thumbnail preview animation in a background thread.

    Returns:
        base64_png_string,
        native_size  — physical monitor resolution as (width, height),
        image_size   — resolution of the image actually sent to the VLM,
        pil_image    — raw RGB screenshot (for debug viewer / previews).
    """
    with mss.mss() as sct:
        monitor    = sct.monitors[PRIMARY_MONITOR_INDEX]
        screenshot = sct.grab(monitor)

        img         = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
        native_size = (monitor["width"], monitor["height"])

        if show_animation:
            anim_img = img.copy()
            t = threading.Thread(
                target=_run_animation,
                args=(anim_img, native_size[0], native_size[1]),
                daemon=True,
            )
            t.start()

        if NPU_PREPROCESSING:
            from engine.preprocessor import get_preprocessor
            preprocessor = get_preprocessor()
            img_b64, image_size = preprocessor.prepare_base64(
                img, target_size=PREPROCESS_TARGET_SIZE
            )
            return img_b64, native_size, image_size, img

        buffered = BytesIO()
        img.save(buffered, format="PNG")
        img_b64  = base64.b64encode(buffered.getvalue()).decode("utf-8")
        return img_b64, native_size, native_size, img