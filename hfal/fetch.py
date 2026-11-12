"""
Step 1: visit a hospital's financial assistance (HFA) page and collect documents.

We use Playwright (a real Chromium browser driven by Python) because many
hospital sites build their pages with JavaScript, block simple scripts, or have
SSL setups that older Python versions can't talk to.

For each HFA link we save:
  * the landing page text
  * every linked PDF / Word file that looks like financial-assistance material
  * same-site pages one click away that look relevant (and PDFs linked from them)
Everything is written to data/cache/<site>/ so a human can check what the AI saw.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urldefrag, urlparse

import config

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

KEYWORDS = [
    "financial assistance", "financial-assistance", "financial aid", "financial-aid",
    "charity", "uniform", "plain language", "plain-language", "summary", "policy",
    "application", "apply", "hfa", "fap", "pls", "assistance", "discount",
    "sliding", "uninsured", "self-pay", "billing", "payment plan",
]
STRONG = ["financial assistance", "financial-assistance", "financial aid", "financial-aid",
          "charity", "uniform", "plain language", "plain-language", "fap", "hfa"]
SKIP = ["mailto:", "tel:", "javascript:", "facebook.", "twitter.", "x.com/", "linkedin.",
        "instagram.", "youtube.", "mychart", "login", "careers", "jobs", "donate",
        "price-transparency", "standard-charges", "standardcharges", "chargemaster",
        ".csv", ".json", ".xml", ".zip", "google.com/maps"]
FILE_EXT = (".pdf", ".doc", ".docx")

# Link text -> language. Used so the AI knows which translations are posted.
LANGUAGES = {
    "spanish": "Spanish", "español": "Spanish", "espanol": "Spanish",
    "chinese": "Chinese", "中文": "Chinese", "简体": "Chinese", "繁體": "Chinese", "mandarin": "Chinese", "cantonese": "Chinese",
    "russian": "Russian", "русский": "Russian",
    "haitian": "Haitian Creole", "kreyòl": "Haitian Creole", "kreyol": "Haitian Creole", "creole": "Haitian Creole",
    "korean": "Korean", "한국어": "Korean",
    "bengali": "Bengali", "বাংলা": "Bengali", "bangla": "Bengali",
    "yiddish": "Yiddish", "ייִדיש": "Yiddish",
    "polish": "Polish", "polski": "Polish",
    "italian": "Italian", "italiano": "Italian",
    "arabic": "Arabic", "العربية": "Arabic",
    "french": "French", "français": "French",
    "urdu": "Urdu", "اردو": "Urdu",
    "vietnamese": "Vietnamese", "tiếng việt": "Vietnamese",
    "tagalog": "Tagalog", "albanian": "Albanian", "greek": "Greek", "hindi": "Hindi",
    "japanese": "Japanese", "nepali": "Nepali", "burmese": "Burmese", "karen": "Karen",
    "somali": "Somali", "swahili": "Swahili", "ukrainian": "Ukrainian", "punjabi": "Punjabi",
    "portuguese": "Portuguese", "farsi": "Farsi", "pashto": "Pashto", "dari": "Dari",
}


@dataclass
class Document:
    doc_id: str                 # D1, D2, ... (D1 is always the landing page)
    url: str
    link_text: str
    kind: str                   # html | pdf | docx
    text: str = ""
    pages: int = 0
    language_hint: Optional[str] = None   # from the link text, e.g. "Spanish"
    scanned: bool = False       # PDF with no text layer -> AI reads it as an image
    file_path: Optional[str] = None
    sha256: str = ""
    error: Optional[str] = None


@dataclass
class SiteFetch:
    hfa_url: str
    fetched_at: str
    landing_ok: bool
    error: Optional[str] = None
    documents: list[Document] = field(default_factory=list)
    skipped_links: list[str] = field(default_factory=list)  # relevant links over the cap

    def fingerprint(self) -> str:
        """Changes whenever any document's content changes."""
        h = hashlib.sha256()
        for d in sorted(self.documents, key=lambda d: d.url):
            h.update(d.url.encode()); h.update(d.sha256.encode())
        return h.hexdigest()


