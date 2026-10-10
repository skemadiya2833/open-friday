"""agentskills.io ``SKILL.md`` loader with progressive disclosure and a trust workflow.

Spec: https://agentskills.io/specification (fetched 2026-10-06; fields name, description,
license, compatibility, metadata, allowed-tools; ``name`` must match the directory name).

Stages
------
1. discovery  - only ``name`` + ``description`` of *installed* skills are exposed (``catalog``).
2. activation - the SKILL.md body is returned by ``activate`` (installed skills only).
3. resources  - files under ``references/`` ``assets/`` ``scripts/`` are readable on demand
                (``read_resource``, path-confined, size-capped). **Nothing is ever executed
                by this module.** Running a bundled script is a separate act that goes through
                the normal tool layer (``run_shell`` is denied by default, then asks).

Trust
-----
    inbox/      owner drops a skill folder here (or the owner-only API copies it)
    quarantine/ imported skills: validated + risk-reported, NOT usable
    proposals/  skills written by the agent: NOT usable, instruction-only, never auto-enabled
    installed/  approved by the owner; trust is bound to a content hash, so any later edit to
                the skill revokes trust until it is re-approved.

``allowed-tools`` in a SKILL.md is parsed and shown in the review report but NEVER grants
anything; permissions always come from the policy file.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_NAME, MAX_DESC, MAX_COMPAT = 64, 1024, 500
MAX_SKILL_BYTES = 5 * 1024 * 1024
MAX_FILES = 200
MAX_RESOURCE_BYTES = 200_000
MAX_BODY_LINES_WARN = 500
CODE_SUFFIXES = {".py", ".sh", ".bat", ".cmd", ".ps1", ".js", ".mjs", ".ts", ".exe", ".dll", ".vbs", ".wsf", ".jar", ".msi", ".psm1"}
_INJECTION = re.compile(
    r"(ignore (all |any |the )?(previous|prior|above) (instructions|rules)|disregard .{0,30}instructions|"
    r"do not tell the user|without (asking|telling) the (user|owner)|run powershell|"
    r"curl [^|]*\|\s*(sh|bash)|invoke-expression|iex\s*\(|rm -rf|format c:|reg add|set-executionpolicy)",
    re.I,
)
_URL = re.compile(r"https?://[^\s)>\"']+", re.I)
_FM = re.compile(r"\A---\s*\r?\n(.*?)\r?\n---\s*(?:\r?\n|\Z)(.*)\Z", re.S)


class SkillError(ValueError):
    pass


@dataclass
class SkillMeta:
    name: str
    description: str
    path: Path
    license: str = ""
    compatibility: str = ""
    metadata: dict[str, str] = field(default_factory=dict)
    allowed_tools: list[str] = field(default_factory=list)
    state: str = "installed"        # installed | quarantine | proposal
    errors: list[str] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "state": self.state,
                "license": self.license, "compatibility": self.compatibility,
                "metadata": self.metadata, "allowed_tools": self.allowed_tools, "errors": self.errors}


# ---------------------------------------------------------------- parsing / validation
def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    m = _FM.match(text.lstrip("\ufeff"))
    if not m:
        raise SkillError("SKILL.md must start with YAML frontmatter delimited by '---'")
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as exc:
        raise SkillError(f"invalid YAML frontmatter: {exc}") from exc
    if not isinstance(fm, dict):
        raise SkillError("frontmatter must be a mapping")
    return fm, m.group(2)


def validate_frontmatter(fm: dict[str, Any], dirname: str | None) -> list[str]:
    errs: list[str] = []
    name, desc = fm.get("name"), fm.get("description")
    if not isinstance(name, str) or not name:
        errs.append("name is required")
    else:
        if len(name) > MAX_NAME:
            errs.append(f"name longer than {MAX_NAME} characters")
        if not NAME_RE.match(name):
            errs.append("name must be lowercase letters/digits and single hyphens, not starting or ending with '-'")
        if dirname is not None and name != dirname:
            errs.append(f"name '{name}' must match the directory name '{dirname}'")
    if not isinstance(desc, str) or not desc.strip():
        errs.append("description is required and must be non-empty")
    elif len(desc) > MAX_DESC:
        errs.append(f"description longer than {MAX_DESC} characters")
    comp = fm.get("compatibility")
    if comp is not None and (not isinstance(comp, str) or not (1 <= len(comp) <= MAX_COMPAT)):
        errs.append(f"compatibility must be a string of 1-{MAX_COMPAT} characters")
    md = fm.get("metadata")
    if md is not None and (not isinstance(md, dict) or not all(isinstance(k, str) and isinstance(v, (str, int, float)) for k, v in md.items())):
        errs.append("metadata must be a mapping of string keys to string values")
    at = fm.get("allowed-tools")
    if at is not None and not isinstance(at, str):
        errs.append("allowed-tools must be a space-separated string")
    lic = fm.get("license")
    if lic is not None and not isinstance(lic, str):
        errs.append("license must be a string")
    return errs


def read_meta(folder: Path, state: str) -> SkillMeta:
    f = folder / "SKILL.md"
    if not f.is_file():
        return SkillMeta(folder.name, "", folder, state=state, errors=["SKILL.md is missing"])
    try:
        fm, _ = split_frontmatter(f.read_text(encoding="utf-8"))
    except (SkillError, UnicodeDecodeError) as exc:
        return SkillMeta(folder.name, "", folder, state=state, errors=[str(exc)])
    errs = validate_frontmatter(fm, folder.name)
    return SkillMeta(
        name=str(fm.get("name") or folder.name), description=str(fm.get("description") or ""), path=folder,
        license=str(fm.get("license") or ""), compatibility=str(fm.get("compatibility") or ""),
        metadata={str(k): str(v) for k, v in (fm.get("metadata") or {}).items()} if isinstance(fm.get("metadata"), dict) else {},
        allowed_tools=str(fm.get("allowed-tools") or "").split(), state=state, errors=errs,
    )


def _files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.is_file())


def tree_hash(folder: Path) -> str:
    h = hashlib.sha256()
    for p in _files(folder):
        h.update(p.relative_to(folder).as_posix().encode())
        h.update(b"\0")
        h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


def review(folder: Path) -> dict[str, Any]:
    """Static risk report shown to the owner before approval. Heuristic, not a guarantee."""
    files = _files(folder)
    code = [p.relative_to(folder).as_posix() for p in files
            if p.suffix.lower() in CODE_SUFFIXES or p.relative_to(folder).parts[0] == "scripts"]
    texts, urls, inj = [], set(), []
    for p in files:
        if p.suffix.lower() in CODE_SUFFIXES or p.stat().st_size > 400_000:
            continue
        try:
            t = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        texts.append(t)
        urls.update(_URL.findall(t))
        inj += [f"{p.relative_to(folder).as_posix()}: {m.group(0)[:60]}" for m in _INJECTION.finditer(t)]
    meta = read_meta(folder, "review")
    body_lines = 0
    try:
        _, body = split_frontmatter((folder / "SKILL.md").read_text(encoding="utf-8"))
        body_lines = len(body.splitlines())
    except Exception:  # noqa: BLE001
        pass
    return {
        "name": meta.name, "valid": not meta.errors, "errors": meta.errors,
        "file_count": len(files), "bytes": sum(p.stat().st_size for p in files),
        "executable_files": code, "runs_code": bool(code),
        "urls": sorted(urls)[:20], "injection_like_text": inj[:20],
        "requests_tools": meta.allowed_tools,
        "notes": (["allowed-tools is ignored: permissions come from policy only"] if meta.allowed_tools else [])
                 + ([f"SKILL.md body has {body_lines} lines (>{MAX_BODY_LINES_WARN})"] if body_lines > MAX_BODY_LINES_WARN else []),
        "hash": tree_hash(folder),
    }


# ---------------------------------------------------------------- store
class SkillStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.inbox, self.quarantine = self.root / "inbox", self.root / "quarantine"
        self.proposals, self.installed = self.root / "proposals", self.root / "installed"
        for d in (self.inbox, self.quarantine, self.proposals, self.installed):
            d.mkdir(parents=True, exist_ok=True)
        self.trust_file = self.root / "trust.json"

    # trust ledger ---------------------------------------------------
    def _trust(self) -> dict[str, Any]:
        try:
            return json.loads(self.trust_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_trust(self, t: dict[str, Any]) -> None:
        tmp = self.trust_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(t, indent=1), encoding="utf-8")
        tmp.replace(self.trust_file)

    def is_trusted(self, name: str) -> bool:
        folder = self.installed / name
        rec = self._trust().get(name)
        return bool(rec) and folder.is_dir() and rec.get("hash") == tree_hash(folder)

    # stage 1 --------------------------------------------------------
    def catalog(self) -> list[SkillMeta]:
        """Name + description of installed, valid, still-trusted skills (what the model may see)."""
        out = []
        for d in sorted(p for p in self.installed.iterdir() if p.is_dir()):
            m = read_meta(d, "installed")
            if not m.errors and self.is_trusted(m.name):
                out.append(m)
        return out

    def list_all(self) -> list[SkillMeta]:
        out: list[SkillMeta] = []
        for state, base in (("installed", self.installed), ("quarantine", self.quarantine), ("proposal", self.proposals)):
            for d in sorted(p for p in base.iterdir() if p.is_dir()):
                m = read_meta(d, state)
                if state == "installed" and not self.is_trusted(d.name):
                    m.errors.append("trust revoked: content changed since approval")
                out.append(m)
        return out

    def catalog_prompt(self) -> str:
        cat = self.catalog()
        if not cat:
            return ""
        lines = ["Available skills (call skill_activate with the name to load full instructions):"]
        lines += [f"- {m.name}: {m.description[:200]}" for m in cat]
        return "\n".join(lines)

    # stage 2 --------------------------------------------------------
    def activate(self, name: str) -> str:
        if not NAME_RE.match(name or ""):
            raise SkillError("invalid skill name")
        if not (self.installed / name).is_dir():
            raise SkillError(f"skill '{name}' is not installed")
        if not self.is_trusted(name):
            raise SkillError(f"skill '{name}' is not trusted (never approved, or changed after approval)")
        _, body = split_frontmatter((self.installed / name / "SKILL.md").read_text(encoding="utf-8"))
        return body.strip()

    # stage 3 --------------------------------------------------------
    def read_resource(self, name: str, rel: str) -> str:
        if not NAME_RE.match(name or "") or not (self.installed / name).is_dir() or not self.is_trusted(name):
            raise SkillError(f"skill '{name}' is not installed and trusted")
        base = (self.installed / name).resolve()
        target = (base / rel).resolve()
        if base != target and base not in target.parents:
            raise SkillError("path escapes the skill folder")
        if not target.is_file():
            raise SkillError("no such file")
        if target.stat().st_size > MAX_RESOURCE_BYTES:
            raise SkillError("file too large")
        if target.suffix.lower() in {".exe", ".dll", ".msi", ".jar"}:
            raise SkillError("binary resources are not readable as text")
        return target.read_text(encoding="utf-8", errors="replace")

    # import / approve -----------------------------------------------
    def _copy_safe(self, src: Path, dst: Path) -> None:
        total, n = 0, 0
        for p in src.rglob("*"):
            if p.is_symlink():
                raise SkillError(f"symlink not allowed: {p.name}")
            rel = p.relative_to(src)
            if any(part in ("..", "") for part in rel.parts):
                raise SkillError("bad path")
            if p.is_file():
                n += 1
                total += p.stat().st_size
                if n > MAX_FILES or total > MAX_SKILL_BYTES:
                    raise SkillError("skill too large")
        shutil.copytree(src, dst)

    def import_from_inbox(self, name: str) -> dict[str, Any]:
        """Move ``inbox/<name>`` (folder) or ``inbox/<name>.zip`` into quarantine and report."""
        if not NAME_RE.match(name):
            raise SkillError("invalid skill name")
        dst = self.quarantine / name
        if dst.exists():
            raise SkillError(f"'{name}' is already in quarantine; reject it first")
        folder, archive = self.inbox / name, self.inbox / f"{name}.zip"
        if archive.is_file():
            self._extract_zip(archive, dst)
        elif folder.is_dir():
            self._copy_safe(folder, dst)
        else:
            raise SkillError(f"nothing named '{name}' (or '{name}.zip') in the inbox")
        rep = review(dst)
        if not rep["valid"]:
            shutil.rmtree(dst, ignore_errors=True)
            raise SkillError("invalid skill: " + "; ".join(rep["errors"]))
        return rep

    def _extract_zip(self, archive: Path, dst: Path) -> None:
        with zipfile.ZipFile(archive) as z:
            infos = z.infolist()
            if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_SKILL_BYTES:
                raise SkillError("archive too large")
            dst.mkdir(parents=True)
            base = dst.resolve()
            try:
                for i in infos:
                    name = i.filename.replace("\\", "/")
                    if name.startswith("/") or re.match(r"^[A-Za-z]:", name) or ".." in name.split("/"):
                        raise SkillError(f"unsafe path in archive: {i.filename}")
                    if (i.external_attr >> 16) & 0o170000 == 0o120000:
                        raise SkillError(f"symlink in archive: {i.filename}")
                    out = (dst / name).resolve()
                    if base != out and base not in out.parents:
                        raise SkillError(f"unsafe path in archive: {i.filename}")
                    if i.is_dir():
                        out.mkdir(parents=True, exist_ok=True)
                    else:
                        out.parent.mkdir(parents=True, exist_ok=True)
                        out.write_bytes(z.read(i))
                # tolerate a single top-level folder wrapper
                kids = list(dst.iterdir())
                if len(kids) == 1 and kids[0].is_dir() and not (dst / "SKILL.md").exists():
                    inner = kids[0]
                    for c in list(inner.iterdir()):
                        shutil.move(str(c), str(dst / c.name))
                    inner.rmdir()
            except Exception:
                shutil.rmtree(dst, ignore_errors=True)
                raise

    def pending(self) -> list[dict[str, Any]]:
        out = []
        for state, base in (("quarantine", self.quarantine), ("proposal", self.proposals)):
            for d in sorted(p for p in base.iterdir() if p.is_dir()):
                out.append({"state": state, "name": d.name, "review": review(d)})
        return out

    def approve(self, name: str, approver: str, *, expected_hash: str | None = None) -> dict[str, Any]:
        """Owner decision. ``expected_hash`` pins approval to the exact content that was reviewed."""
        if not approver:
            raise SkillError("an approver identity is required")
        for state, base in (("quarantine", self.quarantine), ("proposal", self.proposals)):
            src = base / name
            if src.is_dir():
                break
        else:
            raise SkillError(f"'{name}' is not pending approval")
        rep = review(src)
        if not rep["valid"]:
            raise SkillError("invalid skill: " + "; ".join(rep["errors"]))
        if expected_hash and expected_hash != rep["hash"]:
            raise SkillError("content changed since it was reviewed; review it again")
        dst = self.installed / name
        if dst.exists():
            raise SkillError(f"'{name}' is already installed; remove it first")
        shutil.move(str(src), str(dst))
        t = self._trust()
        t[name] = {"hash": tree_hash(dst), "approved_by": approver, "approved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "origin": state, "runs_code": rep["runs_code"], "executable_files": rep["executable_files"]}
        self._save_trust(t)
        return t[name]

    def reject(self, name: str) -> bool:
        for base in (self.quarantine, self.proposals):
            if (base / name).is_dir():
                shutil.rmtree(base / name)
                return True
        return False

    def remove(self, name: str) -> bool:
        if not (self.installed / name).is_dir():
            return False
        shutil.rmtree(self.installed / name)
        t = self._trust()
        t.pop(name, None)
        self._save_trust(t)
        return True

    # proposals ------------------------------------------------------
    def propose(self, name: str, description: str, body: str, *, rationale: str = "",
                proposed_by: str = "agent", run_id: str | None = None) -> Path:
        """Agent-written skill. Instruction-only by construction; waits for owner approval."""
        errs = validate_frontmatter({"name": name, "description": description}, name)
        if errs:
            raise SkillError("; ".join(errs))
        if (self.proposals / name).exists() or (self.installed / name).exists() or (self.quarantine / name).exists():
            raise SkillError(f"a skill named '{name}' already exists")
        if len(body) > 20_000:
            raise SkillError("proposal body too long")
        d = self.proposals / name
        d.mkdir(parents=True)
        fm = {"name": name, "description": description,
              "metadata": {"proposed_by": proposed_by, "run_id": run_id or "", "rationale": rationale[:300]}}
        (d / "SKILL.md").write_text("---\n" + yaml.safe_dump(fm, sort_keys=False, allow_unicode=True) + "---\n\n" + body.strip() + "\n",
                                    encoding="utf-8")
        return d


def slugify(text: str, limit: int = 48) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    s = re.sub(r"-{2,}", "-", s)[:limit].strip("-")
    return s or "task"


def draft_from_run(objective: str, steps: list[str], *, run_id: str | None = None) -> dict[str, str]:
    """Deterministic (no model) draft of a skill from a successful run. Instruction-only."""
    name = "how-to-" + slugify(objective, 40)
    desc = f"Procedure for: {objective.strip()[:200]}. Use when the owner asks for this or a very similar desktop task."
    body = ["# " + objective.strip()[:120], "", "Recorded steps from a successful run (verify each against the live screen; "
            "element ids and coordinates change between runs):", ""]
    body += [f"{i}. {s}" for i, s in enumerate(steps[:25], 1)]
    body += ["", "Check the result on screen before reporting completion."]
    return {"name": name, "description": desc, "body": "\n".join(body)}


_store: SkillStore | None = None


def get_store() -> SkillStore:
    global _store
    if _store is None:
        from friday.config import DATA_DIR

        _store = SkillStore(Path(DATA_DIR) / "skills_md")
    return _store


def set_store(s: SkillStore | None) -> None:
    global _store
    _store = s
