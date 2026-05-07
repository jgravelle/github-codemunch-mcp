"""Integration tests for get_file_outline: producer + MCP encoder + decoder."""

import textwrap

import pytest

from jcodemunch_mcp.encoding import encode_response
from jcodemunch_mcp.encoding.decoder import decode
from jcodemunch_mcp.tools.get_file_outline import get_file_outline


@pytest.fixture
def class_with_members_index(tmp_path):
    """Python repo: 1 file with one class (ctor + 2 methods) and 1 standalone fn.

    Symbols extracted by the Python parser:
        - Repo (class)              parent=None
          - __init__ (method)       parent=Repo
          - count (method)          parent=Repo
        - top_level_helper (fn)     parent=None
    """
    from jcodemunch_mcp.tools.index_folder import index_folder

    src = tmp_path / "src"
    store = tmp_path / "store"
    src.mkdir()
    store.mkdir()
    (src / "repo.py").write_text(textwrap.dedent('''\
        class Repo:
            """A toy repository."""

            def __init__(self, name: str) -> None:
                self.name = name

            def count(self) -> int:
                return 0


        def top_level_helper(x: int) -> int:
            return x + 1
    '''))
    r = index_folder(str(src), use_ai_summaries=False, storage_path=str(store))
    assert r["success"] is True
    return {"repo": r["repo"], "store": str(store), "src": str(src)}


def _outline_through_wire(repo: str, file_path: str, store: str) -> dict:
    """Helper: run producer, encode through compact pipeline, decode back."""
    raw = get_file_outline(repo=repo, file_path=file_path, storage_path=store)
    payload, meta = encode_response("get_file_outline", raw, "compact")
    assert isinstance(payload, str)
    assert meta["encoding"] != "json"
    return decode(payload)


def test_nested_methods_appear_in_response(class_with_members_index):
    """Class methods and constructors appear alongside the class itself."""
    fx = class_with_members_index
    decoded = _outline_through_wire(fx["repo"], "repo.py", fx["store"])

    names = [s["name"] for s in decoded["symbols"]]
    kinds = {s["name"]: s["kind"] for s in decoded["symbols"]}

    assert {"Repo", "__init__", "count", "top_level_helper"} <= set(names)
    assert kinds["Repo"] == "class"
    assert kinds["count"] == "method"


def test_parent_column_carries_hierarchy(class_with_members_index):
    """`parent` ids point each nested symbol at its enclosing class."""
    fx = class_with_members_index
    decoded = _outline_through_wire(fx["repo"], "repo.py", fx["store"])

    by_name = {s["name"]: s for s in decoded["symbols"]}
    repo_id = by_name["Repo"]["id"]

    assert by_name["Repo"]["parent"] in (None, "")
    assert by_name["top_level_helper"]["parent"] in (None, "")
    assert by_name["__init__"]["parent"] == repo_id
    assert by_name["count"]["parent"] == repo_id


def test_dfs_ordering_groups_members_with_class(class_with_members_index):
    """Class members appear immediately after the class, before next top-level."""
    fx = class_with_members_index
    decoded = _outline_through_wire(fx["repo"], "repo.py", fx["store"])
    names = [s["name"] for s in decoded["symbols"]]

    assert names.index("Repo") < names.index("__init__")
    assert names.index("Repo") < names.index("count")
    helper_idx = names.index("top_level_helper")
    for member in ("__init__", "count"):
        assert names.index(member) < helper_idx


def test_signature_field_round_trips(class_with_members_index):
    """`signature` survives encode → decode for nested and top-level symbols."""
    fx = class_with_members_index
    decoded = _outline_through_wire(fx["repo"], "repo.py", fx["store"])

    by_name = {s["name"]: s for s in decoded["symbols"]}
    helper_sig = by_name["top_level_helper"]["signature"] or ""
    init_sig = by_name["__init__"]["signature"] or ""

    assert "top_level_helper" in helper_sig
    assert "__init__" in init_sig


def test_in_process_response_is_flat(class_with_members_index):
    """Producer emits a flat list — no nested ``children`` keys."""
    fx = class_with_members_index
    raw = get_file_outline(repo=fx["repo"], file_path="repo.py", storage_path=fx["store"])

    symbols = raw["symbols"]
    assert all("children" not in s for s in symbols)
    assert any(s.get("parent") for s in symbols)


def test_batch_mode_returns_flat_per_file_outlines(class_with_members_index):
    """Batch mode's per-file inner shape is flat with parent ids too."""
    fx = class_with_members_index
    raw = get_file_outline(
        repo=fx["repo"],
        file_paths=["repo.py"],
        storage_path=fx["store"],
    )

    file_results = raw["results"]
    assert len(file_results) == 1
    syms = file_results[0]["symbols"]
    assert all("children" not in s for s in syms)
    names = {s["name"] for s in syms}
    assert {"Repo", "__init__", "count", "top_level_helper"} <= names
