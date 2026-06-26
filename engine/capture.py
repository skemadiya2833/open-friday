import mss
import base64
import ctypes
import ctypes.wintypes as wt
import threading
from io import BytesIO
from PIL import Image
from config import PRIMARY_MONITOR_INDEX, PREPROCESS_TARGET_SIZE


# ---------------------------------------------------------------------------
# DPI awareness — must be set before any Win32 call that reads monitor geometry.
# Without this, mss reports logical (scaled) dimensions on some hardware even
# at 100% display scaling, while pyautogui clicks in physical pixel space,
# producing a consistent coordinate offset.
# Level 2 = Per-Monitor DPI Aware v1. Safe to call multiple times.
# ---------------------------------------------------------------------------
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    # Already set by another call, or running on Wine / older Windows.
    pass


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

_WndProcType = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t,
    wt.HWND,
    wt.UINT,
    ctypes.c_size_t,
    ctypes.c_ssize_t,
)

user32.DefWindowProcW.restype  = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, ctypes.c_size_t, ctypes.c_ssize_t]

_DEFAULT_WNDPROC = _WndProcType(
    lambda h, m, w, l: user32.DefWindowProcW(h, m, w, l)
)


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def _pil_to_premult_bgra(img: Image.Image) -> bytes:
    rgba = img.convert("RGBA")
    w, h = rgba.size
    raw  = rgba.tobytes()
    rows = [raw[i * w * 4:(i + 1) * w * 4] for i in range(h)]
    rows.reverse()
    bgra = bytearray()
    for row in rows:
        for j in range(0, len(row), 4):
            r, g, b, a = row[j], row[j + 1], row[j + 2], row[j + 3]
            bgra += bytes([b, g, r, a])
    return bytes(bgra)


def _create_dib_from_pil(hdc_screen, img: Image.Image):
    w, h  = img.size
    bits  = _pil_to_premult_bgra(img)

    bmi                         = BITMAPINFO()
    bmi.bmiHeader.biSize        = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth       = w
    bmi.bmiHeader.biHeight      = h
    bmi.bmiHeader.biPlanes      = 1
    bmi.bmiHeader.biBitCount    = 32
    bmi.bmiHeader.biCompression = BI_RGB
    bmi.bmiHeader.biSizeImage   = w * h * 4

    p_bits = ctypes.c_void_p()
    hbm    = gdi32.CreateDIBSection(
        hdc_screen, ctypes.byref(bmi), DIB_RGB_COLORS,
        ctypes.byref(p_bits), None, 0,
    )
    if not hbm:
        return None, None, w, h

    ctypes.memmove(p_bits, bits, len(bits))
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    gdi32.SelectObject(hdc_mem, hbm)
    return hdc_mem, hbm, w, h


def _update_layered(hwnd, hdc_mem, w: int, h: int, x: int, y: int, alpha: int = 255) -> None:
    hdc_screen = user32.GetDC(None)
    dst_pt     = POINT(x, y)
    src_pt     = POINT(0, 0)
    sz         = SIZE(w, h)
    blend      = BLENDFUNCTION(AC_SRC_OVER, 0, alpha, AC_SRC_ALPHA)
    user32.UpdateLayeredWindow(
        hwnd, hdc_screen,
        ctypes.byref(dst_pt), ctypes.byref(sz),
        hdc_mem, ctypes.byref(src_pt),
        0, ctypes.byref(blend), ULW_ALPHA,
    )
    user32.ReleaseDC(None, hdc_screen)


def _make_thumbnail_image(img: Image.Image) -> Image.Image:
    THUMB_W  = 320
    THUMB_H  = 180
    BORDER   = 3
    LABEL_H  = 26
    PANEL_W  = THUMB_W + BORDER * 2
    PANEL_H  = THUMB_H + BORDER * 2 + LABEL_H

    panel = Image.new("RGBA", (PANEL_W, PANEL_H), (200, 151, 58, 255))
    inner = Image.new("RGBA", (THUMB_W, THUMB_H + LABEL_H), (13, 29, 46, 255))
    panel.paste(inner, (BORDER, BORDER))

    thumb = img.copy().convert("RGB")
    thumb.thumbnail((THUMB_W, THUMB_H), Image.LANCZOS)
    tx = BORDER + (THUMB_W - thumb.width) // 2
    ty = BORDER + (THUMB_H - thumb.height) // 2
    panel.paste(thumb, (tx, ty))

    try:
        from PIL import ImageDraw, ImageFont
        draw    = ImageDraw.Draw(panel)
        label_y = BORDER + THUMB_H + 4
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 13)
        except Exception:
            font = ImageFont.load_default()
        draw.text(
            (BORDER + 8, label_y),
            "Screenshot captured",
            font=font,
            fill=(200, 151, 58, 255),
        )
    except Exception:
        pass

    return panel


# ---------------------------------------------------------------------------
# Animation — daemon thread, never blocks the main capture path
# ---------------------------------------------------------------------------

