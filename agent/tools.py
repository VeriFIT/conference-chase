"""Local tools exposed to the LLM: fetching pages and searching the web."""
from __future__ import annotations

import re
import time
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

MAX_PAGE_CHARS = 20_000
USER_AGENT = "Mozilla/5.0 (compatible; conference-chase/1.0; +https://github.com/)"
TIMEOUT = httpx.Timeout(20.0)
SEARCH_RETRIES = 3
SEARCH_BACKOFF = 5  # seconds, multiplied by the attempt number

TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web. Returns up to 8 results with title, URL and snippet.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": (
                "Fetch a web page and return its readable text. Links are kept inline as "
                "[text](url) so you can follow 'Call for papers' or 'Important dates' pages."
            ),
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
]


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, follow_redirects=True)


def fetch_url(url: str) -> str:
    if not re.match(r"^https?://", url):
        return "error: only http(s) URLs are supported"
    try:
        with _client() as client:
            resp = client.get(url)
    except httpx.HTTPError as exc:
        return f"error: {exc}"
    if resp.status_code >= 400:
        return f"error: HTTP {resp.status_code}"
    ctype = resp.headers.get("content-type", "")
    if "html" not in ctype and "text" not in ctype:
        return f"error: unsupported content type {ctype!r}"

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        href = urljoin(str(resp.url), a["href"])
        if text and href.startswith("http"):
            a.replace_with(f"[{text}]({href})")
    text = soup.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) > MAX_PAGE_CHARS:
        text = text[:MAX_PAGE_CHARS] + "\n...[truncated]"
    return f"URL: {resp.url}\n\n{text}"


def _search_duckduckgo(query: str) -> list[dict]:
    """Free, keyless search via DuckDuckGo's HTML endpoint.

    DuckDuckGo answers rate-limited requests with HTTP 202 and no results, so
    retry a few times with backoff before giving up.
    """
    with _client() as client:
        for attempt in range(SEARCH_RETRIES):
            resp = client.post("https://html.duckduckgo.com/html/", data={"q": query})
            if resp.status_code == 200 and "result__a" in resp.text:
                break
            if resp.status_code == 200 and "No results" in resp.text:
                return []
            time.sleep(SEARCH_BACKOFF * (attempt + 1))
        else:
            raise httpx.HTTPError(f"rate-limited or blocked (HTTP {resp.status_code}); "
                                  "try fetch_url on a known site instead")
    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for res in soup.select(".result")[:8]:
        link = res.select_one("a.result__a")
        if not link:
            continue
        href = link.get("href", "")
        # DuckDuckGo wraps targets as //duckduckgo.com/l/?uddg=<url>
        target = parse_qs(urlparse(href).query).get("uddg")
        url = unquote(target[0]) if target else href
        snippet = res.select_one(".result__snippet")
        results.append({
            "title": link.get_text(" ", strip=True),
            "url": url,
            "snippet": snippet.get_text(" ", strip=True) if snippet else "",
        })
    return results


def web_search(query: str) -> str:
    try:
        results = _search_duckduckgo(query)
    except httpx.HTTPError as exc:
        return f"error: search failed: {exc}"
    if not results:
        return "no results"
    return "\n\n".join(f"{r['title']}\n{r['url']}\n{r['snippet']}" for r in results)


TOOLS = {"web_search": web_search, "fetch_url": fetch_url}
