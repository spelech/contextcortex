import os
import uuid
import logging
from typing import Optional, Dict, Any, Tuple
from openai import OpenAI

from app.services.database.connection import (
    get_db_connection,
    get_file_settings,
    get_chat_model,
    get_embedding_db_config,
)
from app.services.vector_store.base import VectorDocument, VectorStore
from app.services.vector_store.manager import get_vector_store

logger = logging.getLogger("contextcortex.summarizer")

DEFAULT_SYSTEM_PROMPT = (
    "You are an expert software architect and technical documentation assistant. "
    "Analyze the provided file content and produce a concise, structured markdown summary covering:\n"
    "- **Overview & Purpose**: High-level purpose and core responsibility of this file.\n"
    "- **Key Components**: Main classes, functions, interfaces, or sections.\n"
    "- **Architectural Dependencies & Data Flow**: Key imports, integrations, and interactions with other modules.\n\n"
    "Keep the summary clear, accurate, and formatted in clean markdown. Do not include introductory or concluding conversational filler."
)


def format_user_prompt(filepath: str, content: str, repo: str = "local") -> str:
    """Formats user prompt containing target file path, repo context, and content."""
    # Truncate content at reasonable limit (e.g. 200k chars) to prevent context window overflow
    max_chars = 200_000
    if len(content) > max_chars:
        content_snippet = content[:max_chars]
        truncation_note = " (truncated for LLM context ceiling)"
    else:
        content_snippet = content
        truncation_note = ""

    return (
        f"File: {filepath}{truncation_note}\n"
        f"Repository: {repo}\n\n"
        f"```\n{content_snippet}\n```\n\n"
        "Please provide the structured markdown summary."
    )


def get_summary_point_id(repo: str, rel_path: str) -> str:
    """Computes a deterministic UUID for the file's summary vector document."""
    namespace = uuid.uuid5(uuid.NAMESPACE_DNS, "contextcortex.lan")
    return str(uuid.uuid5(namespace, f"{repo}:{rel_path}#summary"))


