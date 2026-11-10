# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller specification for the ContextCortex Portable Corporate Distribution.
Bundles FastAPI, FastMCP, Tree-sitter AST grammars, PostgreSQL/pgvector drivers,
and the compiled React admin dashboard into a standalone executable directory.
"""

import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

project_root = Path(SPECPATH).resolve()

datas = []
binaries = []
hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "sqlalchemy.dialects.postgresql",
    "sqlalchemy.dialects.postgresql.psycopg",
    "sqlalchemy.dialects.sqlite",
    "psycopg",
    "psycopg_binary",
    "pgvector",
    "pgvector.sqlalchemy",
    "pgvector.psycopg",
    "mcp",
    "frontmatter",
    "fitz",
]

# Include compiled frontend assets
fe_dist = project_root / "frontend" / "dist"
www_dist = project_root / "www"
if (fe_dist / "index.html").exists():
    datas.append((str(fe_dist), "frontend/dist"))
    datas.append((str(fe_dist), "www"))
elif (www_dist / "index.html").exists():
    datas.append((str(www_dist), "www"))

# Collect all tree-sitter and tree-sitter-language-pack native shared libraries & grammars
for pkg in (
    "tree_sitter",
    "tree_sitter_language_pack",
    "psycopg",
    "psycopg_binary",
    "pgvector",
    "mcp",
    "pymupdf",
    "fitz",
):
    try:
        tmp_ret = collect_all(pkg)
        datas += tmp_ret[0]
        binaries += tmp_ret[1]
        hiddenimports += tmp_ret[2]
    except Exception:
        pass

hiddenimports += collect_submodules("app")

a = Analysis(
    [str(project_root / "main.py")],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "chromadb",
        "fastembed",
        "onnxruntime",
        "pytest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="contextcortex",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="contextcortex",
)
