"""Filesystem tools: read, write, edit, list, glob, grep."""

from __future__ import annotations

import difflib
import fnmatch
import re
from pathlib import Path
from typing import Any

from .base import Tool, ToolContext, ToolError, _short

MAX_READ_BYTES = 400_000


def _diff(before: str, after: str, path: str, max_lines: int = 40) -> str:
    """A compact unified diff for permission previews."""
    lines = list(difflib.unified_diff(
        before.splitlines(), after.splitlines(),
        fromfile=path, tofile=path, lineterm="", n=2,
    ))
    if not lines:
        return "(no changes)"
    if len(lines) > max_lines:
        lines = lines[:max_lines] + [f"… (+{len(lines) - max_lines} more diff lines)"]
    return "\n".join(lines)
IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache",
               ".ruff_cache", "dist", "build", ".idea", ".pytest_cache"}


class ReadFile(Tool):
    name = "read_file"
    description = (
        "Read a file from the local filesystem and return its contents with line "
        "numbers. Use before editing. Supports an optional line range."
    )
    read_only = True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read."},
                "start_line": {"type": "integer", "description": "1-indexed first line (optional)."},
                "end_line": {"type": "integer", "description": "1-indexed last line (optional)."},
            },
            "required": ["path"],
        }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> str:
        path = ctx.resolve(args["path"])
        if not path.exists():
            raise ToolError(f"File not found: {path}")
        if path.is_dir():
            raise ToolError(f"{path} is a directory; use list_directory.")
        if path.stat().st_size > MAX_READ_BYTES:
            raise ToolError(f"File too large ({path.stat().st_size} bytes). Read a line range.")
        try:
            text = path.read_text(errors="replace")
        except OSError as e:
            raise ToolError(f"Could not read {path}: {e}")
        lines = text.splitlines()
        start = max(1, args.get("start_line", 1))
        end = min(len(lines), args.get("end_line", len(lines)))
        width = len(str(end))
        body = "\n".join(f"{i:>{width}}  {lines[i - 1]}" for i in range(start, end + 1))
        if not body:
            return "(file is empty)"
        return body

    def call_summary(self, args: dict[str, Any]) -> str:
        return _short(args.get("path", ""))


class WriteFile(Tool):
    name = "write_file"
    description = (
        "Create a new file or overwrite an existing one with the given content. "
        "Parent directories are created automatically."
    )
    requires_permission = True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to write."},
                "content": {"type": "string", "description": "Full file content."},
            },
            "required": ["path", "content"],
        }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> str:
        path = ctx.resolve(args["path"])
        before = path.read_text(errors="replace") if path.exists() else None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args["content"])
        if ctx.journal is not None:
            ctx.journal.record(path, before, args["content"])
        n = len(args["content"].splitlines())
        verb = "Overwrote" if before is not None else "Created"
        return f"{verb} {path} ({n} lines)."

    def permission_preview(self, args: dict[str, Any], ctx: ToolContext) -> str:
        path = ctx.resolve(args["path"])
        content = args.get("content", "")
        if path.exists():
            before = path.read_text(errors="replace")
            return f"Overwrite {path}\n\n{_diff(before, content, str(path))}"
        snippet = "\n".join(f"+{line}" for line in content.splitlines()[:24])
        more = "" if content.count("\n") < 24 else "\n…"
        return f"Create {path}\n\n{snippet}{more}"

    def call_summary(self, args: dict[str, Any]) -> str:
        return _short(args.get("path", ""))


class EditFile(Tool):
    name = "edit_file"
    description = (
        "Replace an exact string in a file with a new string. The old_string must "
        "appear exactly once (include surrounding context to disambiguate). Use "
        "replace_all to replace every occurrence."
    )
    requires_permission = True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_string": {"type": "string", "description": "Exact text to find."},
                "new_string": {"type": "string", "description": "Replacement text."},
                "replace_all": {"type": "boolean", "description": "Replace all occurrences."},
            },
            "required": ["path", "old_string", "new_string"],
        }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> str:
        path = ctx.resolve(args["path"])
        if not path.exists():
            raise ToolError(f"File not found: {path}")
        text = path.read_text(errors="replace")
        old = args["old_string"]
        new = args["new_string"]
        count = text.count(old)
        if count == 0:
            raise ToolError("old_string not found. Read the file and copy the exact text.")
        if count > 1 and not args.get("replace_all"):
            raise ToolError(
                f"old_string appears {count} times. Add surrounding context to make it "
                "unique, or set replace_all=true."
            )
        new_text = text.replace(old, new) if args.get("replace_all") else text.replace(old, new, 1)
        path.write_text(new_text)
        if ctx.journal is not None:
            ctx.journal.record(path, text, new_text)
        return f"Edited {path} ({count if args.get('replace_all') else 1} replacement(s))."

    def permission_preview(self, args: dict[str, Any], ctx: ToolContext) -> str:
        path = ctx.resolve(args["path"])
        if path.exists():
            text = path.read_text(errors="replace")
            old, new = args.get("old_string", ""), args.get("new_string", "")
            after = text.replace(old, new, 1) if old in text else text
            return f"Edit {path}\n\n{_diff(text, after, str(path))}"
        old = "\n".join(f"-{line}" for line in args.get("old_string", "").splitlines()[:8])
        new = "\n".join(f"+{line}" for line in args.get("new_string", "").splitlines()[:8])
        return f"Edit {path}\n\n{old}\n{new}"

    def call_summary(self, args: dict[str, Any]) -> str:
        return _short(args.get("path", ""))


