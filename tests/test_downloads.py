"""The tokenless download hop, and telling a real body from an error.

`Downloader` is the only client in this codebase that talks to a host other
than the API: no bearer token, no rate-limit bucket, and a different failure
shape than anything `client.py` handles. These tests pin the things that make
a downloaded body unusable -- and, as importantly, the things that look like
failures but are not: an XML declaration with no `<Error` element (legitimate
XHTML), and an empty body (a blank canvas page).
"""

import gzip

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


@pytest.mark.parametrize(
    "status,body",
    [
        (500, "upstream boom"),
        (503, ""),
        (404, "Not Found"),
        (400, "plain text bad request"),
        (502, "<html><body>Bad Gateway</body></html>"),
    ],
)
async def test_a_failing_status_is_refused_whatever_the_body_says(status, body):
    """The XML check alone passes these straight through as the page. A 500
    with a plaintext body, or an error page from something in front of the
    bucket, is not content -- and the failure is silent, surfacing as wrong
    content rather than as an error. The 4xx cases pin that the status check
    covers the whole non-2xx range, not just 5xx: a 4xx with a body that is
    neither XML nor an S3 error document must still be refused on status
    alone."""
    with pytest.raises(DownloadUnusable):
        await _downloader(_responding(status, body)).fetch("https://s3/x", Deadline())


@pytest.mark.parametrize(
    "status,body",
    [
        (100, ""),
        (199, "still not content"),
        (300, ""),
        (307, ""),
        (399, "not content either"),
    ],
)
async def test_an_informational_or_redirect_status_is_also_refused(status, body):
    """The status check is a band with two pinned edges, not a floor: `httpx2`
    does not follow redirects by default, so a 3xx -- an S3 region redirect,
    say -- arrives here as a response like any other, with its own body and no
    exception raised by the transport. A check that only rejects >= 400 (or
    even >= 300, missing the 1xx side) would hand a redirect's or an
    informational response's body to the model as though it were the page --
    the exact silent-wrong-content failure this module exists to prevent.
    Neither of these bodies is XML or an S3 error document, so only the status
    check can be what refuses them.
    """
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


@pytest.mark.parametrize(
    "body",
    [
        (
            "```python\n"
            "response = client.get(url)\n"
            'if response.text.startswith("<Error"):\n'
            '    raise ValueError("bad response")\n'
            "```\n"
        ),
        (
            "# Handling S3 Errors\n\n"
            "When a request fails, S3 returns a body starting with "
            "`<Error>` followed by an error code such as AccessDenied or "
            "NoSuchKey.\n\n"
            "Always check the status code first before parsing the body."
        ),
    ],
)
async def test_a_page_that_mentions_the_error_tag_mid_body_is_not_refused(body):
    """The discriminator is the *prefix*, not a substring search anywhere in
    the body: a code sample or a documentation page discussing XML error
    handling is exactly the realistic case where `<Error` appears well away
    from the first non-space character while the page is still genuine
    content, not an S3 error document. Neither fixture here starts with
    `<Error` or `<?xml`, so a check that instead asked "does `<Error` appear
    anywhere" would refuse both -- silently making them permanently
    unreadable and misreporting a real page as a broken link.
    """
    assert await _downloader(_responding(200, body)).fetch(
        "https://s3/x", Deadline()
    ) == body


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
    """A download link is pre-signed. `docs/reference/api-operational-constants.md`
    section 2.5 records the download host as `docs.superhuman.com/blobs/...`,
    and probe P5b (`docs/validation/2026-09-03-api-operational-probes.md`) is
    the only place any query parameters were directly observed on a real
    signed link: `X-Amz-Date` and `X-Amz-Expires`. Neither probe nor the
    reference doc ever recorded `X-Amz-Credential` or `X-Amz-Signature` on
    this link -- so this fixture asserts against the recorded shape, not an
    invented one, while still pinning the actual point: `_without_signature`
    strips the whole query string regardless of what is in it, so no query
    parameter -- named or not -- ever reaches a refusal message, and neither
    does a value drawn from the query.
    """
    signed = (
        "https://docs.superhuman.com/blobs/DOC_EXPORT_RENDERING/page-x/doc-y"
        "?X-Amz-Date=20260904T010143Z&X-Amz-Expires=300"
    )
    with pytest.raises(DownloadUnusable) as caught:
        await _downloader(_responding(403, "<Error><Code>AccessDenied</Code></Error>")).fetch(
            signed, Deadline()
        )
    message = str(caught.value)
    assert "X-Amz-Date" not in message
    assert "X-Amz-Expires" not in message
    assert "20260904T010143Z" not in message
    assert "DOC_EXPORT_RENDERING/page-x/doc-y" in message


