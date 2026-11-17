"""search returns repo-relative paths for local-source chunks, and merges the same chunk from both tracks."""

import asyncio
import json
from unittest.mock import patch

from app.mcp.handlers.search_handlers import handle_search
from app.services.search import execute_hybrid_search
from app.services.vector_store import VectorSearchResult
from tests.test_diagnose_evidence_chain import REPO, chain_db  # noqa: F401  (pytest fixture)

REL = "Services/ToolService.cs"


class _LocalChunkStore:
    """A vector store whose chunks have only the absolute disk path, as local sources store them."""

    def __init__(self, abs_path):
        self.abs_path = abs_path

    def get_capabilities(self):
        return {"search_modes": ["hybrid", "semantic", "lexical"]}

    def search(self, **_kwargs):
        return [VectorSearchResult(id="dense-1", score=0.8, dense_score=0.8, payload={
            "repo": REPO, "doc_type": "code", "path": self.abs_path, "rel_path": None,
            "start_line": 3, "end_line": 12, "content": "public async Task<ToolDTO> PublishInstance(Guid id)"})]


def _track_a_hit(**_kwargs):
    return [VectorSearchResult(id="lex-1", score=0.6, sparse_score=0.6, payload={
        "repo": REPO, "doc_type": "code", "path": REL, "rel_path": REL,
        "start_line": 3, "end_line": 12, "content": "public async Task<ToolDTO> PublishInstance(Guid id)"})]


def test_store_hits_get_relative_paths_and_merge_with_track_a(chain_db):  # noqa: F811
    store = _LocalChunkStore(str(chain_db / REL).replace("/", "\\"))
    with patch("app.services.search.get_vector_store", return_value=store), \
         patch("app.services.search.run_fast_lexical_track", side_effect=_track_a_hit):
        hybrid = execute_hybrid_search("where is the tool published", repo=REPO, dense_weight=0.5)
        semantic = execute_hybrid_search("where is the tool published", repo=REPO, search_mode="semantic")
        payload = json.loads(asyncio.run(handle_search("where is the tool published", repo=REPO, dense_weight=0.5)))
    assert [h.payload["rel_path"] for h in hybrid] == [REL]
    assert hybrid[0].dense_score == 0.8 and hybrid[0].sparse_score == 0.6  # one hit from both tracks
    assert semantic[0].payload["rel_path"] == REL
    assert [r["file"] for r in payload["results"]] == [REL]


def test_paths_outside_local_roots_keep_the_stored_path(chain_db):  # noqa: F811
    store = _LocalChunkStore("D:/elsewhere/Other.cs")
    with patch("app.services.search.get_vector_store", return_value=store):
        hits = execute_hybrid_search("other", repo=REPO, search_mode="semantic")
    assert hits[0].payload["rel_path"] == "D:/elsewhere/Other.cs"


class _EmptyStore(_LocalChunkStore):
    def search(self, **_kwargs):
        return []


def test_lexical_ast_hits_of_a_local_source_use_relative_paths(chain_db):  # noqa: F811
    """Track A (AST symbols, stored with the absolute disk path for a local source) runs for real here."""
    with patch("app.services.search.get_vector_store", return_value=_EmptyStore("")):
        hits = execute_hybrid_search("PublishInstance", repo=REPO, search_mode="lexical")
        payload = json.loads(asyncio.run(handle_search("PublishInstance", repo=REPO, mode="lexical", limit=10)))
    files = {h.payload["rel_path"] for h in hits}
    assert REL in files
    assert not [f for f in files if ":/" in f or f.startswith("/")]
    assert REL in {r["file"] for r in payload["results"]}
