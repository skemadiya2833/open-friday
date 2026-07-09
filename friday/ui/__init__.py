"""UI package — control center GUI, overlay, aim cursor, Win32 helpers."""

__all__ = ["launch_gui"]


def launch_gui() -> None:
    from friday.ui.app import launch_gui as _launch
    _launch()