def site_slug(url: str) -> str:
    p = urlparse(url)
    base = re.sub(r"[^a-z0-9]+", "-", (p.netloc + p.path).lower()).strip("-")[:70]
    return f"{base}-{hashlib.sha1(url.encode()).hexdigest()[:6]}"


def _norm_hash(text: str) -> str:
    return hashlib.sha256(re.sub(r"\s+", " ", text).strip().encode()).hexdigest()


def _score(url: str, text: str) -> int:
    s = (url + " " + text).lower()
    return sum(1 for k in KEYWORDS if k in s) + 2 * sum(1 for k in STRONG if k in s)


def _language(text: str, url: str) -> Optional[str]:
    s = (text + " " + url).lower()
    for k, v in LANGUAGES.items():
        if re.search(rf"(?<![a-z]){re.escape(k)}(?![a-z])", s):
            return v
    return None


def _is_file(url: str, content_type: str = "") -> Optional[str]:
    path = urlparse(url).path.lower()
    if path.endswith(".pdf") or "pdf" in content_type:
        return "pdf"
    if path.endswith((".docx", ".doc")) or "wordprocessingml" in content_type or "msword" in content_type:
        return "docx"
    return None


def _pdf_text(data: bytes) -> tuple[str, int]:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    parts = []
    for i, page in enumerate(reader.pages, 1):
        try:
            parts.append(f"[page {i}]\n{page.extract_text() or ''}")
        except Exception:  # one broken page shouldn't lose the whole document
            parts.append(f"[page {i}]\n")
    return "\n".join(parts), len(reader.pages)


def _docx_text(data: bytes) -> str:
    import docx
    d = docx.Document(io.BytesIO(data))
    lines = [p.text for p in d.paragraphs]
    for t in d.tables:
        for r in t.rows:
            lines.append(" | ".join(c.text for c in r.cells))
    return "\n".join(lines)


