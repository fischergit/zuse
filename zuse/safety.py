"""Guardrails for shell commands.

Two tiers:
- ALWAYS: catastrophic commands that are essentially never intended — refused in
  every mode, even when a human is approving.
- UNATTENDED: dangerous-but-sometimes-legitimate commands (sudo, force push,
  pipe-to-shell, home/system deletes). Refused only when no human is in the loop
  — i.e. inside an auto-approving crew/sub-agent — so an interactive user can
  still approve them deliberately.
"""

from __future__ import annotations

import re

# Recursive-delete detection: an `rm` with a recursive flag (-r/-R/-rf/--recursive)
# aimed at one of the given targets.
_RM = re.compile(r"\brm\b")
_RM_RECURSIVE = re.compile(r"(?:^|\s)-\S*r|--recursive", re.IGNORECASE)
_ROOT_TARGET = re.compile(r"\s/(?:\s|$|\*)")
_HOME_SYS_TARGET = re.compile(r"\s(?:~|\$HOME|/Users|/etc|/System|/Library|/var|/usr|/bin)(?:/|\s|$|\*)")


def _recursive_rm(command: str, target: re.Pattern[str]) -> bool:
    return bool(_RM.search(command) and _RM_RECURSIVE.search(command) and target.search(command))


# Catastrophic, refused in any mode.
_ALWAYS = [
    (re.compile(r":\(\)\s*\{\s*:\s*\|\s*:&?\s*\}\s*;\s*:"), "fork bomb"),
    (re.compile(r"\bmkfs\b"), "filesystem format (mkfs)"),
    (re.compile(r"\bdd\b[^\n]*\bof=/dev/"), "raw write to a disk device (dd of=/dev/…)"),
    (re.compile(r">\s*/dev/(?:sd|disk|nvme|hd)"), "overwrite of a disk device"),
]

# Dangerous when nobody is approving (crew / auto mode).
_UNATTENDED = [
    (re.compile(r"\bsudo\b"), "privilege escalation (sudo)"),
    (re.compile(r"\bgit\s+push\b[^\n]*(?:--force(?:-with-lease)?\b|\s-f\b)"),
     "force push (rewrites remote history)"),
    (re.compile(r"\b(?:curl|wget)\b[^|\n]*\|\s*(?:sudo\s+)?(?:sh|bash|zsh|fish)\b"),
     "piping a network download into a shell"),
    (re.compile(r"\b(?:shutdown|reboot|halt|poweroff)\b"), "system shutdown/restart"),
    (re.compile(r"\bchmod\s+-R\s+0*777\s+/"), "world-writable chmod on a root path"),
]


def destructive_reason(command: str, unattended: bool) -> str | None:
    """Return a human-readable reason if `command` should be refused, else None.

    `unattended` widens the check to dangerous-but-sometimes-legitimate commands;
    pass True for auto-approving crew/sub-agent contexts.
    """
    c = " ".join(command.split())  # normalize whitespace
    if _recursive_rm(c, _ROOT_TARGET):
        return "recursive delete of / (root)"
    for pat, reason in _ALWAYS:
        if pat.search(c):
            return reason
    if unattended:
        if _recursive_rm(c, _HOME_SYS_TARGET):
            return "recursive delete of a home/system path"
        for pat, reason in _UNATTENDED:
            if pat.search(c):
                return reason
    return None
