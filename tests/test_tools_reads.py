"""The always-on read tools: thin translations between the model's
vocabulary and `api.py`, wrapped by `tool_boundary` and registered by
`register_read_tools`.
"""

from superhumandoc_mcp.deadline import Deadline
from superhumandoc_mcp.tools.reads import outline_page


class _FakeApi:
    """Stands in for `DocsApi`: returns fixed `listPageContent` items without
    any HTTP, so these tests pin only what `outline_page` does with the
    shape it is handed."""

    def __init__(self, items: list[dict]) -> None:
        self._items = items
        self.calls: list[tuple[str, Deadline]] = []

    async def list_page_content(self, page: str, deadline: Deadline) -> list[dict]:
        self.calls.append((page, deadline))
        return self._items


async def test_outline_returns_lines_in_order_with_their_element_ids():
    """The outline preserves the API's own ordering and names every field the
    RFC promises, one entry per line."""
    api = _FakeApi(
        [
            {
                "id": "el-1",
                "itemContent": {
                    "style": "heading1",
                    "lineLevel": 0,
                    "text": "Title",
                },
            },
            {
                "id": "el-2",
                "itemContent": {
                    "style": "paragraph",
                    "lineLevel": 0,
                    "text": "Body",
                },
            },
        ]
    )
    lines = await outline_page(api, "page-x")
    assert lines == [
        {"element_id": "el-1", "style": "heading1", "level": 0, "text": "Title"},
        {"element_id": "el-2", "style": "paragraph", "level": 0, "text": "Body"},
    ]


async def test_style_and_level_are_read_from_item_content_not_the_top_level():
    """Probe P9: `style` and `lineLevel` are nested inside `itemContent`, not
    at the item's top level. A decoy top-level `style` pins that the nested
    one wins rather than being silently shadowed."""
    api = _FakeApi(
        [
            {
                "id": "el-1",
                "style": "WRONG",
                "itemContent": {"style": "paragraph", "lineLevel": 2, "text": "x"},
            }
        ]
    )
    lines = await outline_page(api, "page-x")
    assert lines[0]["style"] == "paragraph"
    assert lines[0]["level"] == 2


async def test_outline_page_asks_for_the_page_it_was_given():
    """The tool's only argument is the page identifier; it must reach the API
    call unchanged."""
    api = _FakeApi([])
    await outline_page(api, "page-x")
    assert api.calls[0][0] == "page-x"
