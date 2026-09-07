"""Row-by-row reporting of write outcomes, one per row.

Each row gets its own outcome — applied, unknown, refused, or not attempted —
and may carry a warning specific to the chunk that row was part of.
"""

from tests.conftest import _rows

from superhumandoc_mcp.outcomes import BatchReport, RowOutcome


def test_every_row_the_caller_sent_appears_exactly_once():
    """The report contains one entry per input row, no more, no less."""
    report = BatchReport.for_rows(_rows(100))
    report.mark(range(0, 50), RowOutcome.APPLIED)
    report.mark(range(50, 100), RowOutcome.NOT_ATTEMPTED)
    assert len(report.as_dict()["rows"]) == 100


def test_a_report_never_collapses_to_a_single_verdict():
    """Each row's outcome is reported individually; no summary verdict."""
    report = BatchReport.for_rows(_rows(2))
    report.mark([0], RowOutcome.APPLIED)
    report.mark([1], RowOutcome.REFUSED)
    assert "succeeded" not in str(report.as_dict()).lower()


def test_resume_from_names_the_first_row_never_attempted():
    """When some rows are not attempted, resume_from() gives their first index."""
    report = BatchReport.for_rows(_rows(10))
    report.mark(range(0, 4), RowOutcome.APPLIED)
    report.mark(range(4, 10), RowOutcome.NOT_ATTEMPTED)
    assert report.resume_from() == 4


def test_resume_from_is_absent_when_everything_was_attempted():
    """When all rows were attempted, resume_from() returns None."""
    report = BatchReport.for_rows(_rows(3))
    report.mark(range(0, 3), RowOutcome.APPLIED)
    assert report.resume_from() is None


def test_an_outcome_serialises_as_its_lowercase_name():
    """Every later task asserts these exact strings.

    Nothing else in this task would catch serialising the enum's name, or
    leaving the enum itself in the dict — both pass every other test here and
    break every consumer.
    """
    report = BatchReport.for_rows(_rows(4))
    report.mark([0], RowOutcome.APPLIED)
    report.mark([1], RowOutcome.UNKNOWN)
    report.mark([2], RowOutcome.REFUSED)
    report.mark([3], RowOutcome.NOT_ATTEMPTED)
    assert [r["outcome"] for r in report.as_dict()["rows"]] == [
        "applied", "unknown", "refused", "not_attempted"]


def test_a_warning_attaches_only_to_the_rows_its_chunk_carried():
    """Collapsing warnings into one field would attribute a warning about
    the first chunk's rows to every other chunk's rows as well.
    """
    report = BatchReport.for_rows(_rows(4))
    report.mark([0, 1], RowOutcome.APPLIED, warning="Column X ignored.")
    report.mark([2, 3], RowOutcome.APPLIED)
    rows = report.as_dict()["rows"]
    assert rows[0]["warning"] == "Column X ignored."
    assert rows[3]["warning"] is None


def test_a_row_nothing_ever_marked_is_reported_and_resumable():
    """The accessors must agree about a row no `mark` call ever named.

    A chunker that returns early — out of budget, or stopped by a refusal —
    leaves a tail of rows it never touched, and that tail is the whole reason
    resuming exists. If an unmarked row were absent from the outcome map,
    `resume_from` would answer None while `as_dict` reported the same rows as
    not attempted, and a caller trusting `resume_from` would drop them
    silently. Nothing else in this module's tests marks fewer rows than it
    opened, so nothing else would catch it.
    """
    report = BatchReport.for_rows(_rows(5))
    report.mark(range(0, 2), RowOutcome.APPLIED)

    assert report.resume_from() == 2
    assert [r["outcome"] for r in report.as_dict()["rows"]] == [
        "applied", "applied", "not_attempted", "not_attempted", "not_attempted",
    ]
    assert report.counts()[RowOutcome.NOT_ATTEMPTED] == 3
