"""Acceptance runner regressions use FIXTURE HTTP, never REAL source evidence."""
import importlib.util
from email.message import Message
from pathlib import Path

import pytest

from fox3d.catalog_recipes import load_library
from fox3d.evidence import DirtyTreeError

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def runner(monkeypatch):
    spec = importlib.util.spec_from_file_location("recipe_runner", ROOT / "scripts/run_recipe_library_e2e.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "inspect_repo_lineage", lambda root: {"evidenceCodeCommit": "a" * 40})
    return module


@pytest.mark.parametrize("failure", ["hash", "mime", "identity", "empty", "redirect", None])
def test_http_evidence_failures_and_reference_only_success(runner, monkeypatch, failure):
    catalog = ROOT / "data/recipe_library/sonaqueen/catalog.json"
    library = load_library(catalog)
    sources = {s.url: s for p in library.products for s in p.sources}

    class Response:
        def __init__(self, url):
            source = sources[url]
            self.status = 200
            self.url = url if failure != "redirect" else "https://example.com/"
            self.headers = Message()
            self.headers["Content-Type"] = "text/plain" if failure == "mime" else source.mediaType
            self.data = (catalog.parent / source.path).read_bytes()
            if failure == "empty":
                self.data = b""
            if failure == "hash" and source.mediaType == "image/jpeg":
                self.data += b"tampered"
            if failure == "identity" and source.mediaType == "text/html":
                self.data = b"<html>Other product</html>"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, size):
            return self.data[:size]

    monkeypatch.setattr(runner, "urlopen", lambda request, timeout: Response(request.full_url))
    if failure:
        with pytest.raises(ValueError):
            runner.run("a" * 40)
    else:
        result = runner.run("a" * 40)
        assert result["ok"] and result["productCount"] == 3
        assert len(result["sourceChecks"]) == 10
        assert not result["realBlenderAcceptance"] and not result["engineeringReady"]
        assert all(p["blockers"] for p in result["products"])


def test_wrong_commit_fails_before_network(runner):
    with pytest.raises(ValueError, match="CODE"):
        runner.run("b" * 40)


def test_dirty_tree_fails_before_network(runner, monkeypatch):
    def dirty(root):
        raise DirtyTreeError("working tree dirty")
    monkeypatch.setattr(runner, "inspect_repo_lineage", dirty)
    with pytest.raises(DirtyTreeError):
        runner.run("a" * 40)
