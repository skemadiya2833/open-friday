"""Fix UTF-8 mojibake in web/public JS (cp1252 mis-decode of UTF-8, then re-encoded)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    ROOT / "web" / "public" / "app.js",
    ROOT / "web" / "public" / "systems-ui.js",
    ROOT / "web" / "public" / "live.js",
    ROOT / "web" / "public" / "index.html",
]

# bad bytes -> good unicode char
FIXES: list[tuple[bytes, str]] = [
    # ▲ ▼ ►  (U+25B2 / U+25BC / U+25BA) as â–² / â–¼ / â–¸
    (b"\xc3\xa2\xe2\x80\x93\xc2\xb2", "\u25b2"),
    (b"\xc3\xa2\xe2\x80\x93\xc2\xbc", "\u25bc"),
    (b"\xc3\xa2\xe2\x80\x93\xc2\xb8", "\u25ba"),
    # — – …
    (b"\xc3\xa2\xe2\x82\xac\xe2\x80\x9d", "\u2014"),
    (b"\xc3\xa2\xe2\x82\xac\xe2\x80\x93", "\u2013"),
    (b"\xc3\xa2\xe2\x82\xac\xc2\xa6", "\u2026"),
    # ·
    (b"\xc3\x82\xc2\xb7", "\u00b7"),
    # → ↔
    (b"\xc3\xa2\xe2\x80\xa0\xe2\x80\x99", "\u2192"),
    (b"\xc3\xa2\xe2\x80\xa0\xe2\x80\x9d", "\u2194"),
    # ≠ ⚠
    (b"\xc3\xa2\xe2\x80\xb0\xc2\xa0", "\u2260"),
    (b"\xc3\xa2\xc5\xa1\xc2\xa0", "\u26a0"),
    # “ ” ‘ ’
    (b"\xc3\xa2\xe2\x82\xac\xc5\x93", "\u201c"),
    (b"\xc3\xa2\xe2\x82\xac\xc2\x9d", "\u201d"),
    (b"\xc3\xa2\xe2\x82\xac\xcb\x9c", "\u2018"),
    (b"\xc3\xa2\xe2\x82\xac\xe2\x84\xa2", "\u2019"),
    # × misread as Ã— where 0x97 became em-dash (C3 83 E2 80 94)
    (b"\xc3\x83\xe2\x80\x94", "\u00d7"),
]


def main() -> None:
    for path in FILES:
        if not path.is_file():
            continue
        data = path.read_bytes()
        total = 0
        for bad, good in FIXES:
            n = data.count(bad)
            if n:
                data = data.replace(bad, good.encode("utf-8"))
                total += n
                print(f"{path.name}: {n}x fixed -> U+{ord(good):04X}")
        if total:
            path.write_bytes(data)
            print(f"{path.name}: wrote {total} fixes")
        else:
            print(f"{path.name}: clean")


if __name__ == "__main__":
    main()