class ListDirectory(Tool):
    name = "list_directory"
    description = "List files and subdirectories in a directory (non-recursive)."
    read_only = True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path (default: cwd)."},
            },
            "required": [],
        }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> str:
        path = ctx.resolve(args.get("path", "."))
        if not path.exists():
            raise ToolError(f"Not found: {path}")
        if not path.is_dir():
            raise ToolError(f"Not a directory: {path}")
        entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        rows = []
        for e in entries:
            if e.is_dir():
                rows.append(f"{e.name}/")
            else:
                try:
                    size = e.stat().st_size
                    rows.append(f"{e.name}  ({size:,} B)")
                except OSError:
                    rows.append(e.name)
        return "\n".join(rows) if rows else "(empty directory)"

    def call_summary(self, args: dict[str, Any]) -> str:
        return _short(args.get("path", "."))


class Glob(Tool):
    name = "glob"
    description = (
        "Find files matching a glob pattern (e.g. '**/*.py', 'src/**/*.ts'), "
        "recursively from a base directory. Ignores common vendor directories."
    )
    read_only = True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern."},
                "path": {"type": "string", "description": "Base directory (default: cwd)."},
            },
            "required": ["pattern"],
        }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> str:
        base = ctx.resolve(args.get("path", "."))
        matches = []
        for p in base.glob(args["pattern"]):
            if any(part in IGNORE_DIRS for part in p.parts):
                continue
            if p.is_file():
                matches.append(str(p.relative_to(base)) if base in p.parents or p.parent == base
                               else str(p))
        matches.sort()
        if not matches:
            return "(no matches)"
        head = matches[:200]
        out = "\n".join(head)
        if len(matches) > 200:
            out += f"\n… and {len(matches) - 200} more"
        return out

    def call_summary(self, args: dict[str, Any]) -> str:
        return _short(args.get("pattern", ""))


class Grep(Tool):
    name = "grep"
    description = (
        "Search file contents for a regular expression and return matching lines "
        "with file:line locations. Recursively searches text files."
    )
    read_only = True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regular expression."},
                "path": {"type": "string", "description": "File or directory (default: cwd)."},
                "glob": {"type": "string", "description": "Only search files matching this glob, e.g. '*.py'."},
                "ignore_case": {"type": "boolean"},
            },
            "required": ["pattern"],
        }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> str:
        base = ctx.resolve(args.get("path", "."))
        flags = re.IGNORECASE if args.get("ignore_case") else 0
        try:
            rx = re.compile(args["pattern"], flags)
        except re.error as e:
            raise ToolError(f"Invalid regex: {e}")
        glob_filter = args.get("glob")

        files: list[Path] = []
        if base.is_file():
            files = [base]
        else:
            for p in base.rglob("*"):
                if any(part in IGNORE_DIRS for part in p.parts):
                    continue
                if not p.is_file():
                    continue
                if glob_filter and not fnmatch.fnmatch(p.name, glob_filter):
                    continue
                files.append(p)

        results: list[str] = []
        for f in files:
            try:
                if b"\x00" in f.read_bytes()[:1024]:  # skip binaries
                    continue
                for i, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
                    if rx.search(line):
                        loc = f.relative_to(base) if base.is_dir() else f
                        results.append(f"{loc}:{i}: {line.strip()[:200]}")
                        if len(results) >= 200:
                            break
            except OSError:
                continue
            if len(results) >= 200:
                results.append("… (truncated at 200 matches)")
                break
        return "\n".join(results) if results else "(no matches)"

    def call_summary(self, args: dict[str, Any]) -> str:
        return _short(args.get("pattern", ""))
