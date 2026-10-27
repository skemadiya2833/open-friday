"""Bring CAD to a buildable state without asking the owner to click around."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

Progress = Callable[[str], None]


@dataclass
class ReadyResult:
    ok: bool
    message: str
    steps: list[str] = field(default_factory=list)
    status: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "message": self.message,
            "steps": list(self.steps),
            "status": dict(self.status),
        }


def ensure_ready(*, on_progress: Progress | None = None, launch_wait_s: float = 90.0) -> ReadyResult:
    """Enable prefs if needed, bootstrap Taiga, launch FreeCAD — then re-probe."""
    from friday.cad.settings import apply_patch, detect_freecad_installs, resolve
    from friday.cad.status import probe_status

    steps: list[str] = []

    def log(msg: str) -> None:
        steps.append(msg)
        if on_progress:
            on_progress(msg)

    st = probe_status()
    cfg = resolve()

    # 1) FreeCAD on disk — enable CAD quietly if the owner is asking to build.
    if not st.freecad_found:
        detected = detect_freecad_installs()
        if detected:
            log(f"Detected FreeCAD at {detected[0]}")
            apply_patch({"freecad_install": str(detected[0]), "cad_enabled": True})
            st = probe_status()
            cfg = resolve()
        else:
            return ReadyResult(
                ok=False,
                message="I can't find FreeCAD. Tell me the install folder and I'll save it.",
                steps=steps,
                status=st.as_dict(),
            )

    if not cfg.enabled:
        log("Turning CAD on")
        apply_patch({"cad_enabled": True})
        st = probe_status()

    # 2) biome-s1 + worker venv
    if not st.repo_ok or not st.worker_found:
        log("Setting up Taiga worker…")
        from friday.cad.bootstrap import bootstrap

        boot = bootstrap(enable=True, on_progress=log)
        if not boot.ok:
            return ReadyResult(
                ok=False,
                message=boot.message,
                steps=steps + list(boot.steps),
                status=probe_status().as_dict(),
            )
        st = probe_status()

    # 3) FreeCAD GUI socket
    if not st.socket_ok:
        log("Launching FreeCAD with the Taiga server…")
        from friday.cad.launch import ensure_gui_server

        launch = ensure_gui_server(wait_s=launch_wait_s)
        steps.append(launch.message)
        if on_progress:
            on_progress(launch.message)
        st = probe_status()
        if not st.socket_ok:
            return ReadyResult(
                ok=False,
                message=launch.message,
                steps=steps,
                status=st.as_dict(),
            )

    # 4) Warm Taiga weights once (HF download must not become the build "error")
    from friday.cad.runner import ensure_taiga_model

    warm_ok, warm_msg = ensure_taiga_model(on_progress=log)
    if not warm_ok:
        return ReadyResult(
            ok=False,
            message=warm_msg,
            steps=steps,
            status=probe_status().as_dict(),
        )

    st = probe_status()
    if st.ready_to_build:
        return ReadyResult(
            ok=True,
            message="CAD ready — building now.",
            steps=steps,
            status=st.as_dict(),
        )
    return ReadyResult(
        ok=False,
        message=" ".join(st.blockers) or "CAD still not ready.",
        steps=steps,
        status=st.as_dict(),
    )
