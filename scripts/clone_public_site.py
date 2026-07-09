#!/usr/bin/env python3
"""Clone a public website into a local editable folder.

This is designed as a practical exit path from website builders:
it downloads public HTML pages, linked assets, a sitemap when available,
and rewrites the downloaded HTML/CSS so the local copy can be served
from a normal static hosting folder.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import subprocess
import sys
import html as html_lib
from collections import deque
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.parse import parse_qs
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0 Safari/537.36"
)

HTML_ATTRS = ("href", "src", "srcset", "poster", "content", "data-src")
CSS_URL_RE = re.compile(r"url\((['\"]?)(.*?)\1\)")
CSS_IMPORT_RE = re.compile(r"@import\s+(?:url\()?['\"]?(.*?)['\"]?\)?")
ABSOLUTE_URL_RE = re.compile(r"https?://[^\s\"'<>\\)]+")
LIKELY_RELATIVE_URL_RE = re.compile(r'["\'](/[^"\']+)["\']')
ASSET_HOST_HINTS = {
    "assets.zyrosite.com",
    "cdn.zyrosite.com",
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "images.pexels.com",
    "images.unsplash.com",
    "videos.pexels.com",
}
ASSET_SUFFIXES = (
    ".avif",
    ".bmp",
    ".css",
    ".eot",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".map",
    ".mp4",
    ".otf",
    ".pdf",
    ".png",
    ".svg",
    ".txt",
    ".ttf",
    ".webm",
    ".webp",
    ".woff",
    ".woff2",
    ".xml",
)


def build_session() -> requests.Session:
    session = requests.Session()
    retries = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "HEAD"),
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def normalize_url(raw_url: str) -> str:
    parsed = urlparse(raw_url.strip())
    if not parsed.scheme:
        raw_url = f"https://{raw_url.lstrip('/')}"
        parsed = urlparse(raw_url)
    parsed = parsed._replace(fragment="")
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return urlunparse((parsed.scheme, parsed.netloc.lower(), path, "", parsed.query, ""))


def fetch_text(session: requests.Session, url: str, timeout: int) -> tuple[str, str]:
    response = session.get(url, timeout=(15, timeout))
    response.raise_for_status()
    response.encoding = response.encoding or "utf-8"
    return response.text, response.url


def fetch_bytes(
    session: requests.Session, url: str, timeout: int
) -> tuple[bytes, str, str]:
    try:
        response = session.get(url, timeout=(15, timeout))
        response.raise_for_status()
        return response.content, response.url, response.headers.get("content-type", "")
    except Exception:
        completed = subprocess.run(
            [
                "curl.exe",
                "-L",
                "--fail",
                "--silent",
                "--show-error",
                "--max-time",
                str(timeout),
                url,
            ],
            capture_output=True,
            check=True,
        )
        return completed.stdout, url, ""


def ensure_directory(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def local_page_path(output_dir: Path, page_url: str) -> Path:
    parsed = urlparse(page_url)
    path = parsed.path or "/"
    clean_parts = [segment for segment in path.split("/") if segment]
    if not clean_parts:
        target = output_dir / "index.html"
    elif "." in clean_parts[-1]:
        target = output_dir.joinpath(*clean_parts)
    else:
        target = output_dir.joinpath(*clean_parts) / "index.html"
    ensure_directory(target)
    return target


def guess_extension(content_type: str, fallback: str = ".bin") -> str:
    mime = content_type.split(";")[0].strip()
    return mimetypes.guess_extension(mime) or fallback


def local_asset_path(output_dir: Path, asset_url: str, content_type: str = "") -> Path:
    parsed = urlparse(asset_url)
    host = parsed.netloc or "local"
    raw_path = parsed.path or "/download"
    clean_parts = [segment for segment in raw_path.split("/") if segment]
    if not clean_parts:
        clean_parts = ["download"]
    filename = clean_parts[-1]
    if "." not in filename:
        filename += guess_extension(content_type)
    if parsed.query:
        stem, suffix = os.path.splitext(filename)
        digest = hashlib.sha1(parsed.query.encode("utf-8")).hexdigest()[:8]
        filename = f"{stem}--q-{digest}{suffix}"
    clean_parts[-1] = filename
    target = output_dir / "_assets" / host / Path(*clean_parts)
    ensure_directory(target)
    return target


def is_same_host(url: str, host: str) -> bool:
    return urlparse(url).netloc.lower() == host.lower()


def looks_like_page(url: str, host: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    if not is_same_host(url, host):
        return False
    path = parsed.path or "/"
    filename = path.rsplit("/", 1)[-1]
    if not filename or "." not in filename:
        return True
    return filename.lower().endswith((".html", ".htm"))


def log_warning(message: str) -> None:
    safe_message = message.encode("ascii", "backslashreplace").decode("ascii")
    print(safe_message)


def looks_like_url_fragment(value: str) -> bool:
    candidate = value.strip()
    if not candidate:
        return False
    if candidate.startswith(("http://", "https://", "/")):
        return True
    return False


def clean_candidate_url(value: str) -> str | None:
    candidate = value.strip()
    if not looks_like_url_fragment(candidate):
        return None
    bad_markers = (" ", "<", ">", "{", "}", "[", "]", "|", "&quot", "&lt", "&gt")
    if any(marker in candidate for marker in bad_markers):
        return None
    return candidate


def looks_like_asset_url(url: str, base_host: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    path = (parsed.path or "").lower()
    host = parsed.netloc.lower()
    if host in ASSET_HOST_HINTS:
        return True
    if path.startswith("/_astro"):
        return True
    if path.endswith(ASSET_SUFFIXES):
        return True
    if host == "app.vantelia.es" and "/widget/" in path:
        return True
    if host == base_host.lower() and any(token in path for token in ("/widget/", "/cdn-cgi/image/")):
        return True
    return False


def split_srcset(value: str) -> list[str]:
    urls = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        urls.append(item.split()[0])
    if not urls:
        return []
    return [urls[-1]]


def canonical_asset_key(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path or "/"
    if host == "assets.zyrosite.com" and "/cdn-cgi/image/" in path:
        suffix = path.split("/cdn-cgi/image/", 1)[1]
        if "/" in suffix:
            return f"{host}/" + suffix.split("/", 1)[1]
    if host in {
        "app.vantelia.es",
        "images.pexels.com",
        "images.unsplash.com",
        "videos.pexels.com",
    }:
        return f"{host}{path}"
    return f"{host}{path}"


def asset_preference_score(url: str) -> int:
    parsed = urlparse(url)
    score = 0
    for text in (parsed.path, parsed.query):
        width_match = re.search(r"w=(\d+)", text)
        height_match = re.search(r"h=(\d+)", text)
        if width_match:
            score += int(width_match.group(1)) * 10
        if height_match:
            score += int(height_match.group(1))
    query_values = parse_qs(parsed.query)
    for key in ("w", "width"):
        if key in query_values:
            try:
                score += int(query_values[key][0]) * 10
            except ValueError:
                pass
    for key in ("h", "height"):
        if key in query_values:
            try:
                score += int(query_values[key][0])
            except ValueError:
                pass
    return score


def extract_sitemap_urls(session: requests.Session, base_url: str, timeout: int) -> list[str]:
    sitemap_url = urljoin(base_url.rstrip("/") + "/", "sitemap.xml")
    try:
        xml_text, _ = fetch_text(session, sitemap_url, timeout)
    except Exception:
        return []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    urls: list[str] = []
    for loc in root.findall(".//{*}loc"):
        if loc.text:
            urls.append(normalize_url(loc.text))
    return urls


def extract_page_and_asset_urls(html_text: str, page_url: str, base_host: str) -> tuple[set[str], set[str]]:
    soup = BeautifulSoup(html_text, "html.parser")
    page_urls: set[str] = set()
    asset_urls: set[str] = set()

    for tag in soup.find_all(True):
        for attr in HTML_ATTRS:
            value = tag.get(attr)
            if not value:
                continue
            values = split_srcset(value) if attr == "srcset" else [value]
            for item in values:
                cleaned = clean_candidate_url(item)
                if not cleaned:
                    continue
                absolute = normalize_url(urljoin(page_url, cleaned))
                if tag.name == "a" and attr == "href":
                    if looks_like_page(absolute, base_host):
                        page_urls.add(absolute)
                    elif looks_like_asset_url(absolute, base_host):
                        asset_urls.add(absolute)
                    continue
                if tag.name == "meta" and attr == "content":
                    if looks_like_asset_url(absolute, base_host):
                        asset_urls.add(absolute)
                    elif looks_like_page(absolute, base_host):
                        page_urls.add(absolute)
                    continue
                if looks_like_page(absolute, base_host):
                    page_urls.add(absolute)
                elif looks_like_asset_url(absolute, base_host):
                    asset_urls.add(absolute)

    for match in ABSOLUTE_URL_RE.findall(html_text):
        cleaned = clean_candidate_url(match)
        if not cleaned:
            continue
        absolute = normalize_url(cleaned)
        if looks_like_page(absolute, base_host):
            page_urls.add(absolute)
        elif looks_like_asset_url(absolute, base_host):
            asset_urls.add(absolute)

    # Capture same-host absolute-path CSS/JS links embedded in the HTML.
    for rel_match in LIKELY_RELATIVE_URL_RE.findall(html_text):
        cleaned = clean_candidate_url(rel_match)
        if not cleaned:
            continue
        absolute = normalize_url(urljoin(page_url, cleaned))
        if looks_like_page(absolute, base_host):
            page_urls.add(absolute)
        elif looks_like_asset_url(absolute, base_host):
            asset_urls.add(absolute)

    return page_urls, asset_urls


def extract_css_asset_urls(css_text: str, css_url: str) -> set[str]:
    urls: set[str] = set()
    for pattern in (CSS_URL_RE, CSS_IMPORT_RE):
        for match in pattern.findall(css_text):
            candidate = match[1] if isinstance(match, tuple) else match
            candidate = candidate.strip()
            if not candidate or candidate.startswith("data:"):
                continue
            urls.add(normalize_url(urljoin(css_url, candidate)))
    return urls


def make_relative(from_file: Path, to_file: Path) -> str:
    return os.path.relpath(to_file, from_file.parent).replace("\\", "/")


def rewrite_text_links(
    text: str,
    page_file: Path,
    url_to_local: dict[str, Path],
    same_host: str,
) -> str:
    replacements: dict[str, str] = {}
    for url, local_path in url_to_local.items():
        replacements[url] = make_relative(page_file, local_path)
        parsed = urlparse(url)
        if parsed.netloc.lower() == same_host.lower():
            root_relative = parsed.path or "/"
            if parsed.query:
                root_relative += f"?{parsed.query}"
            replacements[root_relative] = make_relative(page_file, local_path)

    for source in sorted(replacements, key=len, reverse=True):
        target = replacements[source]
        text = text.replace(f'"{source}"', f'"{target}"')
        text = text.replace(f"'{source}'", f"'{target}'")
        escaped_source = html_lib.escape(source, quote=True)
        if escaped_source != source:
            text = text.replace(f'"{escaped_source}"', f'"{target}"')
            text = text.replace(f"'{escaped_source}'", f"'{target}'")
    return text


def clone_site(base_url: str, output_dir: Path, timeout: int, max_pages: int) -> dict[str, object]:
    session = build_session()
    base_url = normalize_url(base_url)

    # Resolve redirects before building the crawl scope.
    homepage_html, resolved_home_url = fetch_text(session, base_url, timeout)
    base_url = normalize_url(resolved_home_url)
    base_host = urlparse(base_url).netloc

    output_dir.mkdir(parents=True, exist_ok=True)

    page_queue: deque[str] = deque()
    seen_pages: set[str] = set()
    discovered_assets: set[str] = set()
    page_html_map: dict[str, str] = {}
    page_file_map: dict[str, Path] = {}
    asset_file_map: dict[str, Path] = {}
    asset_content_types: dict[str, str] = {}

    seeds = [base_url]
    seeds.extend(extract_sitemap_urls(session, base_url, timeout))
    for seed in seeds:
        if looks_like_page(seed, base_host) and seed not in seen_pages:
            page_queue.append(seed)

    page_html_map[base_url] = homepage_html

    while page_queue and len(seen_pages) < max_pages:
        current_url = page_queue.popleft()
        if current_url in seen_pages:
            continue

        if current_url == base_url and current_url in page_html_map:
            html_text = page_html_map[current_url]
        else:
            try:
                html_text, final_url = fetch_text(session, current_url, timeout)
                current_url = normalize_url(final_url)
            except Exception as exc:
                log_warning(f"[warn] page skipped: {current_url} ({exc})")
                seen_pages.add(current_url)
                continue

        seen_pages.add(current_url)
        page_path = local_page_path(output_dir, current_url)
        page_file_map[current_url] = page_path
        page_html_map[current_url] = html_text

        next_pages, page_assets = extract_page_and_asset_urls(html_text, current_url, base_host)
        discovered_assets.update(page_assets)
        for next_page in sorted(next_pages):
            if next_page not in seen_pages and next_page not in page_queue:
                page_queue.append(next_page)

    css_assets_to_scan: deque[str] = deque()
    downloaded_assets: set[str] = set()
    downloaded_asset_keys: set[str] = set()
    asset_queue: deque[str] = deque(
        sorted(discovered_assets, key=asset_preference_score, reverse=True)
    )

    while asset_queue:
        asset_url = asset_queue.popleft()
        canonical_key = canonical_asset_key(asset_url)
        if asset_url in downloaded_assets or canonical_key in downloaded_asset_keys:
            continue
        downloaded_assets.add(asset_url)

        try:
            content, final_url, content_type = fetch_bytes(session, asset_url, timeout)
        except Exception as exc:
            log_warning(f"[warn] asset skipped: {asset_url} ({exc})")
            continue

        final_url = normalize_url(final_url)
        downloaded_asset_keys.add(canonical_asset_key(final_url))
        asset_path = local_asset_path(output_dir, final_url, content_type)
        asset_path.write_bytes(content)
        asset_file_map[final_url] = asset_path
        asset_content_types[final_url] = content_type

        if "text/css" in content_type or asset_path.suffix.lower() == ".css":
            css_assets_to_scan.append(final_url)

    while css_assets_to_scan:
        css_url = css_assets_to_scan.popleft()
        css_path = asset_file_map.get(css_url)
        if not css_path or not css_path.exists():
            continue

        try:
            css_text = css_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        for nested_asset in extract_css_asset_urls(css_text, css_url):
            canonical_key = canonical_asset_key(nested_asset)
            if nested_asset in downloaded_assets or canonical_key in downloaded_asset_keys:
                continue
            try:
                content, final_url, content_type = fetch_bytes(session, nested_asset, timeout)
            except Exception as exc:
                log_warning(f"[warn] nested asset skipped: {nested_asset} ({exc})")
                continue

            final_url = normalize_url(final_url)
            downloaded_asset_keys.add(canonical_asset_key(final_url))
            asset_path = local_asset_path(output_dir, final_url, content_type)
            asset_path.write_bytes(content)
            asset_file_map[final_url] = asset_path
            asset_content_types[final_url] = content_type
            downloaded_assets.add(final_url)
            if "text/css" in content_type or asset_path.suffix.lower() == ".css":
                css_assets_to_scan.append(final_url)

    url_to_local = {**page_file_map, **asset_file_map}

    for page_url, html_text in page_html_map.items():
        page_file = page_file_map[page_url]
        rewritten = rewrite_text_links(html_text, page_file, url_to_local, base_host)
        page_file.write_text(rewritten, encoding="utf-8")

    for asset_url, asset_file in asset_file_map.items():
        content_type = asset_content_types.get(asset_url, "")
        if not ("text/css" in content_type or asset_file.suffix.lower() == ".css"):
            continue
        css_text = asset_file.read_text(encoding="utf-8", errors="ignore")
        rewritten = rewrite_text_links(css_text, asset_file, url_to_local, base_host)
        asset_file.write_text(rewritten, encoding="utf-8")

    manifest = {
        "base_url": base_url,
        "pages": {url: str(path.relative_to(output_dir)) for url, path in page_file_map.items()},
        "assets": {url: str(path.relative_to(output_dir)) for url, path in asset_file_map.items()},
        "page_count": len(page_file_map),
        "asset_count": len(asset_file_map),
    }
    (output_dir / "clone_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    return manifest


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        required=True,
        help="Public website URL to clone, e.g. https://www.example.com",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory where the cloned static site will be written",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=45,
        help="Per-request timeout in seconds (default: 45)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=100,
        help="Maximum number of HTML pages to crawl (default: 100)",
    )
    return parser.parse_args(list(argv))


def main(argv: Iterable[str]) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output_dir).resolve()
    manifest = clone_site(
        base_url=args.base_url,
        output_dir=output_dir,
        timeout=args.timeout,
        max_pages=args.max_pages,
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
