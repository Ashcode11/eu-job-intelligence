"""Text helpers shared by connectors: HTML to text, experience and remote-type extraction."""

import html
import re
from html.parser import HTMLParser

from common.enums import RemoteType

_BLOCK_TAGS = {
    "p",
    "div",
    "br",
    "li",
    "ul",
    "ol",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "tr",
    "section",
    "article",
    "header",
    "footer",
    "table",
}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(value: str | None, *, escaped: bool = False) -> str:
    """Convert (optionally entity-escaped, as Greenhouse returns) HTML to readable text."""
    if not value:
        return ""
    if escaped:
        value = html.unescape(value)
    parser = _TextExtractor()
    parser.feed(value)
    parser.close()
    text = "".join(parser.parts).replace("\xa0", " ")
    lines = [" ".join(line.split()) for line in text.splitlines()]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


_YEARS = re.compile(
    r"(?<![\d.])(\d{1,2})\s*(?:\+|plus)?\s*(?:-|–|to)?\s*(?:\d{1,2}\s*)?\+?\s*"
    r"(?:years?|yrs?|jahre?n?)\b(?:\s+of)?(?:\s+(?:professional|relevant|hands-on|proven|"
    r"industry|working|work))*\s*(?:experience|exp\b|erfahrung|berufserfahrung)?",
    re.IGNORECASE,
)


def extract_min_years(text: str) -> float | None:
    """Smallest plausible 'N+ years (of experience)' figure in a description, or None.

    Only matches followed by an experience word count, so "founded 10 years ago" is ignored.
    """
    candidates = []
    for m in _YEARS.finditer(text or ""):
        tail = m.group(0).lower()
        if any(w in tail for w in ("experience", "exp", "erfahrung")):
            years = int(m.group(1))
            if 1 <= years <= 25:
                candidates.append(years)
    return float(min(candidates)) if candidates else None


def detect_remote_type(*texts: str | None) -> RemoteType:
    joined = " ".join(t for t in texts if t).lower()
    if not joined:
        return RemoteType.UNKNOWN
    if "hybrid" in joined:
        return RemoteType.HYBRID
    if re.search(r"\b(fully remote|100% remote|remote[- ]first|remote)\b", joined):
        return RemoteType.REMOTE
    if re.search(r"\b(on-?site|in office|office-based)\b", joined):
        return RemoteType.ONSITE
    return RemoteType.UNKNOWN


_WORD = re.compile(r"[a-z0-9+#]+")


def title_matches(title: str, keywords: list[str], excluded: list[str] | None = None) -> bool:
    """True if every word of any keyword appears in the title (any order), and no excluded
    keyword does. 'cloud architect' matches 'Senior Cloud Solutions Architect'."""
    words = set(_WORD.findall(title.lower()))
    for ex in excluded or []:
        ex_words = set(_WORD.findall(ex.lower()))
        if ex_words and ex_words <= words:
            return False
    if not keywords:
        return True
    return any(
        (kw_words := set(_WORD.findall(kw.lower()))) and kw_words <= words for kw in keywords
    )
