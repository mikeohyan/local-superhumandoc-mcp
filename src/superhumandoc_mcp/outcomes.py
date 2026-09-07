"""Row-by-row reporting of write outcomes, one per row.

Each row gets its own outcome — applied, unknown, refused, or not attempted —
and may carry a warning specific to the chunk that row was part of. Warnings
attach per chunk: collapsing them into one field would attribute a warning
about the first chunk's rows to every other chunk's rows as well.
"""

from enum import StrEnum


class RowOutcome(StrEnum):
    """The outcome of attempting to write one row.

    APPLIED: The row was written.
    UNKNOWN: The write was accepted but the outcome could not be confirmed.
    REFUSED: The API refused the row.
    NOT_ATTEMPTED: The row was never attempted due to budget constraints or
      earlier failures.
    """

    APPLIED = "applied"
    UNKNOWN = "unknown"
    REFUSED = "refused"
    NOT_ATTEMPTED = "not_attempted"


class BatchReport:
    """Reports the outcome of a split write, row by row.

    The caller provides the rows at construction, then marks each row with an
    outcome as chunks are sent. The report can be queried for which rows got
    which outcomes, and serialized to a dict with one entry per row.
    """

    def __init__(self, rows: list[dict]) -> None:
        """Every row starts NOT_ATTEMPTED, and that default is load-bearing.

        A row the caller handed in and that nothing ever marked has, by
        definition, not been attempted — so it must read that way from every
        accessor, not only from the serialised form. Leaving unmarked rows out
        of the outcome map instead would let `resume_from` answer None while
        `as_dict` reported those same rows as not attempted, and a caller
        trusting `resume_from` would drop them silently. The one place that
        disagreement could arise is a chunker that returns early, which is
        exactly the case resuming exists for.
        """
        self._rows = rows
        self._outcomes: dict[int, RowOutcome] = {
            index: RowOutcome.NOT_ATTEMPTED for index in range(len(rows))
        }
        self._warnings: dict[int, str | None] = {}

    @classmethod
    def for_rows(cls, rows: list[dict]) -> "BatchReport":
        """The public constructor. Named rather than `__init__` so a call site
        reads as what it is: a report opened over a specific batch."""
        return cls(rows)

    def mark(
        self,
        indices,
        outcome: RowOutcome,
        warning: str | None = None,
    ) -> None:
        """Record `outcome` against every index in `indices`.

        `indices` is any iterable of integers, so a chunk can be marked from
        the same range it was sliced with. A warning attaches to exactly the
        rows named here and to no others: warnings arrive per chunk, and one
        collapsed field would attribute a warning about the first chunk's rows
        to every later chunk's rows as well.
        """
        for i in indices:
            self._outcomes[i] = outcome
            self._warnings[i] = warning

    def indices_with(self, outcome: RowOutcome) -> list[int]:
        """Return the indices of all rows with the given outcome, in order."""
        return sorted([i for i, o in self._outcomes.items() if o == outcome])

    def resume_from(self) -> int | None:
        """The first index never attempted, or None once every row was.

        Not-attempted rows are a suffix of the caller's input — that is the
        guarantee the `request-sizing` topic makes in place of the withdrawn
        promise that a split write ends holding the offending row — so one
        index is enough to say what is left to send.
        """
        not_attempted = self.indices_with(RowOutcome.NOT_ATTEMPTED)
        if not not_attempted:
            return None
        return not_attempted[0]

    def counts(self) -> dict[RowOutcome, int]:
        """How many rows landed in each outcome. Every member is present, with
        a zero rather than a missing key, so a caller can format the tally
        without testing for absence."""
        counts: dict[RowOutcome, int] = {outcome: 0 for outcome in RowOutcome}
        for outcome in self._outcomes.values():
            counts[outcome] += 1
        return counts

    def as_dict(self) -> dict:
        """One entry per row the caller sent, in the order they sent them.

        The outcome serialises as its lowercase value rather than the enum or
        its member name, because every consumer of this report asserts those
        exact strings. There is no summary verdict anywhere in the shape: a
        split write that half succeeded has no single true answer, and
        inventing one is the failure this report exists to prevent.
        """
        return {
            "rows": [
                {
                    "outcome": self._outcomes[index].value,
                    "warning": self._warnings.get(index),
                }
                for index in range(len(self._rows))
            ]
        }
