# Changelog

## [2.27.4](https://github.com/spelech/contextcortex/compare/v2.27.3...v2.27.4) (2026-11-17)


### Bug Fixes

* **mcp:** route bug reports to diagnose_issue in the server instructions and tool descriptions ([#168](https://github.com/spelech/contextcortex/issues/168)) ([1092cf5](https://github.com/spelech/contextcortex/commit/1092cf55aa1ebd7bea1d5569186f0536159548cc))
* **trace-path:** remove duplicate candidates for an unknown symbol ([#167](https://github.com/spelech/contextcortex/issues/167)) ([79de2e0](https://github.com/spelech/contextcortex/commit/79de2e018a79431063b28f71b78b3b117d781f9d))

## [2.27.3](https://github.com/spelech/contextcortex/compare/v2.27.2...v2.27.3) (2026-11-17)


### Bug Fixes

* **trace-path:** return found false with candidates for an unknown class instead of merging same-named methods ([#165](https://github.com/spelech/contextcortex/issues/165)) ([128c75b](https://github.com/spelech/contextcortex/commit/128c75b9b86fbb96e07688daec2292900029de39))

## [2.27.2](https://github.com/spelech/contextcortex/compare/v2.27.1...v2.27.2) (2026-11-17)


### Bug Fixes

* **search:** strip the local-source root from lexical AST and summary hits ([#163](https://github.com/spelech/contextcortex/issues/163)) ([919edc4](https://github.com/spelech/contextcortex/commit/919edc45fc24dbfbe409fe386c508d4910ce4293))

## [2.27.1](https://github.com/spelech/contextcortex/compare/v2.27.0...v2.27.1) (2026-11-17)


### Bug Fixes

* **search:** return repo-relative paths for local-source chunks and merge them with lexical hits ([#160](https://github.com/spelech/contextcortex/issues/160)) ([0675183](https://github.com/spelech/contextcortex/commit/06751832cbccca5d9ce7ea7125a36d60e8d78471))
* **ui:** show the release version from package.json instead of a hard-coded v2.17.1 ([#159](https://github.com/spelech/contextcortex/issues/159)) ([7354d6a](https://github.com/spelech/contextcortex/commit/7354d6a612775a38a5d50c3df203932e8dc5b655))

## [2.27.0](https://github.com/spelech/contextcortex/compare/v2.26.1...v2.27.0) (2026-11-17)


### Features

* **code-mode:** add tools.help() in scripts and a hint on field-name errors ([fc2859b](https://github.com/spelech/contextcortex/commit/fc2859b2d3d828d5738500a616c203c1c255cdb4))
* **code-mode:** declare result types for diagnose_issue, find_routes, trace_path, find_symbol, and search ([5086f9d](https://github.com/spelech/contextcortex/commit/5086f9d5658a90dd6255e8f75a2c8d15b53038b6))
* **code-mode:** show the bug-report flow and the main result fields in the execute_script example ([e853d07](https://github.com/spelech/contextcortex/commit/e853d07c382863a3311091cfe8cfd0d9d82ebb93))

## [2.26.1](https://github.com/spelech/contextcortex/compare/v2.26.0...v2.26.1) (2026-11-17)


### Bug Fixes

* **mcp:** tell Code Mode and agents to call diagnose_issue first for a bug report ([#155](https://github.com/spelech/contextcortex/issues/155)) ([e0d0262](https://github.com/spelech/contextcortex/commit/e0d0262d55fd6aed0a37b3e0c0f85ddc91bc10b3))
* **trace-path:** show where each callee is defined next to the call-site line ([#154](https://github.com/spelech/contextcortex/issues/154)) ([7033f78](https://github.com/spelech/contextcortex/commit/7033f78136b279a7aea35a4f10296d7940995eb9))

## [2.26.0](https://github.com/spelech/contextcortex/compare/v2.25.0...v2.26.0) (2026-11-16)


### Features

* **diagnose-issue:** compare the failing path with a path that still works ([#153](https://github.com/spelech/contextcortex/issues/153)) ([1f91227](https://github.com/spelech/contextcortex/commit/1f91227863e223ea7cdde74fa25c9162c35bd376))
* **diagnose-issue:** return a ranked call chain with evidence lines ([#152](https://github.com/spelech/contextcortex/issues/152)) ([dcd80fd](https://github.com/spelech/contextcortex/commit/dcd80fdd41ade2a04fdffff70d3a4122d16ced3d))


### Bug Fixes

* **diagnose-issue:** return repo-relative paths for route-path and semantic candidates ([#150](https://github.com/spelech/contextcortex/issues/150)) ([3b0a1c9](https://github.com/spelech/contextcortex/commit/3b0a1c9fe51d102dd3cb5a421b830cdda182a868))
* **indexing:** reindex when the chunk format changes and allow forced local sync ([#149](https://github.com/spelech/contextcortex/issues/149)) ([4b73f12](https://github.com/spelech/contextcortex/commit/4b73f12289171514af02bf4532e193784640dcd7))
* **indexing:** report is_indexing from the indexing lock ([#143](https://github.com/spelech/contextcortex/issues/143)) ([66dac5f](https://github.com/spelech/contextcortex/commit/66dac5fc89e4de21da38ad04e58557a7a84e5568))
* **logging:** send application logs to stdout and the Admin UI log view ([#144](https://github.com/spelech/contextcortex/issues/144)) ([6e01246](https://github.com/spelech/contextcortex/commit/6e01246238ba07d6fb12ac257a03fe4188d0ee36))
* **mcp:** find_symbol takes symbol like trace_path, keeps name as alias ([#146](https://github.com/spelech/contextcortex/issues/146)) ([24ad851](https://github.com/spelech/contextcortex/commit/24ad8516c1db6517617479c6e77570c11c6278dd))
* **portable:** listen on 127.0.0.1 and ::1 when HOST=localhost ([#142](https://github.com/spelech/contextcortex/issues/142)) ([14d9172](https://github.com/spelech/contextcortex/commit/14d91722de96765aabbec3bdbe926f660074182c))
* **trace-path:** hide test doubles and group library calls in callees ([#148](https://github.com/spelech/contextcortex/issues/148)) ([29d4893](https://github.com/spelech/contextcortex/commit/29d4893ec863096957fe4bbdd3bd1cc7ed764e7c))


### Performance Improvements

* **mcp:** compact grep_code and read_file output ([#147](https://github.com/spelech/contextcortex/issues/147)) ([14a5a4f](https://github.com/spelech/contextcortex/commit/14a5a4f2d4ce4978e708fe2783e4f5635b180f79))

## [2.25.0](https://github.com/spelech/contextcortex/compare/v2.24.1...v2.25.0) (2026-11-13)


### Features

* **mcp:** ripgrep default, 10-tool MCP surface, parallel query router, and benchmarks ([#140](https://github.com/spelech/contextcortex/issues/140)) ([22bd3a5](https://github.com/spelech/contextcortex/commit/22bd3a53eaf77ed6e2acf646665d4aa2fc475bb8))

## [2.24.1](https://github.com/spelech/contextcortex/compare/v2.24.0...v2.24.1) (2026-11-12)


### Bug Fixes

* **trace-path:** follow own-class calls and ignore test doubles ([#138](https://github.com/spelech/contextcortex/issues/138)) ([24a9b55](https://github.com/spelech/contextcortex/commit/24a9b5547a076e6fe75eb834f04cc14bee74c36d))

## [2.24.0](https://github.com/spelech/contextcortex/compare/v2.23.3...v2.24.0) (2026-11-12)


### Features

* **mcp:** add Code Mode (execute_script) with a sandboxed V8 engine ([#136](https://github.com/spelech/contextcortex/issues/136)) ([1f60139](https://github.com/spelech/contextcortex/commit/1f60139e184b3a4b405f4b09c5635102fe1071be))


### Bug Fixes

* **api-callers:** give each client call to its most specific route ([#134](https://github.com/spelech/contextcortex/issues/134)) ([b975619](https://github.com/spelech/contextcortex/commit/b975619e2779401767317d4292199ce842361746))
* **diagnose:** respect the repo filter and rank candidates from the matched route ([#132](https://github.com/spelech/contextcortex/issues/132)) ([79aecc8](https://github.com/spelech/contextcortex/commit/79aecc8fe1888513c9186198b23c2014f64c6730))
* **grep-code:** give each context line its own line number ([#135](https://github.com/spelech/contextcortex/issues/135)) ([6bbd20d](https://github.com/spelech/contextcortex/commit/6bbd20dc85bfe501c9a90a390b2bb35e315a86e8))
* **paths:** return repository-relative paths for local sources ([#133](https://github.com/spelech/contextcortex/issues/133)) ([5a58141](https://github.com/spelech/contextcortex/commit/5a581418ac74d22bd6db93f387bc8de5713d2e1f))

## [2.23.3](https://github.com/spelech/contextcortex/compare/v2.23.2...v2.23.3) (2026-11-12)


### Bug Fixes

* **api-callers:** resolve URL constants, URL variables, and unresolved bases ([#130](https://github.com/spelech/contextcortex/issues/130)) ([1f811d8](https://github.com/spelech/contextcortex/commit/1f811d83bc53fbc6b7fb4f67a8fdb0e9421f1532))
* **grep-code:** accept folder paths and retry regex-like patterns ([#129](https://github.com/spelech/contextcortex/issues/129)) ([c576f22](https://github.com/spelech/contextcortex/commit/c576f22b14723d4be6fc2955fec467ef54c09839))

## [2.23.2](https://github.com/spelech/contextcortex/compare/v2.23.1...v2.23.2) (2026-11-12)


### Bug Fixes

* **trace-path:** store C# call targets with the receiver's declared type ([#126](https://github.com/spelech/contextcortex/issues/126)) ([b2a7e52](https://github.com/spelech/contextcortex/commit/b2a7e523e5ccc86b42fd7edc316995561f905c14))
* **trace-path:** use portable case-insensitive symbol lookup ([#127](https://github.com/spelech/contextcortex/issues/127)) ([f64252e](https://github.com/spelech/contextcortex/commit/f64252e3faff22ca4c100ec8875e59b3f19b0ec5))

## [2.23.1](https://github.com/spelech/contextcortex/compare/v2.23.0...v2.23.1) (2026-11-12)


### Bug Fixes

* **api-callers:** resolve C# request URLs built in variables ([#124](https://github.com/spelech/contextcortex/issues/124)) ([3115d83](https://github.com/spelech/contextcortex/commit/3115d8323536f547fc7395dc76bc0ce788ac543c))
* **file-reads:** read UTF-16 text files in read_file, summarize_file, and grep_code ([#122](https://github.com/spelech/contextcortex/issues/122)) ([9426590](https://github.com/spelech/contextcortex/commit/9426590f261598bbc13e67e3e7b26aedba8feb98))
* **trace-path:** keep only injected callers of same-named methods ([#123](https://github.com/spelech/contextcortex/issues/123)) ([682f1d0](https://github.com/spelech/contextcortex/commit/682f1d06ac04573e16e0dbbb0456b4ad96d4701b))

## [2.23.0](https://github.com/spelech/contextcortex/compare/v2.22.0...v2.23.0) (2026-11-12)


### Features

* **trace-path:** compact answers without per-node permalinks by default ([afc42bd](https://github.com/spelech/contextcortex/commit/afc42bd936dc37043071d12969943f799203e339))


### Bug Fixes

* **api-callers:** recognize JS/TS request helpers with template-literal URLs ([afc42bd](https://github.com/spelech/contextcortex/commit/afc42bd936dc37043071d12969943f799203e339))
* **indexing:** decode UTF-16 sources and isolate PostgreSQL upsert failures ([#118](https://github.com/spelech/contextcortex/issues/118)) ([8dd1799](https://github.com/spelech/contextcortex/commit/8dd179996a225c6c577dd4deeacc9c90224b678a))

## [2.22.0](https://github.com/spelech/contextcortex/compare/v2.21.4...v2.22.0) (2026-11-12)


### Features

* **ast,cobol:** add multi-language AST extraction and cross-file linking for COBOL, C#, TS/TSX, and Python ([66f374d](https://github.com/spelech/contextcortex/commit/66f374dd63a58e3bf0dc3249361f1b536f27f8df))
* **core,ast,mcp:** multi-language AST linking, first-class COBOL support, and modular &lt;= 500 LOC architecture ([386babf](https://github.com/spelech/contextcortex/commit/386babfa4ea8c6971717693b297ffd4abc19db1b))
* **mcp:** add bounded pagination, complete parameter docs, and modular knowledge resources ([3231cf6](https://github.com/spelech/contextcortex/commit/3231cf69d12da279a191f7c4daab8f5eca9e8736))
* **ui:** add multi-language badges, syntax rendering, modular styling, and layout stability ([8e17484](https://github.com/spelech/contextcortex/commit/8e17484b854174dfa3d96ba7f885e2346c996576))


### Bug Fixes

* **security:** resolve CodeQL path injection alerts with explicit startswith barriers ([d759063](https://github.com/spelech/contextcortex/commit/d7590634a47f18029943a14cddc1d2a6ee510741))
* **security:** sanitize path resolver barriers and settings exception exposure for CodeQL ([bf9206b](https://github.com/spelech/contextcortex/commit/bf9206b063a16a30c13ecb59e6f3f749b1b6af05))
* **storage,diagnostics:** persist multi-language relationships in local storage and enhance stack trace parsing ([c7d6c56](https://github.com/spelech/contextcortex/commit/c7d6c5622a763615bf23b865572accaa47bf482f))

## [2.21.4](https://github.com/spelech/contextcortex/compare/v2.21.3...v2.21.4) (2026-11-12)


### Bug Fixes

* **diagnostics:** scope stack-frame callees to enclosing file/lines and prioritize production callers ([c947374](https://github.com/spelech/contextcortex/commit/c9473741f150c91b50e6f41fb7806f6b3ea99c62))

## [2.21.3](https://github.com/spelech/contextcortex/compare/v2.21.2...v2.21.3) (2026-11-12)


### Bug Fixes

* **database,docker:** add FK cascade indexes for fast startup deduplication and upgrade Dockerfile to Python 3.12 ([6c6beaa](https://github.com/spelech/contextcortex/commit/6c6beaa23dc18f62fbc3eb135fd68e92d2dc03dd))
* **git:** remove read-only .git packfiles on Windows when falling back to fresh clone ([#112](https://github.com/spelech/contextcortex/issues/112)) ([162c2b0](https://github.com/spelech/contextcortex/commit/162c2b0692a7ca505f48ba4344cab308843048a6))

## [2.21.2](https://github.com/spelech/contextcortex/compare/v2.21.1...v2.21.2) (2026-11-11)


### Bug Fixes

* **portable:** bundle tree-sitter grammars next to the exe and load them from there ([#110](https://github.com/spelech/contextcortex/issues/110)) ([a352cde](https://github.com/spelech/contextcortex/commit/a352cde302e7a4e1377c3559b06f89b3645deb0a))

## [2.21.1](https://github.com/spelech/contextcortex/compare/v2.21.0...v2.21.1) (2026-11-11)


### Bug Fixes

* **portable:** make the Windows x64 portable bundle start on Windows ([#108](https://github.com/spelech/contextcortex/issues/108)) ([38d2abe](https://github.com/spelech/contextcortex/commit/38d2abeaed68991a2c85d712b975cd0266ea0e69))

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
