"""Cell value formatting for writes, and refusal of columns that discard values.

The role of `cells_for_write` is to format values as they should appear in a
request body and to refuse writes that would be silently discarded server-side.
Every column type that rejects a write must reject it here, before the request
is sent — a refusal message tells the caller what they supplied, what would
happen, and what to do instead.
"""

from datetime import date

import pytest

from superhumandoc_mcp.cells import cells_for_write
from superhumandoc_mcp.errors import ContentRefused
from tests.conftest import (
    _BUTTON_COLUMN,
    _CALCULATED_COLUMN,
    _DATE_COLUMN,
    _NAME_COLUMN,
)


def test_a_date_is_sent_as_iso_8601():
    """The API parses dates through the same parser the UI uses; that parser
    reads ISO 8601 unambiguously, and every other format is locale-dependent.
    See `docs/validation/2026-09-03-cell-write-formats.md § Contradictions
    and traps #2`."""
    out = cells_for_write({"When": date(2026, 9, 6)}, [_DATE_COLUMN])
    assert out[0]["value"] == "2026-09-06"


def test_a_write_to_a_calculated_column_is_refused_before_sending():
    """The API accepts the request and discards the value, so the caller
    would be told a write applied that never happened. Refuse this before
    sending, to make the loss visible.

    `docs/validation/2026-09-03-cell-write-formats.md § Confirmed §
    formula / calculated columns` says they are not writable.
    """
    with pytest.raises(ContentRefused) as caught:
        cells_for_write({"Total": 5}, [_CALCULATED_COLUMN])
    assert "calculated" in str(caught.value)


def test_a_write_to_a_button_column_is_refused():
    """Button columns are written via `pushButton`, not through `cells` at all.
    See `docs/validation/2026-09-03-cell-write-formats.md § Confirmed §
    button (ColumnFormatType: button)`."""
    with pytest.raises(ContentRefused):
        cells_for_write({"Go": 1}, [_BUTTON_COLUMN])


def test_cells_go_out_keyed_by_column_id():
    """The row endpoint returns values keyed by ID; writes go the same way.
    `src/superhumandoc_mcp/tools/reads.py::_cells_by_name` shows the shape:
    row values are keyed by column ID, not column name. The reverse direction —
    name to ID — is what this function does."""
    out = cells_for_write({"Name": "Ada"}, [_NAME_COLUMN])
    assert out[0]["column"] == _NAME_COLUMN["id"]


def test_an_unknown_column_name_is_refused_rather_than_guessed():
    """A misspelled column name or a reference to a column in a different table
    leaves the cell unchanged on the server. Refuse this, so the loss is visible."""
    with pytest.raises(ContentRefused):
        cells_for_write({"Nonexistent": 1}, [_NAME_COLUMN])
