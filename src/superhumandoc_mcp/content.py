"""HTML page content: format and refusal rules.

The tool surface writes page content as HTML, never markdown. This module
validates HTML before sending and refuses patterns that would degrade.
"""

import re

from superhumandoc_mcp.errors import ContentRefused

# Page content size limit, set by the `request-sizing` topic and tabulated in
# docs/reference/api-operational-constants.md §1.2. No published page-content
# limit exists; this is the byte count that stays under the request cap once
# the body is expanded into the document's internal representation.
MAX_PAGE_CONTENT_BYTES = 700_000


def canvas_content(html: str) -> dict:
    """Produce a `canvasContent` payload for a page-content write.

    The `format` is always `"html"`, never markdown, set by the `tool-surface`
    topic. `docs/reference/api-operational-constants.md` records why: of the
    two formats a page write accepts, only HTML preserves a table's header
    row, which markdown demotes to data.

    Raises `ContentRefused` on image syntax in either notation, and on a body
    over `MAX_PAGE_CONTENT_BYTES`. An oversized page body is refused rather
    than split, because unlike a batch of rows a page has no split point that
    preserves its meaning — the `request-sizing` topic makes that distinction
    explicitly.
    """
    # An <img> written into page content is dropped outright — measured, and
    # the more dangerous of the two image failures, because nothing is left
    # behind to show that something went missing.
    if _contains_html_img(html):
        raise ContentRefused(
            "Page content contains an <img> tag. An image written this way is "
            "dropped from the page entirely — not even a link is left behind, "
            "so the loss is invisible afterwards. Write an <a href=\"...\"> "
            "link to the image instead, so the reference survives."
        )

    # Markdown image syntax in an HTML body is not an image at all: it is
    # literal text. The caller has the format wrong, and would get neither the
    # image they asked for nor an error from the API.
    if _contains_markdown_img(html):
        raise ContentRefused(
            "Page content uses markdown image syntax ![alt](url), but this "
            "content is written as HTML, where that is literal text rather "
            "than an image. Write HTML — and for an image, an <a href=\"...\"> "
            "link, since an <img> tag is dropped on write."
        )

    # Refuse oversized body: page content has no split point that preserves
    # meaning, so over-cap bodies cannot be split and chunked like rows.
    if len(html.encode("utf-8")) > MAX_PAGE_CONTENT_BYTES:
        raise ContentRefused(
            f"Page content is {len(html.encode('utf-8'))} bytes, exceeding the "
            f"{MAX_PAGE_CONTENT_BYTES}-byte limit. The page body has no split "
            "point that preserves meaning, so it cannot be split and retried."
        )

    return {"format": "html", "content": html}


def _contains_html_img(html: str) -> bool:
    """Check if the HTML contains an `<img>` tag.

    Matches the opening tag pattern `<img`, case-insensitive, not the full
    element so as to catch malformed or unusual spellings without parsing.
    """
    return bool(re.search(r"<\s*img\b", html, re.IGNORECASE))


def _contains_markdown_img(html: str) -> bool:
    """Check if the text contains markdown image syntax `![alt](url)`.

    Matches the pattern `![...](...)`; does not validate that the brackets are
    balanced or that the content is well-formed, only that the syntax appears.
    """
    return bool(re.search(r"!\[[^\]]*\]\([^)]*\)", html))
