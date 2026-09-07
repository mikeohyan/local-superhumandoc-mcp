import pytest

from superhumandoc_mcp.deadline import Deadline
from superhumandoc_mcp.errors import ClientError, RateLimited, UpstreamRefused
from superhumandoc_mcp.export import (
    EXPORT_404_GRACE_S,
    EXPORT_DEADLINE_S,
    EXPORT_INITIAL_SLEEP_S,
    EXPORT_MAX_LINK_REFRESH,
    EXPORT_POLL_MAX_INTERVAL_S,
    export_page,
)
from tests.conftest import (
    _always_failing_downloader,
    _downloader_failing_on,
    _fixed_downloader,
    _fixtures,
    _url_recording_downloader,
)


class _ExportApi:
    """Returns each queued status reply in turn; a reply that is an exception
    is raised rather than returned, so a test can queue a 404 or a 410. An
    exhausted queue answers `{}`, which is non-terminal -- an export that never
    completes."""

    def __init__(self, replies, *, kickoff=None):
        self._replies = list(replies)
        self._kickoff = kickoff if kickoff is not None else {"id": "exp-1"}
        self.begun = 0

    async def begin_export(self, page, output_format, deadline):
        self.begun += 1
        return self._kickoff

    async def get_export_status(self, page, request_id, deadline):
        reply = self._replies.pop(0) if self._replies else {}
        if isinstance(reply, Exception):
            raise reply
        return reply


async def test_a_link_is_followed_once_the_export_completes():
    """Not just that a body comes back, but that it was fetched from the link
    the poll body actually returned -- a downloader shaped to answer every URL
    alike would otherwise agree with code that fetched a different one."""
    clock, _, sleep = _fixtures()
    api = _ExportApi([{}, {"downloadLink": "https://s3/x"}])
    downloader = _url_recording_downloader("# Page")
    body = await export_page(api, downloader, "page-x",
                             "markdown", Deadline(clock=clock),
                             clock=clock, sleep=sleep)
    assert body == "# Page"
    assert downloader.urls == ["https://s3/x"]


async def test_the_kickoff_id_is_what_gets_polled():
    """The kickoff returns `id`, not `requestId`. Reading the wrong key yields
    None, which would be polled as the literal path segment "None" and answer
    404 -- indistinguishable from replication lag, so it would fail slowly and
    for the wrong stated reason."""
    seen: list[str] = []

    class _Recorder(_ExportApi):
        async def get_export_status(self, page, request_id, deadline):
            seen.append(request_id)
            return {"downloadLink": "https://s3/x"}

    clock, _, sleep = _fixtures()
    await export_page(_Recorder([], kickoff={"id": "exp-7"}),
                      _fixed_downloader("x"), "page-x", "markdown",
                      Deadline(clock=clock), clock=clock, sleep=sleep)
    assert seen == ["exp-7"]


async def test_a_kickoff_without_an_id_fails_at_once_and_says_so():
    """Polling None as a path segment would 404 and burn the whole grace window
    before reporting replication lag -- slow, and about the wrong thing."""
    clock, _, sleep = _fixtures()
    api = _ExportApi([], kickoff={"status": "inProgress"})
    with pytest.raises(ClientError) as caught:
        await export_page(api, _fixed_downloader("x"), "page-x", "markdown",
                          Deadline(clock=clock), clock=clock, sleep=sleep)
    # Not just "id" -- that substring also turns up inside "did" in the
    # fallback "did not complete within the export deadline" message, so it
    # would pass even if this branch fell through to the wrong one.
    assert "did not return an id" in str(caught.value)
    assert clock() < EXPORT_404_GRACE_S


async def test_a_410_is_terminal_at_once_and_never_waits_out_the_grace():
    """410 is declared on this endpoint and is unambiguous: the resource
    existed and is gone. Treating it like a 404 would spend the whole grace
    window asking for something that provably will not appear."""
    clock, slept, sleep = _fixtures()
    api = _ExportApi([UpstreamRefused("getPageContentExportStatus", 410, "gone")])
    with pytest.raises(ClientError):
        await export_page(api, _fixed_downloader("x"), "page-x", "markdown",
                          Deadline(clock=clock), clock=clock, sleep=sleep)
    # Equality, not a loose bound under the grace window: `< EXPORT_404_GRACE_S`
    # (20.0) passes with tenfold slack over the one sleep that actually
    # happens (the opening 2.0s wait), so it would not catch a 410 mistakenly
    # spending part of the grace window before giving up.
    assert sum(slept) == EXPORT_INITIAL_SLEEP_S


async def test_a_404_inside_the_grace_window_is_not_yet():
    clock, _, sleep = _fixtures()
    api = _ExportApi([
        UpstreamRefused("getPageContentExportStatus", 404, "missing"),
        {"downloadLink": "https://s3/x"},
    ])
    body = await export_page(api, _fixed_downloader("ok"), "page-x", "markdown",
                             Deadline(clock=clock), clock=clock, sleep=sleep)
    assert body == "ok"


