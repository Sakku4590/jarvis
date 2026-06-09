"""Unit tests for the sandboxed FileService (pure, no LLM, isolated workspace)."""

import pytest

from app.services.file_service import (
    AlreadyExists,
    FileService,
    NotFound,
    PathNotAllowed,
)


@pytest.fixture
def svc(tmp_path):
    return FileService(root=tmp_path)


def test_create_and_read_roundtrip(svc):
    svc.create("notes/todo.txt", "buy milk")
    out = svc.read("notes/todo.txt")
    assert out["content"] == "buy milk"
    assert out["bytes"] == len("buy milk")
    assert out["binary"] is False


def test_create_refuses_existing_without_overwrite(svc):
    svc.create("a.txt", "one")
    with pytest.raises(AlreadyExists):
        svc.create("a.txt", "two")
    # overwrite succeeds and replaces content
    svc.create("a.txt", "two", overwrite=True)
    assert svc.read("a.txt")["content"] == "two"


def test_delete_removes_file(svc):
    svc.create("gone.txt", "x")
    svc.delete("gone.txt")
    with pytest.raises(NotFound):
        svc.read("gone.txt")


def test_delete_missing_raises(svc):
    with pytest.raises(NotFound):
        svc.delete("nope.txt")


def test_rename_moves_file(svc):
    svc.create("old.txt", "data")
    svc.rename("old.txt", "sub/new.txt")
    assert svc.read("sub/new.txt")["content"] == "data"
    with pytest.raises(NotFound):
        svc.read("old.txt")


def test_search_by_name(svc):
    svc.create("report-q1.md", "x")
    svc.create("notes.txt", "y")
    res = svc.search(query="report")
    names = {m["name"] for m in res["matches"]}
    assert "report-q1.md" in names and "notes.txt" not in names


def test_search_by_content(svc):
    svc.create("a.txt", "the quick brown fox")
    svc.create("b.txt", "lorem ipsum")
    res = svc.search(query="brown", search_content=True)
    paths = {m["path"] for m in res["matches"]}
    assert "a.txt" in paths and "b.txt" not in paths


def test_path_traversal_is_blocked(svc):
    with pytest.raises(PathNotAllowed):
        svc.read("../../etc/passwd")
    with pytest.raises(PathNotAllowed):
        svc.create("/etc/evil.txt", "nope")
    with pytest.raises(PathNotAllowed):
        svc.delete("../outside.txt")


def test_search_on_empty_workspace_returns_nothing(svc):
    res = svc.search(query="anything")
    assert res["count"] == 0 and res["matches"] == []
