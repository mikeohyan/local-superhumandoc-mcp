"""The export poll loop: one bounded wait for a `downloadLink` or an `error`.

A kickoff `POST` returns an id; this is what turns that into page content. The
`async-operations` topic sets the loop's shape — wait, poll on a backing-off
interval, stop on a terminal answer or a deadline — the same shape
`polling.py`'s mutation loop uses, with export's own constants and its own
terminal conditions. Where the two differ: the terminal signal here is
`downloadLink` or `error`, never `status`; a `410` ends the wait at once with
no grace window, where a `404` still gets one; and a link that fails its body
check is re-minted by re-entering this same loop — sharing its grace window
and its ceiling — rather than by running a second ladder beside it. See
`_rfc/README.md`.
"""

from collections.abc import Awaitable, Callable

from superhumandoc_mcp.deadline import Deadline
from superhumandoc_mcp.errors import ClientError, DownloadUnusable, UpstreamRefused

EXPORT_INITIAL_SLEEP_S = 2.0
EXPORT_POLL_INTERVAL_S = 2.0
EXPORT_POLL_BACKOFF = 1.5
EXPORT_POLL_MAX_INTERVAL_S = 15.0
EXPORT_404_GRACE_S = 20.0
EXPORT_DEADLINE_S = 45.0
EXPORT_MAX_LINK_REFRESH = 2


async def export_page(
    api,
    downloader,
    page: str,
    output_format: str,
    deadline: Deadline,
    *,
    clock: Callable[[], float],
    sleep: Callable[[float], Awaitable[None]],
) -> str:
    """Kick off an export and poll it to a body, or to a bounded give-up.

    The poll itself always runs at least once after the opening sleep, rather
    than being gated by the same ceiling check that ends the loop: a call made
    with almost no budget left must still get to ask its one question, or a
    tool call placed near its own deadline could never export anything at
    all. Everything after that first question is bounded the usual way.

    The operation's own ceiling never extends the tool call's: `clamp` takes
    the lesser, so a deadline with less than `EXPORT_DEADLINE_S` left still
    governs. A 404 is caught here, around each status call, rather than inside
    the transport's classifier, for the same reason the mutation loop does
    this: that table is uniform with no per-endpoint carve-out, and a 404
    within `EXPORT_404_GRACE_S` of the first poll is replication lag on the
    status endpoint, not evidence the export never happened. A 410 gets no
    such benefit of the doubt — it is declared on this endpoint and means the
    resource existed and is gone, so it falls straight into the same "not a
    404-in-grace" branch that ends the wait immediately.
    """
    kickoff = await api.begin_export(page, output_format, deadline)
    request_id = kickoff.get("id")
    if request_id is None:
        raise ClientError(
            f"the export kickoff for page {page!r} did not return an id, so "
            "there is nothing to poll"
        )

    started = clock()
    ceiling = started + deadline.clamp(EXPORT_DEADLINE_S)
    grace_ends = started + EXPORT_404_GRACE_S
    interval = EXPORT_POLL_INTERVAL_S
    refreshes = 0

    # Clamped like every other subordinate wait. Unclamped, this is the sleep
    # that would run before any loop condition is even checked and so could
    # overshoot straight into the reserved tail before a single question is
    # asked.
    await sleep(deadline.clamp(EXPORT_INITIAL_SLEEP_S))
    while True:
        try:
            body = await api.get_export_status(page, request_id, deadline)
        except UpstreamRefused as refusal:
            if refusal.status == 404 and clock() < grace_ends:
                pass  # not yet: the status has not replicated
            else:
                raise ClientError(
                    f"the export for page {page!r} could not be completed: "
                    f"{refusal}"
                ) from refusal
        except ClientError as failure:
            raise ClientError(
                f"the export for page {page!r} could not be completed: "
                f"{failure}"
            ) from failure
        else:
            # Truthiness, not presence. The mutation status endpoint was
            # measured returning `warning` absent rather than null, but
            # nothing establishes which way this field goes, and `"error" in
            # body` would turn an explicit null into a failure reported as
            # "failed: None" -- an export that succeeded, refused, with no
            # reason a reader could act on.
            if body.get("error"):
                raise ClientError(
                    f"the export for page {page!r} failed: {body['error']}"
                )
            link = body.get("downloadLink")
            if link:
                try:
                    return await downloader.fetch(link, deadline)
                except DownloadUnusable:
                    # A link expires in about five minutes while the file
                    # behind it lives for days, so a stale link is the
                    # likeliest cause of a late failure -- and the spec
                    # sanctions asking again: "Call this method again to get
                    # a fresh link." Re-entering this same loop, rather than
                    # running a second ladder beside it, is what gives a
                    # re-mint poll the same 404 grace window as any other.
                    refreshes += 1
                    if refreshes > EXPORT_MAX_LINK_REFRESH:
                        raise ClientError(
                            f"the download link for page {page!r} could not "
                            "be used even after being re-minted "
                            f"{EXPORT_MAX_LINK_REFRESH} times"
                        ) from None
        if clock() >= ceiling:
            raise ClientError(
                f"the export for page {page!r} did not complete within the "
                "export deadline"
            )
        if not deadline.can_afford(interval):
            # Said separately from the ceiling above, because they are
            # different facts and a reader acts on them differently: one means
            # the export is slow, the other that this tool call had other work
            # to pay for first.
            raise ClientError(
                f"the export for page {page!r} was still running when this "
                "tool call ran out of time"
            )
        await sleep(interval)
        interval = min(interval * EXPORT_POLL_BACKOFF, EXPORT_POLL_MAX_INTERVAL_S)
