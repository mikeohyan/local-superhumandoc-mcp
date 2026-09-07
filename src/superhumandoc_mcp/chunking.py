"""Splitting a row batch into chunks, and sending them in order.

The API enforces two independent caps on a write: how many rows one request
may carry, and how many bytes it may occupy, measured on two different axes
(see `sizing.py`). Refusing an over-cap batch outright would push the split
onto every caller; the `request-sizing` topic instead has the client split it
here and send the pieces in order, so a caller that wants to write more rows
than fit in one request never has to think about the cap at all.

`plan_chunks` decides the split; `send_chunks` carries it out against a
deadline, folding the two ways a chunk can fail — no time left, and no local
rate-limit slot — into the outcomes `outcomes.py` defines, rather than
letting either escape as a bare exception mid-batch.
"""

from collections import deque
from collections.abc import Awaitable, Callable

from superhumandoc_mcp.deadline import Deadline
from superhumandoc_mcp.errors import ThrottleRefused, UpstreamRefused
from superhumandoc_mcp.outcomes import BatchReport, RowOutcome
from superhumandoc_mcp.sizing import request_wire_bytes, row_internal_bytes

# The two message texts a size refusal is spelled with. The `request-sizing`
# topic names them explicitly, and it has to: a size refusal is a 400 carrying
# the bare `{statusCode, statusMessage, message}` shape, with no `codaType` and
# no `codaDetail` — nothing structured to match on, so the message text is the
# only discriminator that exists
# (docs/reference/api-operational-constants.md §2.3).
_SIZE_REFUSAL_PHRASES = ("exceeds maximum size", "entity too large")

CHUNK_COST_ESTIMATE_S = 30.0
"""What one chunk is charged against the deadline before another is admitted.

An estimate, not a bound: `MUTATION_DEADLINE_S` in `polling.py` lets a single
chunk's poll run up to 60 seconds, twice this figure, so a chunk this gate
admitted can still consume more of the budget than it was charged for. See
docs/reference/api-operational-constants.md §1.2 and §1.3 for the observations
behind both numbers; the `request-sizing` topic owns what a client does with
them.
"""


def _is_size_refusal(refusal: UpstreamRefused) -> bool:
    """Whether this refusal is the one halving answers.

    Only a size refusal is. Halving anything else would turn a single "you
    may not do that" — a 403, a table that does not exist — into a cascade of
    requests that each get the same answer, spending the rate budget and the
    deadline to relearn a fact the first response already gave. The single-row
    floor bounds that cascade but does not make it useful.
    """
    if refusal.status != 400:
        return False
    detail = (refusal.detail or "").lower()
    return any(phrase in detail for phrase in _SIZE_REFUSAL_PHRASES)


def plan_chunks(
    rows: list[dict],
    *,
    max_rows: int,
    max_row_bytes: int,
    max_request_bytes: int,
) -> list[list[int]]:
    """Partition `rows` into chunks, returned as indices into `rows` itself.

    Indices rather than rows, so that whatever happens to a chunk — applied,
    unknown, refused, never attempted — can be attributed back to the
    caller's own position in its own list. That attribution is what lets
    `BatchReport.resume_from` name one index instead of asking the caller to
    reconstruct a subset.

    Three caps govern the split, each on a different axis. `max_rows` bounds
    how many rows one chunk may carry. `max_row_bytes` bounds a single row —
    the same axis `row_internal_bytes` measures — so a row already over that
    cap on its own cannot be helped by grouping; it is isolated in a
    singleton chunk rather than folded into a request-byte computation that
    would only restate the same fact. `max_request_bytes` bounds the wire
    size of a chunk as a whole, on `request_wire_bytes`' axis, which is why it
    is checked against the *running* chunk rather than one row at a time.

    Rows are consumed strictly in input order and never reordered, so the
    indices in the returned chunks are contiguous and ascending both within a
    chunk and across chunks — the property `send_chunks` depends on to keep
    whatever it never gets to as a suffix of the input.
    """
    chunks: list[list[int]] = []
    current: list[int] = []

    def flush() -> None:
        if current:
            chunks.append(current.copy())
            current.clear()

    for index, row in enumerate(rows):
        if row_internal_bytes(row) > max_row_bytes:
            flush()
            chunks.append([index])
            continue
        candidate = current + [index]
        if (
            len(candidate) > max_rows
            or request_wire_bytes([rows[i] for i in candidate]) > max_request_bytes
        ):
            flush()
        current.append(index)
    flush()
    return chunks