async def test_a_non_404_client_error_from_status_is_wrapped_with_page_context():
    """`get_export_status` can also fail with `RateLimited`, `StickyRateLimit`,
    `ThrottleRefused`, `ResponseUnusable` or `OutcomeUnknown` -- all reachable
    from the real client, and none of them `UpstreamRefused`. Those go through
    the general `except ClientError` arm, one branch below the 404/410
    handling, which is what gives them the "could not be completed" page
    context. `RateLimited`'s own message says nothing about being unable to
    complete, so this only passes if that wrapping actually happened."""
    clock, _, sleep = _fixtures()
    api = _ExportApi([RateLimited("getPageContentExportStatus")])
    with pytest.raises(ClientError) as caught:
        await export_page(api, _fixed_downloader("x"), "page-x", "markdown",
                          Deadline(clock=clock), clock=clock, sleep=sleep)
    assert "the export for page 'page-x' could not be completed" in str(caught.value)


async def test_an_error_field_is_terminal_and_carries_its_own_text():
    """`error` has no structured code beside it, so the API's own text is the
    only thing there is to report."""
    clock, _, sleep = _fixtures()
    api = _ExportApi([{"error": "Page is a sync page and cannot be exported."}])
    with pytest.raises(ClientError) as caught:
        await export_page(api, _fixed_downloader("x"), "page-x", "markdown",
                          Deadline(clock=clock), clock=clock, sleep=sleep)
    assert "sync page" in str(caught.value)


async def test_a_stale_link_is_re_minted_rather_than_returned():
    """A link expires in five minutes while the file behind it lives for days,
    so a dead link is the likeliest late failure. The status endpoint is polled
    again for a fresh one -- the specification sanctions exactly this."""
    clock, _, sleep = _fixtures()
    api = _ExportApi([
        {"downloadLink": "https://s3/stale"},
        {"downloadLink": "https://s3/fresh"},
    ])
    body = await export_page(
        api, _downloader_failing_on("https://s3/stale", then="# Page"),
        "page-x", "markdown", Deadline(clock=clock), clock=clock, sleep=sleep)
    assert body == "# Page"


async def test_a_404_during_a_re_mint_gets_the_same_grace_as_any_other():
    """Re-minting re-enters the poll loop rather than running a ladder beside
    it. A separate ladder would deny the grace window on a re-mint poll, and a
    moment's replication lag would fail an export that patience completes."""
    clock, _, sleep = _fixtures()
    api = _ExportApi([
        {"downloadLink": "https://s3/stale"},
        UpstreamRefused("getPageContentExportStatus", 404, "missing"),
        {"downloadLink": "https://s3/fresh"},
    ])
    body = await export_page(
        api, _downloader_failing_on("https://s3/stale", then="# Page"),
        "page-x", "markdown", Deadline(clock=clock), clock=clock, sleep=sleep)
    assert body == "# Page"


async def test_re_minting_is_bounded_and_stops_well_short_of_the_ceiling():
    """The bug to catch is a re-mint that never stops -- ended only by the
    deadline, and reported as a timeout rather than as a link that will not
    come good.

    Asserting a ClientError is not enough to catch that: an unbounded
    implementation raises one too, from deadline exhaustion, and leaves
    `begun == 1` just the same, because re-minting re-polls rather than
    re-exporting. So this counts the downloads and checks the clock stopped far
    short of the export ceiling.
    """
    clock, _, sleep = _fixtures()
    api = _ExportApi([{"downloadLink": "https://s3/dead"}] * 50)
    downloader = _always_failing_downloader()
    with pytest.raises(ClientError):
        await export_page(api, downloader, "page-x", "markdown",
                          Deadline(clock=clock), clock=clock, sleep=sleep)
    assert downloader.calls == EXPORT_MAX_LINK_REFRESH + 1
    assert api.begun == 1          # re-minting re-polls; it never re-exports
    assert clock() < EXPORT_DEADLINE_S / 2


