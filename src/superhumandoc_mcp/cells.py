"""Cell value formatting for writes, and refusal of columns that discard values.

The role of `cells_for_write` is to format values as they should appear in a
request body and to refuse writes that would be silently discarded server-side.
Every column type that rejects a write must reject it here, before the request
is sent — so the loss is visible in the refusal message rather than silent.

Cell values that are dates are sent as ISO 8601 strings, set by the
`tool-surface` topic. Every other type is coerced to a string by the API's
parser, which is the same parser the UI uses when a value is typed by hand.
"""

from datetime import date

from superhumandoc_mcp.errors import ContentRefused


def cells_for_write(cells: dict, columns: list[dict]) -> list[dict]:
    """Format cell values for writing, and refuse columns that discard writes.

    Takes a dict of cells keyed by column name (as a user would spell them)
    and the column schema list. Returns a list of dicts, each with `column`
    (the column ID) and `value` (the formatted value), in the shape the write
    endpoint expects.

    Raises `ContentRefused` if a cell targets a calculated column, a button
    column, or a column name that does not exist in the schema.
    """
    schema_by_name = {column["name"]: column for column in columns}
    out = []
    for name, value in cells.items():
        if name not in schema_by_name:
            raise ContentRefused(
                f"Column '{name}' was not found in this table's schema. "
                "Cells are addressed by column name here — the name a row read "
                "comes back keyed by — not by column ID. Call describe_table "
                "to see this table's column names."
            )

        column = schema_by_name[name]

        # Refuse calculated columns: the API accepts the request and discards
        # the value, so the caller would be told a write applied that never
        # happened. Refuse this before sending.
        if column.get("calculated"):
            raise ContentRefused(
                f"Column '{name}' is a calculated column. Calculated columns "
                "are read-only and their values are discarded on write. "
                "Remove this column from the write."
            )

        # Refuse button columns: they are written via pushButton, not through
        # cells at all.
        if column.get("format", {}).get("type") == "button":
            raise ContentRefused(
                f"Column '{name}' is a button column. Button columns are "
                "written via `push_button`, not through cell values. "
                "Use the dedicated `push_button` tool instead."
            )

        # A date carries no format of its own once it reaches JSON, and the
        # one parser the API uses reads ISO 8601 unambiguously where every
        # other spelling is locale-dependent.
        if isinstance(value, date):
            formatted_value = value.isoformat()
        else:
            formatted_value = value

        out.append({"column": column["id"], "value": formatted_value})

    return out
