import re

with open('server_old.py', 'r') as f:
    lines = f.readlines()

def get_lines(start_idx, end_idx=None):
    if end_idx is None:
        end_idx = len(lines)
    return "".join(lines[start_idx:end_idx])

# Identify boundaries
imports = "".join(lines[:45]) # imports and logging

# We need everything from notify_list_changed (58) down to run_full_indexing (end of it, around 630)
indexer_lines = []
search_lines = []

in_search = False
for line in lines[45:]:
    if line.startswith("def execute_hybrid_search"):
        in_search = True
    if line.startswith("mcp_server = Server"):
        in_search = False
        break
    if in_search:
        search_lines.append(line)

with open('app/services/indexer.py', 'w') as f:
    f.write("import os\nimport uuid\nimport json\nimport threading\nimport asyncio\nimport re\nimport logging\nfrom collections import Counter\nfrom typing import Tuple, List, Dict, Any, Optional\n")
    f.write("from app.services.db import *\nfrom app.services.chunker import *\nfrom app.services.embeddings import *\nfrom app.services.git_manager import *\nfrom qdrant_client.http import models as qmodels\n\n")
    f.write("logger = logging.getLogger('notes-rag-mcp')\n")
    f.write("active_sessions = set()\nmain_event_loop = None\n")
    f.write(get_lines(57, 630))

with open('app/services/search.py', 'w') as f:
    f.write("import logging\nfrom typing import Optional, List\nfrom qdrant_client.http import models as qmodels\nfrom app.services.embeddings import *\n")
    f.write("logger = logging.getLogger('notes-rag-mcp')\n")
    f.write("".join(search_lines))

