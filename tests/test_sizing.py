"""Row and request sizing: computing what the API counts, not what we send."""

import pytest

from superhumandoc_mcp.sizing import row_internal_bytes, request_wire_bytes


def test_a_plain_ascii_row_measures_its_own_length():
    """ASCII text's UTF-8 encoding is byte-identical to the ASCII string."""
    assert row_internal_bytes({"c-1": "hello"}) == 5


def test_a_newline_is_charged_twice():
    """The formula nine samples fit: utf8 length plus one per newline.

    See docs/reference/api-operational-constants.md: measured 2026-09-05, nine
    samples. Every sample fits `internal ≈ utf8_len(value) + newline_count`,
    i.e. the value's UTF-8 length with each newline charged twice.
    """
    assert row_internal_bytes({"c-1": "a\nb"}) == 4


def test_non_latin_content_is_measured_in_utf8_bytes_not_characters():
    """Measuring characters would refuse CJK rows at a fraction of the size
    the API accepts, which is the mistake this measure exists to avoid."""
    assert row_internal_bytes({"c-1": "中" * 10}) == 30


def test_values_that_are_not_strings_are_measured_as_their_text():
    """Non-string values are converted to strings before measurement."""
    assert row_internal_bytes({"c-1": 36, "c-2": True}) == len("36") + len("True")


def test_the_two_axes_are_not_the_same_measure():
    """The request cap counts wire bytes and the row cap counts internal
    bytes. Conflating them is what the previous decision got wrong.

    See docs/reference/api-operational-constants.md §1.2: `MAX_REQUEST_BYTES`
    is about the request (count of bytes actually put on the wire),
    `MAX_ROW_INTERNAL_BYTES` is about the row (values' UTF-8 length with
    newlines charged twice). The two are not comparable.
    """
    payload = {"rows": [{"cells": [{"column": "c-1", "value": "中"}]}]}
    assert request_wire_bytes(payload) > row_internal_bytes({"c-1": "中"})