class SummarizerService:
    """
    Summarizes source files and documents using LiteLLM / OpenAI chat completions,
    caches summaries in SQLite file_summaries table, and indexes them in the VectorStore.
    """

    def __init__(
        self,
        client: Optional[Any] = None,
        vector_store: Optional[VectorStore] = None,
    ):
        self._client = client
        self._vector_store = vector_store

    @property
    def client(self) -> Any:
        if self._client is not None:
            return self._client

        db_cfg = {}
        try:
            db_cfg = get_embedding_db_config()
        except Exception:
            pass

        litellm_url = (
            (db_cfg.get("litellm_url") if db_cfg else None)
            or os.getenv("LITELLM_URL")
            or "http://litellm:4000/v1"
        ).strip()
        litellm_key = (
            (db_cfg.get("litellm_api_key") if db_cfg else None)
            or os.getenv("LITELLM_API_KEY")
            or "dummy"
        ).strip()

        self._client = OpenAI(base_url=litellm_url, api_key=litellm_key)
        return self._client

    @client.setter
    def client(self, client_instance: Any):
        self._client = client_instance

    @property
    def vector_store(self) -> Optional[VectorStore]:
        if self._vector_store is not None:
            return self._vector_store
        try:
            return get_vector_store()
        except Exception as e:
            logger.debug(f"Vector store unavailable: {e}")
            return None

    @vector_store.setter
    def vector_store(self, store_instance: Optional[VectorStore]):
        self._vector_store = store_instance

    def _get_active_chat_model(self) -> str:
        """Resolves chat model from file settings or general chat model settings."""
        try:
            settings = get_file_settings()
            model = settings.get("summary_chat_model")
            if model and str(model).strip():
                return str(model).strip()
        except Exception as e:
            logger.debug(f"Failed to fetch file settings for chat model: {e}")

        return get_chat_model()

    def generate_file_summary(
        self,
        filepath: str,
        content: str,
        repo: str = "local",
        category: Optional[str] = None,
    ) -> Tuple[str, Optional[VectorDocument]]:
        """
        Invokes LiteLLM / OpenAI chat completions to generate a structured markdown summary.
        Returns a tuple of (summary_text, vector_document).
        """
        rel_path = filepath
        if os.path.isabs(filepath):
            try:
                rel_path = os.path.relpath(filepath, os.getcwd())
                if rel_path.startswith(".."):
                    rel_path = os.path.basename(filepath)
            except Exception:
                rel_path = os.path.basename(filepath)

        title = os.path.basename(filepath)
        folder = os.path.dirname(rel_path) or ""

        active_model = self._get_active_chat_model()
        user_prompt = format_user_prompt(filepath=rel_path, content=content, repo=repo)

        try:
            response = self.client.chat.completions.create(
                model=active_model,
                messages=[
                    {"role": "system", "content": DEFAULT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )
            summary_text = (response.choices[0].message.content or "").strip()
        except Exception as e:
            logger.warning(f"LiteLLM summarization failed for '{filepath}' using {active_model}: {e}")
            return ("", None)

        if not summary_text:
            return ("", None)

        # Generate embedding vectors if available
        dense_v = None
        s_indices = None
        s_values = None
        try:
            from app.services.embeddings import get_hybrid_embeddings
            emb = get_hybrid_embeddings(summary_text)
            dense_v = emb.get("dense")
            sparse = emb.get("sparse")
            if sparse is not None:
                s_indices = getattr(sparse, "indices", None)
                s_values = getattr(sparse, "values", None)
        except Exception:
            pass

        point_id = get_summary_point_id(repo=repo, rel_path=rel_path)
        vector_doc = VectorDocument(
            id=point_id,
            text=summary_text,
            dense_vector=dense_v,
            sparse_indices=s_indices,
            sparse_values=s_values,
            repo=repo,
            doc_type="summary",
            path=filepath,
            rel_path=rel_path,
            title=title,
            folder=folder,
            category=category,
            heading="Summary",
            start_line=1,
            end_line=1,
            metadata={
                "doc_type": "summary",
                "is_summary": True,
                "repo": repo,
                "rel_path": rel_path,
                "title": title,
                "folder": folder,
            },
        )

        return (summary_text, vector_doc)

    def get_or_create_summary(
        self,
        filepath: str,
        repo: Optional[str] = None,
        force_refresh: bool = False,
    ) -> str:
        """
        Retrieves cached summary from SQLite file_summaries table if available.
        On cache miss or force_refresh=True, reads the file, generates summary,
        updates SQLite and VectorStore, and returns summary text.
        """
        resolved_repo = repo or "local"

        # Check cached summary if not forcing refresh
        if not force_refresh:
            try:
                with get_db_connection() as conn:
                    row = conn.execute(
                        "SELECT summary_text FROM file_summaries WHERE filepath = ?",
                        (filepath,),
                    ).fetchone()
                    if row and row["summary_text"]:
                        return str(row["summary_text"])
            except Exception as e:
                logger.debug(f"Failed to query cached summary for '{filepath}': {e}")

        # Read file content from FileReaderService or disk
        content = None
        try:
            from app.services.file_reader import get_file_reader_service
            reader = get_file_reader_service()
            read_res = reader.read_file(filepath, repo=resolved_repo)
            if isinstance(read_res, dict) and "content" in read_res:
                content = read_res["content"]
        except Exception:
            content = None

        if content is None:
            if os.path.exists(filepath):
                try:
                    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                except Exception as e:
                    logger.warning(f"Failed to read file from disk '{filepath}': {e}")
            else:
                try:
                    from app.services.local_storage import get_default_storage_path
                    storage_cand = os.path.join(get_default_storage_path(), filepath)
                    if os.path.exists(storage_cand):
                        with open(storage_cand, "r", encoding="utf-8", errors="replace") as f:
                            content = f.read()
                except Exception:
                    pass

        if content is None:
            raise FileNotFoundError(f"File not found on disk or storage: {filepath}")

        # Generate summary
        summary_text, vector_doc = self.generate_file_summary(
            filepath=filepath,
            content=content,
            repo=resolved_repo,
        )

        if not summary_text:
            return ""

        # Persist summary in SQLite file_summaries
        try:
            with get_db_connection() as conn:
                existing = conn.execute(
                    "SELECT filepath FROM file_summaries WHERE filepath = ?",
                    (filepath,),
                ).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE file_summaries SET summary_text = ? WHERE filepath = ?",
                        (summary_text, filepath),
                    )
                else:
                    title = os.path.basename(filepath)
                    folder = os.path.dirname(filepath)
                    conn.execute(
                        """INSERT INTO file_summaries (filepath, repo, title, folder, summary_text)
                           VALUES (?, ?, ?, ?, ?)""",
                        (filepath, resolved_repo, title, folder, summary_text),
                    )
                conn.commit()
        except Exception as e:
            logger.warning(f"Failed to persist summary in SQLite for '{filepath}': {e}")

        # Upsert summary vector document to VectorStore
        if vector_doc is not None:
            try:
                store = self.vector_store
                if store is not None:
                    store.upsert_documents([vector_doc])
            except Exception as e:
                logger.warning(f"Failed to upsert summary vector document for '{filepath}': {e}")

        return summary_text


_summarizer_service: Optional[SummarizerService] = None


def get_summarizer_service() -> SummarizerService:
    """Retrieves or creates the SummarizerService singleton instance."""
    global _summarizer_service
    if _summarizer_service is None:
        _summarizer_service = SummarizerService()
    return _summarizer_service


def reset_summarizer_service() -> None:
    """Resets the singleton instance (primarily for test isolation)."""
    global _summarizer_service
    _summarizer_service = None
