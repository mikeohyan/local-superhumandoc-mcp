"""Row and request sizing: computing what the API counts, not what we send.

The API counts size in two different units: the internal bytes a row consumes
in the doc file, and the wire bytes a request occupies on the network. A client
that conflates them — e.g. by estimating row bytes from a serialized request —
will split or refuse rows the API would take. See `_rfc/README.md` for the
`request-sizing` topic, which owns these constants and the sizing operations
they gate.
"""

import json


MAX_ROW_INTERNAL_BYTES = 84_000
"""Row size ceiling, in the units the API counts — internal bytes.

The API's error says "85 KB" but measures in Coda's internal representation
with a 1.1% margin: utf8_len(value) + newlines_charged_twice, summed over the
row's values. Computed, not estimated. The margin covers the formula's observed
error and the ambiguity in the vendor's "85 KB" (does it mean 85,000 or 87,040?).
See docs/reference/api-operational-constants.md §2.3 for the measurement.
"""

MAX_REQUEST_BYTES = 1_500_000
"""Request size ceiling, in the units that matter on the network — wire bytes.

The API's published cap is 2 MB. The 25% headroom accounts for encoding
overhead (UTF-8, JSON escaping). This is the byte count of the HTTP body.
See docs/reference/api-operational-constants.md §1.2.
"""


def row_internal_bytes(values: dict) -> int:
    """A row's size as the API counts it: UTF-8 length, newlines charged twice.

    Fitted to nine samples across Latin text, CJK, emoji and newline-dense
    content to about 1%. Computed, not estimated — the inflation factor this
    replaced sat above a ratio that provably cannot exceed 2.0.

    The API counts each newline in a value as two bytes, not one. Non-string
    values are converted to their string representation before measurement.
    """
    total = 0
    for value in values.values():
        text = value if isinstance(value, str) else str(value)
        total += len(text.encode("utf-8")) + text.count("\n")
    return total


def request_wire_bytes(payload: object) -> int:
    """Bytes actually put on the wire — a different axis, a different unit,
    guarding a different limit.

    The serialization here deliberately matches what actually encodes a
    request body, `httpx2._content.encode_json`: `ensure_ascii=False` and
    compact separators. A measure that disagreed with the encoder would be
    guessing at the very number the cap is expressed in — default separators,
    for instance, charge two bytes per field that are never sent, which on a
    batch of many small cells is a real over-count.

    Because the encoder passes `ensure_ascii=False`, non-ASCII travels as its
    UTF-8 bytes rather than as escapes. This is still not interchangeable with
    `row_internal_bytes`: the structure around the values — keys, brackets,
    quotes, commas — is on this axis and not on that one.
    """
    return len(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