class Fetcher:
    """Use as `with Fetcher() as f: f.fetch_site(url)` so the browser closes."""

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch()
        self._ctx = self._browser.new_context(user_agent=UA, ignore_https_errors=True,
                                              accept_downloads=False)
        self._ctx.set_default_timeout(config.PAGE_TIMEOUT_SECONDS * 1000)
        return self

    def __exit__(self, *exc):
        self._browser.close()
        self._pw.stop()

    # -------------------------------------------------------------- low level
    def _get_file(self, url: str) -> tuple[Optional[bytes], str]:
        r = self._ctx.request.get(url, timeout=config.PAGE_TIMEOUT_SECONDS * 1000)
        if not r.ok:
            raise RuntimeError(f"HTTP {r.status}")
        return r.body(), r.headers.get("content-type", "")

    def _render(self, url: str) -> tuple[str, list[dict], str]:
        """Open a web page like a person would; return (text, links, final_url)."""
        page = self._ctx.new_page()
        try:
            resp = page.goto(url, wait_until="domcontentloaded")
            if resp is not None and resp.status >= 400:
                raise RuntimeError(f"HTTP {resp.status}")
            try:
                page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass  # some sites never go fully idle; what we have is fine
            # expand accordions / "read more" sections so their text is captured
            page.evaluate("""() => document.querySelectorAll('details').forEach(d => d.open = true)""")
            text = page.inner_text("body")
            links = page.eval_on_selector_all(
                "a[href]",
                "els => els.map(e => ({href: e.href, text: (e.innerText || e.getAttribute('aria-label') || e.title || '').trim()}))",
            )
            return text, links, page.url
        finally:
            page.close()

    def _file_document(self, doc_id: str, url: str, link_text: str, save_dir: Path) -> Document:
        doc = Document(doc_id=doc_id, url=url, link_text=link_text, kind="pdf",
                       language_hint=_language(link_text, url))
        try:
            data, ctype = self._get_file(url)
            kind = _is_file(url, ctype)
            if kind is None and "html" in ctype:
                raise RuntimeError("link is a web page, not a file")
            doc.kind = kind or "pdf"
            ext = ".pdf" if doc.kind == "pdf" else ".docx"
            path = save_dir / f"{doc_id}{ext}"
            path.write_bytes(data)
            doc.file_path = str(path)
            if doc.kind == "pdf":
                doc.text, doc.pages = _pdf_text(data)
                real_chars = len(re.sub(r"\[page \d+\]|\s", "", doc.text))
                doc.scanned = doc.pages > 0 and real_chars / doc.pages < 100
            else:
                doc.text = _docx_text(data)
            doc.sha256 = hashlib.sha256(data).hexdigest() if doc.scanned else _norm_hash(doc.text)
        except Exception as e:
            doc.error = f"{type(e).__name__}: {str(e)[:200]}"
        return doc

    # -------------------------------------------------------------- main entry
    def fetch_site(self, hfa_url: str) -> SiteFetch:
        save_dir = config.CACHE_DIR / site_slug(hfa_url) / "files"
        save_dir.mkdir(parents=True, exist_ok=True)
        for old in save_dir.iterdir():
            old.unlink()
        site = SiteFetch(hfa_url=hfa_url, fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                         landing_ok=False)

        # The HFA link itself may point straight at a PDF.
        if _is_file(hfa_url):
            d = self._file_document("D1", hfa_url, "HFA link (file)", save_dir)
            site.documents.append(d)
            site.landing_ok = d.error is None
            site.error = d.error
            return site

        try:
            text, links, final_url = self._render(hfa_url)
        except Exception as e:
            site.error = f"Could not open HFA page: {type(e).__name__}: {str(e)[:200]}"
            return site
        site.landing_ok = True
        site.documents.append(Document("D1", final_url, "HFA landing page", "html", text=text,
                                       sha256=_norm_hash(text)))
        home = urlparse(final_url).netloc.replace("www.", "")

        seen = {urldefrag(final_url)[0], urldefrag(hfa_url)[0]}
        candidates: list[tuple[int, str, str, str]] = []  # (score, url, text, kind)

        def consider(link_list, from_subpage=False):
            for l in link_list:
                url = urldefrag(l["href"])[0]
                if not url.startswith("http") or url in seen or any(s in url.lower() for s in SKIP):
                    continue
                t = re.sub(r"\s+", " ", l["text"] or "")[:200]
                score = _score(url, t)
                is_file = _is_file(url) is not None
                lang = _language(t, url)
                if is_file and (score > 0 or lang):
                    seen.add(url)
                    # files linked straight from the HFA page are the most important
                    candidates.append((score + (0 if from_subpage else 5), url, t, "file"))
                elif (not is_file and not from_subpage and config.FOLLOW_SUBPAGES
                      and home in urlparse(url).netloc and any(k in (url + t).lower() for k in STRONG)):
                    seen.add(url)
                    candidates.append((score, url, t, "page"))

        consider(links)

        # Open relevant sub-pages and collect the files they link to.
        for score, url, t, kind in sorted([c for c in candidates if c[3] == "page"], reverse=True)[:6]:
            try:
                sub_text, sub_links, _ = self._render(url)
            except Exception as e:
                site.documents.append(Document(f"D{len(site.documents)+1}", url, t, "html", error=str(e)[:200]))
                continue
            site.documents.append(Document(f"D{len(site.documents)+1}", url, t, "html", text=sub_text,
                                           sha256=_norm_hash(sub_text)))
            consider(sub_links, from_subpage=True)

        files = sorted([c for c in candidates if c[3] == "file"], reverse=True)
        room = max(0, config.MAX_DOCUMENTS_PER_SITE - len(site.documents))
        for score, url, t, _ in files[:room]:
            site.documents.append(self._file_document(f"D{len(site.documents)+1}", url, t, save_dir))
        site.skipped_links = [u for _, u, _, _ in files[room:]]

        return site


# ---------------------------------------------------------------- cache helpers
def save_site(site: SiteFetch) -> Path:
    path = config.CACHE_DIR / site_slug(site.hfa_url) / "documents.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(site), indent=1, ensure_ascii=False))
    return path


def load_site(hfa_url: str) -> Optional[SiteFetch]:
    path = config.CACHE_DIR / site_slug(hfa_url) / "documents.json"
    if not path.exists():
        return None
    raw = json.loads(path.read_text())
    raw["documents"] = [Document(**d) for d in raw["documents"]]
    return SiteFetch(**raw)
