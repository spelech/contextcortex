import os
import pytest

if "QDRANT_URL" not in os.environ:
    os.environ["QDRANT_URL"] = "http://localhost:8010"