async def test_the_interval_backs_off_and_caps():
    """The tuned numbers, pinned by value the way the mutation loop's are.
    Nothing else here would notice the backoff silently becoming linear, or the
    cap being dropped so a long export waits minutes between polls.

    Diverges from the plan's literal reply list of twenty `{}`s plus one
    terminal `downloadLink`: reaching that terminal reply needs roughly 250
    simulated seconds of backed-off sleeps, which a genuine `EXPORT_DEADLINE_S`
    ceiling -- the entire point of retuning that constant -- cannot let a
    single export run past. `tests/test_polling.py`'s sibling test hits the
    same shape of problem and resolves it the same way this one now does:
    supply an export that never completes, assert the ceiling ends it with a
    `ClientError`, and check the backoff schedule from whatever sleeps
    happened before that. `max(slept)` still reaches the cap here rather than
    only bounding it, because the default deadline used below affords enough
    polls to reach `EXPORT_POLL_MAX_INTERVAL_S` before the ceiling fires.
    """
    clock, slept, sleep = _fixtures()
    api = _ExportApi([{}] * 30)
    with pytest.raises(ClientError):
        await export_page(api, _fixed_downloader("x"), "page-x", "markdown",
                          Deadline(clock=clock), clock=clock, sleep=sleep)
    assert slept[0] == EXPORT_INITIAL_SLEEP_S
    assert slept[1:4] == [2.0, 3.0, 4.5]
    assert max(slept) == EXPORT_POLL_MAX_INTERVAL_S


async def test_the_export_ceiling_never_extends_the_tool_deadline():
    """`clamp` takes the lesser: with a tight tool deadline the ceiling is set
    by what the deadline has left, not by the export's own forty-five-second
    allowance.

    A deadline with only 1.0s of working budget left (`total_s=11.0`, with the
    default 10s reserved tail) makes the opening sleep -- itself clamped --
    consume exactly that budget, landing the clock exactly on the ceiling. The
    next iteration's ceiling check then fires first, before `can_afford` is
    ever consulted, and only the ceiling branch's message names the export
    deadline. A bound on the clock alone cannot tell `clamp` apart from its
    absence here: both land on the same clock value (`can_afford` sees the
    same exhausted budget either way and raises its own message instead), so
    it is the message, not the clock, that discriminates.
    """
    clock, _, sleep = _fixtures()
    api = _ExportApi([])  # never completes
    with pytest.raises(ClientError) as caught:
        await export_page(api, _fixed_downloader("x"), "page-x", "markdown",
                          Deadline(total_s=11.0, clock=clock),
                          clock=clock, sleep=sleep)
    assert clock() == 1.0
    assert "did not complete within the export deadline" in str(caught.value)


async def test_a_tool_deadline_running_out_says_so_and_not_the_ceiling():
    """The two give-up messages are different facts a reader acts on
    differently, so they must actually be distinguishable. Here `can_afford`
    is what ends the loop -- well short of the (looser) export ceiling -- and
    only its message names the tool call's own time running out."""
    clock, _, sleep = _fixtures()
    api = _ExportApi([])  # never completes
    with pytest.raises(ClientError) as caught:
        await export_page(api, _fixed_downloader("x"), "page-x", "markdown",
                          Deadline(total_s=20.0, clock=clock),
                          clock=clock, sleep=sleep)
    assert clock() == 7.0
    assert "ran out of time" in str(caught.value)


async def test_the_opening_wait_is_clamped_like_every_other():
    """It runs before any loop condition, so it is the one that can overshoot
    into the reserved tail before a single question is asked. This is the
    defect the mutation loop shipped with. The assertion is an equality, not a
    bound: `<=` would also pass an implementation that never sleeps at all,
    which would hammer the status endpoint from the first instant."""
    clock, slept, sleep = _fixtures()
    api = _ExportApi([{"downloadLink": "https://s3/x"}])
    await export_page(api, _fixed_downloader("x"), "page-x", "markdown",
                      Deadline(total_s=11.0, clock=clock),
                      clock=clock, sleep=sleep)
    assert slept[0] == 1.0


async def test_the_page_and_format_reach_the_kickoff_unchanged():
    """Nothing else pins that export_page forwards its own arguments, and a
    call that exported the wrong page would return a plausible document."""
    seen = {}

    class _Recorder(_ExportApi):
        async def begin_export(self, page, output_format, deadline):
            seen.update(page=page, output_format=output_format)
            return {"id": "exp-1"}

    clock, _, sleep = _fixtures()
    await export_page(_Recorder([{"downloadLink": "https://s3/x"}]),
                      _fixed_downloader("x"), "page-9", "html",
                      Deadline(clock=clock), clock=clock, sleep=sleep)
    assert seen == {"page": "page-9", "output_format": "html"}


async def test_an_explicit_null_error_is_not_a_failure():
    """`error` carries the API's own failure text when it is set, but nothing
    establishes whether an unset one is absent or null -- the mutation status
    endpoint was measured going the absent way, which is no guarantee about
    this one. Testing presence rather than truthiness would turn a null into
    an export reported as "failed: None": a refusal with no reason a reader
    could act on, for a page that exported perfectly well.
    """
    clock, _, sleep = _fixtures()
    api = _ExportApi([{"error": None, "downloadLink": "https://s3/x"}])
    body = await export_page(api, _fixed_downloader("# Page"), "page-x",
                             "markdown", Deadline(clock=clock),
                             clock=clock, sleep=sleep)
    assert body == "# Page"