async def send_chunks(
    chunks: list[list[int]],
    rows: list[dict],
    send: Callable[[list[int]], Awaitable[object]],
    deadline: Deadline,
    *,
    report: BatchReport,
) -> BatchReport:
    """Send each chunk in order, marking `report` with what happened to it.

    `rows` plays no part beyond documenting that `chunks` indexes into it —
    `send` already closes over whatever it needs to build a request, and
    `report` already knows the full row count. It is accepted anyway so this
    signature reads as chunking the same list `plan_chunks` did, rather than
    an unrelated list of indices.

    Chunks are attempted strictly in order. The moment one cannot even be
    started, every chunk still in the queue is marked `NOT_ATTEMPTED` without
    being tried, which is what makes the not-attempted rows a suffix of the
    input rather than a scattered subset — a correctness property, not an
    optimisation, since a caller resumes from one index (`resume_from`) and a
    resume that skipped over an untried row in the middle would drop it.

    A chunk can fail to start in two different ways, and they must not read
    alike. `CHUNK_COST_ESTIMATE_S` is an admission gate on starting *another*
    chunk, not a bound on the one already in flight — a chunk it just let
    through can still take up to `MUTATION_DEADLINE_S` to poll, twice the
    estimate, so the gate is checked only once progress exists to protect;
    the very first chunk is always attempted regardless of budget, and
    whatever the deadline has to say about that is left to `send` itself —
    the same shape `DocsApi._paged` uses for its own deadline check
    (`if collected and deadline.expired`). A `ThrottleRefused` from `send`
    is the other way to fail to start: the local limiter never had a slot to
    give within this call's remaining time, so nothing was sent and nothing
    is different from budget exhaustion as far as the rows are concerned —
    it folds into the same `NOT_ATTEMPTED` suffix. Any other error `send`
    raises — a dead deadline included, once the request layer refuses to
    even try — is a different thing than either and is left to propagate.

    A *size* refusal — and only a size refusal, which the API spells as a 400
    whose message says `exceeds maximum size` or `entity too large`, with
    nothing structured to match on — is treated as an oversized request
    rather than a bad chunk: halved and retried in the same order, down to
    single rows, at which point a refusal is `REFUSED` rather than a reason
    to keep splitting. Every other refusal marks its chunk `REFUSED` at once.
    Halving a 403 or a bad table name would ask the same question up to seven
    more times and get the same answer each time, spending rate budget and
    deadline to relearn what the first response already said.

    A `MutationOutcome` with `applied=False` marks its chunk `UNKNOWN`, never
    `REFUSED` — the API accepted the write and this call merely lost track of
    it, which is not the same as the API having said no. Its `warning`, when
    one is present, is attached only to that chunk's own rows, via `mark`'s
    per-call `warning`, so a warning about one chunk is never read as though
    it were about another.
    """
    queue: deque[list[int]] = deque(chunks)
    attempted = False
    while queue:
        indices = queue.popleft()
        if attempted and not deadline.can_afford(CHUNK_COST_ESTIMATE_S):
            report.mark(indices, RowOutcome.NOT_ATTEMPTED)
            for remaining in queue:
                report.mark(remaining, RowOutcome.NOT_ATTEMPTED)
            return report

        try:
            outcome = await send(indices)
        except UpstreamRefused as refusal:
            attempted = True
            if len(indices) == 1 or not _is_size_refusal(refusal):
                report.mark(indices, RowOutcome.REFUSED)
                continue
            mid = len(indices) // 2
            queue.appendleft(indices[mid:])
            queue.appendleft(indices[:mid])
            continue
        except ThrottleRefused:
            report.mark(indices, RowOutcome.NOT_ATTEMPTED)
            for remaining in queue:
                report.mark(remaining, RowOutcome.NOT_ATTEMPTED)
            return report

        attempted = True
        if outcome.applied:
            report.mark(indices, RowOutcome.APPLIED, warning=outcome.warning)
        else:
            report.mark(indices, RowOutcome.UNKNOWN, warning=outcome.warning)
    return report
