"""The tokenless download hop, and telling a body from an error.

The only place in this client that talks to a host other than the API, and it
shares none of `client.py`'s policy: no `Authorization` header, because the
URL is pre-signed and the host is Amazon's, and a credential sent to a third
party has left the process; no rate-limit bucket, because the buckets belong
to the API and this request never reaches it; and no 429 ladder, because S3
does not speak the API's retry conventions. The `async-operations` topic
records why the download is a separate hop on a separate host.
"""

import httpx2

from superhumandoc_mcp.deadline import Deadline
from superhumandoc_mcp.errors import DownloadUnusable


class Downloader:
    def __init__(self, transport: httpx2.AsyncBaseTransport | None = None) -> None:
        self._http = httpx2.AsyncClient(transport=transport)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def fetch(self, url: str, deadline: Deadline) -> str:
        """Read the body behind an already-minted download link.

        The timeout is `deadline.remaining_with_tail()`, not `remaining()`:
        `deadline.py` reserves the tail for exactly this case, the terminal
        fetch of a result the rest of the budget already paid for. A download
        with no timeout, or one that ignored the tail, could pin a global
        concurrency slot forever -- and with a fixed number of slots shared
        across every export, that is enough to wedge every later `read_page`.

        Three things make the response unusable, not one: a non-2xx status,
        whatever the body says; an S3 error document, however it is dressed;
        and nothing else -- an empty body is content, not a failure. httpx2
        decodes `Content-Encoding` transparently for `.text`, and a good body
        decodes to readable markdown or HTML while an error body is plain
        XML, so `.text` is the right thing to check for both; nothing here
        needs the raw byte stream.
        """
        response = await self._http.get(
            url, timeout=deadline.remaining_with_tail()
        )
        if not (200 <= response.status_code < 300):
            raise DownloadUnusable(
                _without_signature(url),
                f"the download responded with HTTP {response.status_code}.",
            )
        text = response.text
        if _is_s3_error_document(text):
            raise DownloadUnusable(
                _without_signature(url),
                "the link answered with an S3 error document instead of the "
                "page.",
            )
        return text


def _without_signature(url: str) -> str:
    """The link with its query string removed.

    A download link is pre-signed: its query carries `X-Amz-Credential` and
    `X-Amz-Signature`, which together grant anyone holding them read access to
    the blob until the link expires. That is a credential, and a refusal's text
    is the first thing this client repeats to a model, so the query never goes
    into one — the same rule the API client applies to the bearer token. What
    is left still identifies which object failed, which is all a reader needs.
    """
    return url.split("?", 1)[0]


def _is_s3_error_document(text: str) -> bool:
    """Told apart from a good body by its first non-space characters, not by
    a substring search anywhere in it: a page may legitimately contain or
    even open with `<?xml` (XHTML does, at its very start) without being an
    error, so the prefix alone is not enough -- the `<Error` element is what
    makes it one.
    """
    stripped = text.lstrip()
    return stripped.startswith("<Error") or (
        stripped.startswith("<?xml") and "<Error" in stripped
    )
