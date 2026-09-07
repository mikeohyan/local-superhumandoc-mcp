"""HTML page content: format and refusal rules."""

import pytest

from superhumandoc_mcp.content import ContentRefused, canvas_content
from superhumandoc_mcp.errors import ClientError


def test_content_is_sent_as_html():
    """Page content is always written as HTML, never markdown."""
    assert canvas_content("<p>hi</p>") == {"format": "html",
                                           "content": "<p>hi</p>"}


def test_an_img_tag_is_refused_and_says_why():
    """It degrades to a link. Silently substituting one for the other is the
    failure this rule exists to prevent."""
    with pytest.raises(ContentRefused) as caught:
        canvas_content('<p><img src="x.png"></p>')
    assert "link" in str(caught.value)


def test_markdown_image_syntax_is_refused_too():
    """The format is HTML; a caller reaching for this has misunderstood and
    would get a link rather than the image they asked for."""
    with pytest.raises(ContentRefused):
        canvas_content("![alt](x.png)")


def test_an_oversized_body_is_refused_never_split():
    """A page body has no natural split point that preserves meaning."""
    with pytest.raises(ContentRefused) as caught:
        canvas_content("<p>" + "x" * 800_000 + "</p>")
    assert "split" in str(caught.value).lower()


def test_a_refusal_reaches_the_model_rather_than_being_redacted():
    """It is a ClientError, so the tool boundary translates it. A bare
    exception would be redacted to 'Error executing tool'."""
    assert issubclass(ContentRefused, ClientError)