async def test_the_reserved_tail_is_spent_on_the_terminal_fetch():
    """`deadline.py` reserves a tail specifically so the terminal download can
    spend it: `remaining_with_tail()` includes the reserve, `remaining()`
    does not. Pin that `fetch` passes the former, not the latter, to the
    underlying `get` -- swapping to `remaining()` would silently shrink every
    download's timeout by the whole reserved tail and leaves every other test
    here passing.
    """
    seen_timeout = {}

    def handler(request):
        seen_timeout.update(request.extensions["timeout"])
        return httpx2.Response(200, text="body")

    deadline = Deadline(total_s=100.0, reserved_tail_s=10.0, clock=lambda: 0.0)
    await _downloader(handler).fetch("https://s3/x", deadline)

    assert seen_timeout["read"] == deadline.remaining_with_tail() == 100.0
    assert deadline.remaining() == 90.0
    assert seen_timeout["read"] != deadline.remaining()


async def test_a_transport_failure_is_raised_as_download_unusable():
    """A timeout, connect failure, or protocol error from `self._http.get`
    used to propagate raw: `export_page`'s `except DownloadUnusable` could not
    catch it, so no link re-mint was attempted, and `tool_boundary` could not
    catch it either since it is not a `ClientError`. This is the most likely
    download failure, not an exotic one, because the timeout passed to `get`
    is `deadline.remaining_with_tail()` -- a slow export leaves a short fuse
    on exactly this call.
    """

    def handler(request):
        raise httpx2.ReadTimeout("timed out", request=request)

    with pytest.raises(DownloadUnusable):
        await _downloader(handler).fetch("https://s3/x", Deadline())


async def test_a_transport_failure_does_not_repeat_the_link_s_signature():
    """The same credential-leak rule applies to a transport failure's message
    as to a status or S3-error refusal: the URL passed through must be the
    one with its query string stripped."""
    signed = "https://docs.superhuman.com/blobs/DOC_EXPORT_RENDERING/page-x/doc-y?X-Amz-Date=20260904T010143Z&X-Amz-Expires=300"

    def handler(request):
        raise httpx2.ConnectError("connection refused", request=request)

    with pytest.raises(DownloadUnusable) as caught:
        await _downloader(handler).fetch(signed, Deadline())
    message = str(caught.value)
    assert "X-Amz-Date" not in message
    assert "20260904T010143Z" not in message
    assert "DOC_EXPORT_RENDERING/page-x/doc-y" in message


async def test_a_gzip_encoded_body_decodes_before_the_error_check():
    """`docs/reference/api-operational-constants.md` section 2.5 records that
    every real successful download arrives `Content-Encoding: gzip`, and that
    httpx2 selects a decoder from that header before `.text` (or `.content`,
    or `.json()`) is read -- only `iter_raw`/`aiter_raw` see the compressed
    bytes. This builds a genuinely gzip-encoded response (compressed bytes
    plus the header, not `text=`) through the same `MockTransport` every other
    test here uses, to confirm real decoding happens through this transport
    rather than merely through the test doubles that pass `text=` directly.
    """
    payload = "# A heading\n\nSome text."

    def handler(request):
        return httpx2.Response(
            200,
            content=gzip.compress(payload.encode()),
            headers={"Content-Encoding": "gzip", "Content-Type": "text/plain"},
        )

    result = await _downloader(handler).fetch("https://s3/x", Deadline())
    assert result == payload

