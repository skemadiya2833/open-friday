"""Context-aware classification of pop-up dialogs (Stage K3).

A dialog is classified from its *text and owning app*, not from a button name alone. Only known benign categories
(crash report, feedback request, update nag, tip) in non-denylisted, non-browser apps may be dismissed without a
human, and only with a button from that category's decline list. Anything that could discard unsaved user work
("Don't Save", "No" on a save prompt, closing with unsaved changes) is never auto-dismissed and is flagged so the
guard asks the owner (which fails closed in unattended runs).

Dialog text is untrusted: it is only ever *matched* here, never obeyed. A save-prompt signal always wins over a
benign-looking one, so a spoofed "crash report" wording cannot turn a save prompt into an auto-dismissed one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from friday.agent import uitree as U

BENIGN = ("crash_report", "feedback", "update_nag", "tip")

_SAVE = re.compile(r"(save (the )?changes|do you want to save|want to save|unsaved|not saved|save before|"
                   r"save (your )?(work|file|document)|discard (changes|your)|changes will be lost)", re.I)
_CRASH = re.compile(r"(has (stopped working|crashed)|stopped responding|unexpected(ly)? (error|closed|quit)|"
                    r"\bcrash(ed)?\b|(don.?t|do not) send|send (a |the |an )?(crash |error |bug )?report|error report|"
                    r"report (this |the )?(problem|crash|error)|problem (caused|occurred)|something went wrong)", re.I)
_FEEDBACK = re.compile(r"(feedback|survey|rate (us|this|the app)|how (are we|did we) doing|help us improve|"
                       r"share your (thoughts|experience)|tell us what you think)", re.I)
_UPDATE = re.compile(r"(update (is )?available|new version|updates? (are )?available|update now|remind me later|"
                     r"a newer version|install (the )?update)", re.I)
_TIP = re.compile(r"(tip of the day|did you know|what.?s new|welcome to|getting started|quick tips?)", re.I)

# Buttons that decline or merely close, in order of preference, per category.
SAFE_BUTTONS = {
    "crash_report": ["don't send", "do not send", "dont send", "never send", "don't report", "do not report",
                     "no", "not now", "close", "cancel"],
    "feedback": ["no thanks", "no, thanks", "not now", "maybe later", "later", "dismiss", "close", "cancel", "no"],
    "update_nag": ["remind me later", "later", "not now", "skip", "skip this version", "no thanks", "close",
                   "cancel", "dismiss"],
    "tip": ["close", "got it", "dismiss", "ok", "not now"],
}
# Never clicked automatically, in any benign category.
NEVER_AUTO = re.compile(r"\b(send|yes|report|submit|share|upload|install|update now|accept|agree|allow|continue|"
                        r"restart|sign|log ?in|buy|pay|save|delete|remove|discard|don.?t save|exit|quit)\b", re.I)
# Buttons that can throw away the owner's unsaved work (checked on save prompts and unknown dialogs).
DISCARD = re.compile(r"^(no|don.?t save|do not save|discard|discard changes|close|exit|quit|exit without saving|"
                     r"close without saving|leave|don.?t keep)$", re.I)
_BROWSER = re.compile(r"(google chrome|microsoft edge|mozilla firefox|brave|opera|vivaldi)", re.I)
_DIALOG_CLASS_WORDS = re.compile(r"(error|warning|crash|report|update|feedback|save|confirm|alert|notice|problem|"
                                 r"not responding|stopped working|tip|welcome|what.?s new|survey|rate)", re.I)


@dataclass
class DialogInfo:
    category: str                       # crash_report | feedback | update_nag | tip | save_prompt | unknown
    owner: str                          # title of the window that owns the dialog
    text: str = ""
    buttons: list[str] = field(default_factory=list)
    auto_dismiss: bool = False
    safe_button: str | None = None
    reason: str = ""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\u2019", "'")).strip()


def classify(owner: str, texts: list[str], buttons: list[str], *, deny_apps: list[str] | None = None,
             injection: bool = False) -> DialogInfo:
    """Pure function: decide what a dialog is and whether it may be dismissed without a human."""
    btns = [_norm(b) for b in buttons if _norm(b)]
    # Windows-MCP often does not expose the dialog body (static labels), so the title and the button set are
    # evidence too: "Send / Don't send" is a report prompt, "Save / Don't Save / Cancel" is a save prompt.
    text = _norm(" ".join(texts + btns))
    info = DialogInfo("unknown", owner, text[:300], btns)

    if _SAVE.search(text) or any(re.fullmatch(r"(don.?t save|do not save|discard( changes)?)", b.replace("&", ""), re.I) for b in btns):                        # save prompt wins over everything else (anti-spoofing)
        info.category = "save_prompt"
        info.reason = "dialog asks about saving: dismissing could discard unsaved work"
        return info
    cat = next((c for c, rx in (("crash_report", _CRASH), ("feedback", _FEEDBACK),
                                ("update_nag", _UPDATE), ("tip", _TIP)) if rx.search(text)), None)
    if cat is None:
        info.reason = "unrecognised dialog: left to the owner/model"
        return info
    info.category = cat
    if injection:
        info.reason = "dialog text looks like instructions: not auto-dismissed"
        return info
    if _BROWSER.search(owner or ""):
        info.reason = "dialog is inside a web page (untrusted content): not auto-dismissed"
        return info
    from friday.agent.guard import DEFAULT_DENY_APPS

    pats = deny_apps if deny_apps is not None else DEFAULT_DENY_APPS
    if any(re.search(p, owner or "", re.I) or re.search(p, text, re.I) for p in pats):
        info.reason = "dialog belongs to a denylisted app"
        return info
    lowered = {b.lower().replace("&", ""): b for b in btns}
    for want in SAFE_BUTTONS[cat]:
        b = lowered.get(want)
        if b is not None:                      # exact match against the vetted decline list only
            info.auto_dismiss, info.safe_button = True, b
            info.reason = f"benign {cat}: decline with '{b}'"
            return info
    info.reason = f"benign {cat} but no safe decline button found"
    return info


def detect_dialog(snap: U.Snapshot, *, deny_apps: list[str] | None = None, max_elements: int = 14) -> DialogInfo | None:
    """Heuristic: the focused window is small (few interactive elements), has a button, and talks like a dialog."""
    ft = snap.focused_title()
    if not ft:
        return None
    els = [e for e in snap.elements if e.window == ft]
    buttons = [e.name for e in els if e.ctype == "button" and e.action]
    if not buttons or len(els) > max_elements:
        return None
    texts = [ft] + [t for w, t in snap.texts if w == ft] + [e.name for e in els if e.ctype in ("text", "document", "pane")]
    from friday.agent import guard as G

    joined = " ".join(texts)
    info = classify(ft, texts, buttons, deny_apps=deny_apps, injection=G.looks_like_injection(joined))
    if info.category == "unknown" and not _DIALOG_CLASS_WORDS.search(joined):
        return None
    return info


def discards_work(info: DialogInfo | None, label: str) -> bool:
    """True when clicking ``label`` in this dialog could throw away unsaved data."""
    if not label:
        return False
    lab = _norm(label).replace("&", "")
    if info is not None and info.category == "save_prompt":
        return not re.fullmatch(r"(save( all)?|cancel)", lab, re.I)       # only Save and Cancel are harmless
    return bool(DISCARD.match(lab)) and info is not None and info.category in ("unknown",) and \
        bool(re.search(r"\b(save|unsaved|changes)\b", info.text, re.I))
