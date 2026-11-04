"""Text helpers shared by the board standardisers, the checks and the evaluation."""

import hashlib
import html
import re
import unicodedata

from bs4 import BeautifulSoup

_BLOCK_TAGS = ["p", "div", "section", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "table", "tr"]

_CHAR_MAP = {
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2015": "-",
    "\u2212": "-",
}


def html_to_text(raw: str, escaped: bool = False) -> str:
    """Turn board HTML into plain text, one block per line, with "- " before list items."""
    if escaped:
        raw = html.unescape(raw)
    soup = BeautifulSoup(raw, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.insert_before("\n")
        tag.insert_after("\n")
    for item in soup.find_all("li"):
        item.insert_before("\n- ")
    lines = [re.sub(r"[ \t\u00a0]+", " ", line).strip() for line in soup.get_text().splitlines()]
    kept: list[str] = []
    for line in lines:
        if line or (kept and kept[-1]):
            kept.append(line)
    return "\n".join(kept).strip()


def _normalise_char(ch: str) -> str:
    return unicodedata.normalize("NFKC", _CHAR_MAP.get(ch, ch)).lower()


def _normalise_with_index(text: str) -> tuple[str, list[int]]:
    """Normalise text and record, for each output character, the index of its input character."""
    chars: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text):
        for out in _normalise_char(ch):
            if out.isspace():
                if not chars or chars[-1] == " ":
                    continue
                out = " "
            chars.append(out)
            index.append(i)
    while chars and chars[-1] == " ":
        chars.pop()
        index.pop()
    return "".join(chars), index


def normalise_for_match(text: str) -> str:
    """Lower case, NFKC, straight quotes and hyphens, single spaces, trimmed."""
    return _normalise_with_index(text)[0]


def find_quote(text: str, quote: str) -> tuple[int, int] | None:
    """Find quote in text, ignoring case, spacing, quote style and hyphen style.

    Returns the (start, end) span in the original text, or None if the quote is empty or absent.
    """
    needle = normalise_for_match(quote)
    if not needle:
        return None
    haystack, index = _normalise_with_index(text)
    pos = haystack.find(needle)
    if pos < 0:
        return None
    return index[pos], index[pos + len(needle) - 1] + 1


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