def _run_animation(img: Image.Image, screen_w: int, screen_h: int) -> None:
    try:
        hinstance  = kernel32.GetModuleHandleW(None)
        CLASS_NAME = "FridayCaptureAnim"

        wc               = WNDCLASSEX()
        wc.cbSize        = ctypes.sizeof(WNDCLASSEX)
        wc.style         = CS_HREDRAW | CS_VREDRAW
        wc.lpfnWndProc   = ctypes.cast(_DEFAULT_WNDPROC, ctypes.c_void_p)
        wc.hInstance     = hinstance
        wc.hCursor       = user32.LoadCursorW(None, wt.LPCWSTR(IDC_ARROW))
        wc.hbrBackground = None
        wc.lpszClassName = CLASS_NAME
        user32.RegisterClassExW(ctypes.byref(wc))

        EX_STYLE = WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE

        # Phase 1 — white flash
        hwnd_flash = user32.CreateWindowExW(
            EX_STYLE, CLASS_NAME, "FridayFlash",
            WS_POPUP | WS_VISIBLE,
            0, 0, screen_w, screen_h,
            None, None, hinstance, None,
        )
        if hwnd_flash:
            user32.SetLayeredWindowAttributes(hwnd_flash, 0, 90, LWA_ALPHA)
            user32.ShowWindow(hwnd_flash, SW_SHOWNOACTIVATE)
            user32.UpdateWindow(hwnd_flash)
            kernel32.Sleep(80)
            user32.DestroyWindow(hwnd_flash)

        # Phase 2 — thumbnail toast
        panel            = _make_thumbnail_image(img)
        MARGIN           = 20
        panel_w, panel_h = panel.size
        target_x         = screen_w - panel_w - MARGIN
        target_y         = screen_h - panel_h - MARGIN
        start_y          = screen_h

        hwnd_thumb = user32.CreateWindowExW(
            EX_STYLE, CLASS_NAME, "FridayThumb",
            WS_POPUP,
            target_x, start_y, panel_w, panel_h,
            None, None, hinstance, None,
        )
        if not hwnd_thumb:
            return

        hdc_screen              = user32.GetDC(None)
        hdc_mem, hbm, w, h      = _create_dib_from_pil(hdc_screen, panel)
        user32.ReleaseDC(None, hdc_screen)

        if not hdc_mem:
            user32.DestroyWindow(hwnd_thumb)
            return

        user32.ShowWindow(hwnd_thumb, SW_SHOWNOACTIVATE)

        # Slide up — 20 frames, ease-out cubic
        for i in range(21):
            t     = i / 20
            eased = 1.0 - (1.0 - t) ** 3
            cur_y = int(start_y + (target_y - start_y) * eased)
            _update_layered(hwnd_thumb, hdc_mem, w, h, target_x, cur_y, alpha=255)
            kernel32.Sleep(6)

        kernel32.Sleep(900)

        # Fade out — 20 frames
        for i in range(21):
            alpha = int(255 * (1.0 - i / 20))
            _update_layered(hwnd_thumb, hdc_mem, w, h, target_x, target_y, alpha=alpha)
            kernel32.Sleep(18)

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
    Capture the primary monitor and prepare the image for the VLM.

    Returns:
        base64_png    — base64-encoded PNG string to send to the model.
        native_size   — physical monitor resolution as (width, height).
                        pyautogui clicks use these coordinates directly.
        image_size    — resolution of the image the model will see.
                        coordinate scaling in coordinates.py uses this to map
                        model output back to native_size click targets.
        pil_image     — raw RGB screenshot for the overlay thumbnail.

    Coordinate contract:
        When image_size == native_size, the model sees full-res pixels and
        coordinates.py applies no scaling (scale factor = 1.0).
        When image_size != native_size (i.e. the image was downsampled),
        coordinates.py scales model coordinates up to native_size before
        passing them to pyautogui. Both paths are correct as long as the
        returned image_size matches the actual pixel dimensions of base64_png.
    """
    with mss.mss() as sct:
        monitor    = sct.monitors[PRIMARY_MONITOR_INDEX]
        screenshot = sct.grab(monitor)
        img        = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
        native_size = (monitor["width"], monitor["height"])

    if show_animation:
        t = threading.Thread(
            target=_run_animation,
            args=(img.copy(), native_size[0], native_size[1]),
            daemon=True,
        )
        t.start()

    # Always preprocess through Pillow to get a consistent model input size.
    # The preprocessor resizes to fit within PREPROCESS_TARGET_SIZE while
    # preserving aspect ratio. If the image already fits, no resize occurs
    # and image_size == native_size, which is the zero-cost path.
    from engine.preprocessor import get_preprocessor
    preprocessor  = get_preprocessor()
    img_b64, image_size = preprocessor.prepare_base64(img, target_size=PREPROCESS_TARGET_SIZE)

    return img_b64, native_size, image_size, img