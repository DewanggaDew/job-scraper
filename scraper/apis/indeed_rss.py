from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote_plus


def build_indeed_rss_url(domain: str, title: str, location: str) -> str:
    """
    Indeed search RSS.

    Regional hosts often return 404 on ``/rss``; the global host usually serves
    the feed with ``l=`` set to the country or city (same as the HTML search UI).
    """
    _ = domain  # Kept for call-site symmetry with HTML search config.
    return (
        "https://www.indeed.com/rss"
        f"?q={quote_plus(title)}"
        f"&l={quote_plus(location)}"
    )


@dataclass
class IndeedRssItem:
    title: str
    link: str
    description: str
    pub_date: str


def parse_indeed_rss(xml_text: str) -> list[IndeedRssItem]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    # RSS 2.0: channel/item; tolerate default namespace
    items: list[IndeedRssItem] = []
    for el in root.iter():
        if el.tag.endswith("item") or el.tag == "item":
            title = _child_text(el, "title")
            link = _child_text(el, "link")
            if not title or not link:
                continue
            items.append(
                IndeedRssItem(
                    title=title.strip(),
                    link=link.strip(),
                    description=_child_text(el, "description"),
                    pub_date=_child_text(el, "pubDate"),
                )
            )
    return items


def _child_text(parent: ET.Element, tag_suffix: str) -> str:
    for child in parent:
        if child.tag.endswith(tag_suffix) or child.tag == tag_suffix:
            return (child.text or "").strip()
    return ""
