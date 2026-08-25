"""
Indexer Service Shim
Re-exports all indexing functions, dependencies, and state from app.services.indexing.
"""
import os
import uuid
import json
import threading
import asyncio
import re
import logging
from collections import Counter
from typing import Tuple, List, Dict, Any, Optional
import frontmatter

from app.services.db import *
from app.services.chunker import *
from app.services.embeddings import *
from app.services.git_manager import *
from app.services.vector_store import (
    VectorStore, VectorDocument, VectorSearchResult,
    VectorStoreManager, get_vector_store
)
from app.services.indexing import *
