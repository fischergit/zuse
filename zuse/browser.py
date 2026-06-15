"""Persistent Playwright browser session for real web automation.

One browser/page is kept open across tool calls so the agent can navigate,
read, click, fill forms, and screenshot a live page — JS-rendered sites
included. Created lazily on first use.
"""

from __future__ import annotations


class BrowserSession:
    def __init__(self, headless: bool = True) -> None:
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(headless=headless)
        self.context = self.browser.new_context(viewport={"width": 1280, "height": 900})
        self.page = self.context.new_page()
        self.page.set_default_timeout(15000)

    def navigate(self, url: str) -> tuple[str, str]:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return self.page.title(), self.page.url

    def read_text(self, max_chars: int = 6000) -> str:
        try:
            txt = self.page.inner_text("body")
        except Exception:  # noqa: BLE001
            txt = self.page.content()
        txt = "\n".join(line for line in txt.splitlines() if line.strip())
        return txt[:max_chars] + ("\n… (truncated)" if len(txt) > max_chars else "")

    def links(self, limit: int = 40) -> list[tuple[str, str]]:
        out = []
        for a in self.page.query_selector_all("a[href]"):
            text = (a.inner_text() or "").strip().replace("\n", " ")
            href = a.get_attribute("href") or ""
            if text and href and not href.startswith("javascript:"):
                out.append((text[:60], href))
            if len(out) >= limit:
                break
        return out

    def click(self, text: str | None, selector: str | None) -> str:
        if selector:
            self.page.click(selector, timeout=10000)
            return f"Clicked selector {selector}"
        if text:
            self.page.get_by_text(text, exact=False).first.click(timeout=10000)
            return f"Clicked element with text '{text}'"
        raise ValueError("Provide text or selector.")

    def fill(self, selector: str, value: str, submit: bool) -> str:
        self.page.fill(selector, value, timeout=10000)
        if submit:
            self.page.keyboard.press("Enter")
            self.page.wait_for_load_state("domcontentloaded", timeout=15000)
        return f"Filled {selector}" + (" and submitted" if submit else "")

    def screenshot(self) -> bytes:
        return self.page.screenshot(full_page=False, type="png")

    def current(self) -> tuple[str, str]:
        return self.page.title(), self.page.url

    def close(self) -> None:
        try:
            self.browser.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._pw.stop()
        except Exception:  # noqa: BLE001
            pass


class BrowserManager:
    """Lazily opens a browser on first use and keeps it for the session."""

    def __init__(self, headless: bool = True) -> None:
        self.headless = headless
        self.session: BrowserSession | None = None

    def get(self) -> BrowserSession:
        if self.session is None:
            self.session = BrowserSession(self.headless)
        return self.session

    def close(self) -> None:
        if self.session is not None:
            self.session.close()
            self.session = None
