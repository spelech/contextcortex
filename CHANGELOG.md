# Changelog

## [2.21.0](https://github.com/spelech/contextcortex/compare/v2.20.0...v2.21.0) (2026-11-11)


### Features

* **config,docs:** rename AI gateway env vars to OPENAI_API_URL/KEY and update model discovery & docs ([#93](https://github.com/spelech/contextcortex/issues/93)) ([1ea3116](https://github.com/spelech/contextcortex/commit/1ea3116b2ab09dbd68b631cd1d07d1ca58c3321f))
* **git:** add configurable commit history retention and get_recent_changes MCP tool (closes [#101](https://github.com/spelech/contextcortex/issues/101)) ([#107](https://github.com/spelech/contextcortex/issues/107)) ([5225cc0](https://github.com/spelech/contextcortex/commit/5225cc0da5e56832abe62ef398d2e86beee1d06a))
* **mcp:** add diagnose_issue MCP tool for stack-trace, log, and bug description triage ([#103](https://github.com/spelech/contextcortex/issues/103)) ([6b965c6](https://github.com/spelech/contextcortex/commit/6b965c6f57992eda675e36b82e639d684a1af98f))
* **mcp:** add grep_code MCP tool and backend-agnostic line-accurate vector file reconstruction ([#105](https://github.com/spelech/contextcortex/issues/105)) ([88b1a39](https://github.com/spelech/contextcortex/commit/88b1a39b75ca606a80f104d3cea0abeffb1df4b7))
* **packaging:** add Windows x64 portable bundle with user-space PostgreSQL and pgvector ([fbf86bc](https://github.com/spelech/contextcortex/commit/fbf86bc34f775aff3571d6dd6e1296442dd0ac67))
* **packaging:** add Windows x64 portable bundle with user-space PostgreSQL and pgvector ([c341127](https://github.com/spelech/contextcortex/commit/c3411270919e74849f8e9caa912b7504af8a9635))
* **pgvector,git:** add PostgreSQL FTS lexical/hybrid search and native SSH/glab support ([#90](https://github.com/spelech/contextcortex/issues/90)) ([61d7a12](https://github.com/spelech/contextcortex/commit/61d7a122132454a48b24f002d9b13ec9d00b9a0f))
* **trace:** add cross-repo HTTP boundary resolution and compact JSON output to trace_path (closes [#99](https://github.com/spelech/contextcortex/issues/99)) ([#106](https://github.com/spelech/contextcortex/issues/106)) ([b99239f](https://github.com/spelech/contextcortex/commit/b99239f23eebfcbe6f1f87f96e803e7d5babb940))
* **ui,settings:** remove local FastEmbed/ONNX UI options and standardize on API embeddings ([#91](https://github.com/spelech/contextcortex/issues/91)) ([e38b363](https://github.com/spelech/contextcortex/commit/e38b363626fe605d830992d208612936d7a3c956))
* **ui,vector-store:** consolidate vector database options to Qdrant and PostgreSQL pgvector ([aaddb08](https://github.com/spelech/contextcortex/commit/aaddb08da4df3c5332be203d552a8add0b31bcbc))
* **ui,vector-store:** consolidate vector database options to Qdrant and PostgreSQL pgvector ([05534e4](https://github.com/spelech/contextcortex/commit/05534e48d235836960493bee4660c6cbf2351f6b))


### Bug Fixes

* **database:** restore native PostgreSQL readiness probes ([9549da4](https://github.com/spelech/contextcortex/commit/9549da4c5ce6d4b4019df6d6b1e9a4203678ff64)), closes [#50](https://github.com/spelech/contextcortex/issues/50)
* fail ingestion when vector persistence fails ([#78](https://github.com/spelech/contextcortex/issues/78)) ([a1618ce](https://github.com/spelech/contextcortex/commit/a1618ceadbe9f8025388b5fff8800e75910371f5))
* initialize and migrate pgvector tables transactionally ([#54](https://github.com/spelech/contextcortex/issues/54)) ([0642ff1](https://github.com/spelech/contextcortex/commit/0642ff1b35424c1460e6a4ba087737e53cd585fc))
* **mcp:** bypass ping middleware for active sse sessions and clean up corrupted target dirs ([853f305](https://github.com/spelech/contextcortex/commit/853f3057b46a2e574048119cf76d300b8ec18ff1))
* **mcp:** bypass ping middleware for active SSE sessions and clean up corrupted target dirs ([ecb8513](https://github.com/spelech/contextcortex/commit/ecb851354ce8d4a84439594826a00fd71b7b1d3b))
* **pdf:** isolate test db path and restore local embeddings in fixture teardown ([000afe4](https://github.com/spelech/contextcortex/commit/000afe4ae4ceb499c0c2862ea7add8e0876d4b7a))
* **pgvector:** guard postgresql-specific ddl against sqlite test engines ([ecfbff8](https://github.com/spelech/contextcortex/commit/ecfbff82d6e2b0a6fa5e44abdf19d6d372f96ff8))
* **pgvector:** make native initialization and legacy migration atomic ([4063816](https://github.com/spelech/contextcortex/commit/40638167fe5209929f47cd316d8cbbf90673f5c4))
* **pgvector:** merge main, sync requirements and increase vitest testTimeout ([2e0e5b7](https://github.com/spelech/contextcortex/commit/2e0e5b708a78b6c50a1b3c27094e0f8c6bc690dc))
* restore native PostgreSQL readiness probes ([#50](https://github.com/spelech/contextcortex/issues/50)) ([582fc46](https://github.com/spelech/contextcortex/commit/582fc4612b1e2d3bd3e215ac0857d2bbd97a80ec))
* **storage:** fail uploads when vector indexing fails ([973f3e5](https://github.com/spelech/contextcortex/commit/973f3e5d3bca085b9d895e264f9d25552134e122))
* **storage:** upsert PDF extraction cache across database backends ([388c77e](https://github.com/spelech/contextcortex/commit/388c77e38c1fee847e9f1a0ba0b884ec180318ef)), closes [#77](https://github.com/spelech/contextcortex/issues/77)
* support PostgreSQL PDF extraction cache upserts ([#77](https://github.com/spelech/contextcortex/issues/77)) ([9530095](https://github.com/spelech/contextcortex/commit/953009509ae45be3997687fef24f4362509f131d))
* **test:** reset default dense and sparse models during fixture teardown ([7bd98f4](https://github.com/spelech/contextcortex/commit/7bd98f4aa7e3bdd89a344dbb2281dd496937eeff))


### Performance Improvements

* **memory:** tune glibc malloc arenas and trim memory post-ingestion ([#85](https://github.com/spelech/contextcortex/issues/85)) ([ebf328d](https://github.com/spelech/contextcortex/commit/ebf328d65c0a6a16403f494256fa00404d44f4bd))
* **memory:** tune glibc malloc arenas and trim memory post-ingestion ([#85](https://github.com/spelech/contextcortex/issues/85)) ([5f57039](https://github.com/spelech/contextcortex/commit/5f570392b193f74aaa4ad94ada14e569c77bb9af))
