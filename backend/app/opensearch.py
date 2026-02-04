from __future__ import annotations

import logging
import re
from functools import lru_cache
from html.parser import HTMLParser
from urllib.parse import quote_plus, urljoin, urlparse

import httpx

try:  # pragma: no cover
    from curl_cffi import requests as curl_requests  # type: ignore
except Exception:  # pragma: no cover
    curl_requests = None  # type: ignore

try:  # pragma: no cover
    import tls_client
except Exception:  # pragma: no cover
    tls_client = None  # type: ignore

from defusedxml import ElementTree as ET

logger = logging.getLogger(__name__)

OPENSEARCH_TIMEOUT = 5
OPENSEARCH_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/118.0 Safari/537.36 go-search-engine/0.4"
)
DEFAULT_HTTP_HEADERS = {
    "User-Agent": OPENSEARCH_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
    "sec-ch-ua": '"Not/A)Brand";v="8", "Chromium";v="118", "Google Chrome";v="118"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}
_HTTP_CLIENT = httpx.Client(
    http2=False,
    headers=DEFAULT_HTTP_HEADERS,
    timeout=httpx.Timeout(OPENSEARCH_TIMEOUT, connect=OPENSEARCH_TIMEOUT),
    follow_redirects=True,
)


class _SearchLinkParser(HTMLParser):
    """HTML parser that collects OpenSearch link hrefs."""

    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "link":
            return
        attr_map = {name.lower(): value or "" for name, value in attrs}
        rel = attr_map.get("rel", "")
        rel_tokens = {token.strip().lower() for token in rel.split()}
        if "search" not in rel_tokens and "search" not in rel.lower():
            return
        type_attr = attr_map.get("type", "")
        if type_attr and "opensearchdescription+xml" not in type_attr.lower():
            return
        href = attr_map.get("href")
        if href:
            self.hrefs.append(href)


def _parse_opensearch_link_hrefs(html: str) -> list[str]:
    parser = _SearchLinkParser()
    parser.feed(html)
    return parser.hrefs


def _parse_opensearch_script_hrefs(html: str) -> list[str]:
    urls: list[str] = []
    pattern = re.compile(r'opensearchurl[^"]*"([^"]+)"', re.IGNORECASE)
    for match in pattern.findall(html):
        unescaped = match.replace("\\/", "/")
        urls.append(unescaped)
    return urls


def _strip_optional_placeholders(template: str) -> str:
    """Remove optional OpenSearch placeholders like "{foo?}" without regex backtracking."""
    if "{" not in template:
        return template

    out: list[str] = []
    pending: list[str] | None = None

    for ch in template:
        if pending is None:
            if ch == "{":
                pending = ["{"]
            else:
                out.append(ch)
            continue

        pending.append(ch)
        if ch != "}":
            continue

        if len(pending) > 2 and pending[-2] == "?":
            pending = None
            continue

        out.extend(pending)
        pending = None

    if pending is not None:
        out.extend(pending)

    return "".join(out)


@lru_cache(maxsize=128)
def _fetch_html(url: str) -> str | None:
    resp = _http_get(url)
    if resp is None:
        return None
    encoding = resp.encoding or "utf-8"
    return resp.content.decode(encoding, errors="replace")


def _http_get(url: str) -> httpx.Response | None:
    resp: httpx.Response | None = None
    try:
        candidate = _HTTP_CLIENT.get(url)
        if candidate.status_code < 400:
            return candidate
    except Exception as exc:  # pragma: no cover - network failure fallback
        logger.debug("Primary httpx request failed", exc_info=exc)
        candidate = None
    if curl_requests is not None:
        try:
            alt = curl_requests.get(
                url,
                impersonate="chrome120",
                timeout=OPENSEARCH_TIMEOUT,
                allow_redirects=True,
            )
            if alt.status_code < 400:
                return _CurlResponseAdapter(alt)
        except Exception as exc:  # pragma: no cover - optional dependency failure
            logger.debug("curl_cffi request failed", exc_info=exc)
    if tls_client is not None:
        try:
            session = tls_client.Session(client_identifier="chrome120")
            alt = session.get(
                url,
                headers=DEFAULT_HTTP_HEADERS,
                timeout=OPENSEARCH_TIMEOUT,
                allow_redirects=True,
            )
            if alt.status_code < 400:
                return _TlsClientResponseAdapter(alt)
        except Exception as exc:  # pragma: no cover - optional dependency failure
            logger.debug("tls-client request failed", exc_info=exc)
    return resp


class _CurlResponseAdapter:
    """Adapter so curl_cffi responses act like httpx responses."""

    def __init__(self, resp):
        self.status_code = resp.status_code
        self.content = resp.content
        self.encoding = resp.encoding


class _TlsClientResponseAdapter:
    """Adapter so tls-client responses act like httpx responses."""

    def __init__(self, resp):
        self.status_code = resp.status_code
        self.content = resp.content
        self.encoding = resp.encoding or "utf-8"


def _opensearch_document_url(link_url: str) -> str | None:
    parsed = urlparse(link_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if parsed.path.lower().endswith(".xml"):
        return link_url
    base = f"{parsed.scheme}://{parsed.netloc}/"
    return urljoin(base, "opensearch.xml")


def _candidate_opensearch_document_urls(link_url: str) -> list[str]:
    parsed = urlparse(link_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return []
    base = f"{parsed.scheme}://{parsed.netloc}"
    docs: list[str] = []
    seen: set[str] = set()

    def add(url: str | None) -> None:
        if url and url not in seen:
            seen.add(url)
            docs.append(url)

    add(_opensearch_document_url(link_url))
    add(urljoin(link_url, "opensearch.xml"))
    add(urljoin(base + "/", "opensearch.xml"))
    add(urljoin(base + "/", ".well-known/opensearch.xml"))

    html_sources = {link_url, base + "/"}
    for html_url in html_sources:
        html = _fetch_html(html_url)
        if not html:
            continue
        for href in _parse_opensearch_link_hrefs(html):
            add(urljoin(html_url, href))
        for href in _parse_opensearch_script_hrefs(html):
            add(urljoin(html_url, href))
    return docs


def _download_opensearch_document(doc_url: str) -> str:
    resp = _http_get(doc_url)
    if resp is None:  # pragma: no cover - network failure fallback
        raise RuntimeError("failed to download OpenSearch descriptor")
    encoding = resp.encoding or "utf-8"
    return resp.content.decode(encoding, errors="replace")


def _extract_search_template(xml_text: str) -> str | None:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    for url_el in root.findall(".//{*}Url"):
        template = url_el.attrib.get("template")
        if not template:
            continue
        method = url_el.attrib.get("method", "get").lower()
        if method != "get":
            continue
        mime = url_el.attrib.get("type", "text/html").lower()
        if mime not in {"text/html", "application/xhtml+xml"}:
            continue
        if "searchterms" not in template.lower():
            continue
        return template
    return None


@lru_cache(maxsize=128)
def _get_opensearch_template(doc_url: str) -> str | None:
    try:
        xml_text = _download_opensearch_document(doc_url)
    except Exception:
        return None
    return _extract_search_template(xml_text)


def _build_search_url(doc_url: str, template: str, terms: str) -> str | None:
    encoded = quote_plus(terms)
    replaced = False
    for placeholder in ("{searchTerms}", "{searchTerms?}", "{searchterms}", "{searchterms?}"):
        if placeholder in template:
            template = template.replace(placeholder, encoded)
            replaced = True
    if not replaced:
        return None
    template = _strip_optional_placeholders(template)
    return urljoin(doc_url, template)


def _lookup_opensearch_search_url(link_url: str, terms: str) -> str | None:
    if not terms:
        return None
    for doc_url in _candidate_opensearch_document_urls(link_url):
        template = _get_opensearch_template(doc_url)
        if not template:
            continue
        search_url = _build_search_url(doc_url, template, terms)
        if search_url:
            return search_url
    return None


def discover_opensearch_template(link_url: str) -> tuple[str, str] | None:
    """Best-effort OpenSearch discovery for a link URL.

    Returns:
        (doc_url, template) when a usable OpenSearch template is found.
    """
    parsed = urlparse(link_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    for doc_url in _candidate_opensearch_document_urls(link_url):
        template = _get_opensearch_template(doc_url)
        if template:
            return doc_url, template
    return None


def refresh_link_opensearch(db, link_id: int, link_url: str) -> bool:
    """Discover and persist OpenSearch metadata for a link.

    Returns True when a template is found and stored.
    """
    try:
        discovered = discover_opensearch_template(link_url)
    except Exception as exc:  # pragma: no cover - network or parser error
        logger.debug("OpenSearch discovery failed for %s", link_url, exc_info=exc)
        discovered = None

    if discovered:
        doc_url, template = discovered
        db.execute(
            "UPDATE links SET opensearch_doc_url=?, opensearch_template=?, search_enabled=1 WHERE id=?",
            (doc_url, template, link_id),
        )
        return True

    db.execute(
        "UPDATE links SET opensearch_doc_url=NULL, opensearch_template=NULL, search_enabled=0 WHERE id=?",
        (link_id,),
    )
    return False
