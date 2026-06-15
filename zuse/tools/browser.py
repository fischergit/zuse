"""Browser automation tools (Playwright). Registered only if playwright is
installed. The browser stays open across calls, so navigate then read/click/type."""

from __future__ import annotations

import base64
from typing import Any

from .base import Tool, ToolContext, ToolError, ToolOutput, _short


def _session(ctx: ToolContext):
    if ctx.browser is None:
        raise ToolError("Browser is not available.")
    try:
        return ctx.browser.get()
    except Exception as e:  # noqa: BLE001
        raise ToolError(
            f"Could not start the browser: {e}. If Chromium is missing, run: "
            "python -m playwright install chromium"
        )


class BrowserOpen(Tool):
    name = "browser_open"
    description = (
        "Open a URL in the browser (a real Chromium that runs JavaScript). Returns "
        "the page title and URL. Then use browser_read to read it, browser_click / "
        "browser_type to interact, or browser_screenshot to see it."
    )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}

    def run(self, args: dict[str, Any], ctx: ToolContext) -> str:
        try:
            title, url = _session(ctx).navigate(args["url"])
        except ToolError:
            raise
        except Exception as e:  # noqa: BLE001
            raise ToolError(f"Navigation failed: {e}")
        return f"Opened: {title}\n{url}"

    def call_summary(self, args: dict[str, Any]) -> str:
        return _short(args.get("url", ""))


class BrowserRead(Tool):
    name = "browser_read"
    description = "Read the visible text of the current browser page."
    read_only = True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    def run(self, args: dict[str, Any], ctx: ToolContext) -> str:
        return _session(ctx).read_text()


class BrowserLinks(Tool):
    name = "browser_links"
    description = "List the links (text → href) on the current page, for navigation."
    read_only = True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    def run(self, args: dict[str, Any], ctx: ToolContext) -> str:
        links = _session(ctx).links()
        if not links:
            return "(no links found)"
        return "\n".join(f"{text}  →  {href}" for text, href in links)


class BrowserClick(Tool):
    name = "browser_click"
    description = (
        "Click an element on the current page, either by visible text or a CSS "
        "selector. Prefer text for links/buttons."
    )
    requires_permission = True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Visible text to click."},
                "selector": {"type": "string", "description": "CSS selector (alternative)."},
            },
            "required": [],
        }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> str:
        try:
            return _session(ctx).click(args.get("text"), args.get("selector"))
        except ToolError:
            raise
        except Exception as e:  # noqa: BLE001
            raise ToolError(f"Click failed: {e}")

    def permission_preview(self, args: dict[str, Any], ctx: ToolContext) -> str:
        return f"Click in browser: {args.get('text') or args.get('selector')}"

    def call_summary(self, args: dict[str, Any]) -> str:
        return _short(args.get("text") or args.get("selector", ""))


class BrowserType(Tool):
    name = "browser_type"
    description = (
        "Type text into a form field on the current page, found by CSS selector "
        "(e.g. 'input[name=q]', '#email'). Set submit=true to press Enter after."
    )
    requires_permission = True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "text": {"type": "string"},
                "submit": {"type": "boolean"},
            },
            "required": ["selector", "text"],
        }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> str:
        try:
            return _session(ctx).fill(args["selector"], args["text"], bool(args.get("submit")))
        except ToolError:
            raise
        except Exception as e:  # noqa: BLE001
            raise ToolError(f"Type failed: {e}")

    def permission_preview(self, args: dict[str, Any], ctx: ToolContext) -> str:
        return f"Type into {args.get('selector')}: {args.get('text', '')[:120]}"

    def call_summary(self, args: dict[str, Any]) -> str:
        return _short(args.get("selector", ""))


class BrowserScreenshot(Tool):
    name = "browser_screenshot"
    description = "Take a screenshot of the current browser page and see it (image)."
    read_only = True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolOutput:
        png = _session(ctx).screenshot()
        title, url = _session(ctx).current()
        b64 = base64.standard_b64encode(png).decode()
        return ToolOutput(text=f"Screenshot of {title} ({url})", images=[b64])


def browser_tools() -> list[Tool]:
    return [
        BrowserOpen(), BrowserRead(), BrowserLinks(),
        BrowserClick(), BrowserType(), BrowserScreenshot(),
    ]


def available() -> bool:
    try:
        import playwright  # noqa: F401

        return True
    except ImportError:
        return False
