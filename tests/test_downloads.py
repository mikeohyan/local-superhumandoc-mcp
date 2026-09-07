"""The tokenless download hop, and telling a real body from an error.

`Downloader` is the only client in this codebase that talks to a host other
than the API: no bearer token, no rate-limit bucket, and a different failure
shape than anything `client.py` handles. These tests pin the three things
that make a downloaded body unusable -- and, as importantly, the two things
that look like failures but are not: an XML declaration with no `<Error`
element (legitimate XHTML), and an empty body (a blank canvas page).
"""

import httpx2
import pytest

from superhumandoc_mcp.deadline import Deadline
from superhumandoc_mcp.downloads import Downloader
from superhumandoc_mcp.errors import DownloadUnusable


def _downloader(handler) -> Downloader:
    return Downloader(transport=httpx2.MockTransport(handler))


def _responding(status: int, body: str):
    def handler(request):
        return httpx2.Response(status, text=body)
    return handler


async def test_a_good_body_comes_back_as_text():
    assert "# A heading" in await _downloader(
        _responding(200, "# A heading\n\nSome text.")
    ).fetch("https://s3/x", Deadline())


async def test_the_download_carries_no_authorization_header():
    """The URL is pre-signed and the host is not the API's. A bearer token
    sent to a third party has left this process, and nothing downstream could
    tell that it had."""
    seen = {}

    def handler(request):
        seen.update(request.headers)
        return httpx2.Response(200, text="body")

    await _downloader(handler).fetch("https://s3/x", Deadline())
    assert "authorization" not in {k.lower() for k in seen}


@pytest.mark.parametrize(
    "status,body",
    [
        (403, '<?xml version="1.0"?><Error><Code>AccessDenied</Code></Error>'),
        (403, '<?xml version="1.0"?><Error><Code>SignatureDoesNotMatch</Code></Error>'),
        (200, '<?xml version="1.0"?><Error><Code>NoSuchKey</Code></Error>'),
        (200, '<Error><Code>NoSuchKey</Code></Error>'),
    ],
)
async def test_an_error_document_is_refused_however_it_is_dressed(status, body):
    """A dead link answers with XML under a 403 or a 200 -- both observed. The
    200 is the dangerous one: nothing about the response says failure except
    the body, so returning it unchecked would hand a model an XML error
    document and call it the page. The fourth case carries no XML declaration,
    which is how the earliest recorded form was quoted."""
    with pytest.raises(DownloadUnusable):
        await _downloader(_responding(status, body)).fetch("https://s3/x", Deadline())


@pytest.mark.parametrize("status,body", [(500, "upstream boom"), (503, "")])
async def test_a_failing_status_is_refused_whatever_the_body_says(status, body):
    """The XML check alone passes these straight through as the page. A 500
    with a plaintext body, or an error page from something in front of the
    bucket, is not content -- and the failure is silent, surfacing as wrong
    content rather than as an error."""
    with pytest.raises(DownloadUnusable):
        await _downloader(_responding(status, body)).fetch("https://s3/x", Deadline())


async def test_leading_whitespace_does_not_hide_an_error_document():
    """The check is on the first non-space characters, not on byte zero."""
    with pytest.raises(DownloadUnusable):
        await _downloader(
            _responding(200, '\n  <?xml version="1.0"?><Error/>')
        ).fetch("https://s3/x", Deadline())


async def test_a_page_that_merely_mentions_xml_is_not_refused():
    """The discriminator is the prefix plus an Error element, not a substring.
    A page whose content happens to contain `<?xml` further in is content."""
    assert "snippet" in await _downloader(
        _responding(200, "Here is a snippet: <?xml ... ?>")
    ).fetch("https://s3/x", Deadline())


async def test_an_xml_declaration_without_an_error_element_is_content():
    """XHTML may legitimately open with a declaration. Refusing on the prefix
    alone would make such a page permanently unreadable and report it as a link
    failure, which is the wrong place to go looking."""
    body = '<?xml version="1.0"?><html><body><p>Real page</p></body></html>'
    assert "Real page" in await _downloader(_responding(200, body)).fetch(
        "https://s3/x", Deadline()
    )


async def test_an_empty_body_is_content_not_a_failure():
    """A blank canvas page exports to nothing. Treating empty as an error would
    make an empty page unreadable, and a caller could not tell that from a
    broken link."""
    assert await _downloader(_responding(200, "")).fetch(
        "https://s3/x", Deadline()
    ) == ""


async def test_a_refusal_never_repeats_the_link_s_signature():
    """A download link is pre-signed: its query carries X-Amz-Credential and
    X-Amz-Signature, which together grant read access to the blob until the
    link expires. That is a credential, and a refusal's text is the first
    thing this client repeats to a model -- the same reason the API client
    redacts its bearer token out of an upstream refusal's detail.

    The path survives, because it says which object failed and that is what a
    reader needs.
    """
    signed = (
        "https://coda-us-west-2-prod-workflow-objects.s3.us-west-2.amazonaws.com"
        "/DOC_EXPORT_RENDERING/page-x/doc-y"
        "?X-Amz-Credential=ASIAQNTH22RI577ZUYAW%2F20260907%2Fus-west-2"
        "&X-Amz-Signature=deadbeefcafe&X-Amz-Expires=300"
    )
    with pytest.raises(DownloadUnusable) as caught:
        await _downloader(_responding(403, "<Error><Code>AccessDenied</Code></Error>")).fetch(
            signed, Deadline()
        )
    message = str(caught.value)
    assert "X-Amz-Signature" not in message
    assert "X-Amz-Credential" not in message
    assert "deadbeefcafe" not in message
    assert "DOC_EXPORT_RENDERING/page-x/doc-y" in message

