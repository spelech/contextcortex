"""Bounded channel producer-consumer pipeline (modeled after C# System.Threading.Channels)
for overlapping file AST parsing, embedding cache lookup, parallel API slice embedding,
and database/vector store persistence."""

import logging
import queue
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generic, Iterator, List, Optional, Tuple, TypeVar

from app.services.embedding_batcher import (
    estimate_token_count,
    partition_texts_into_slices,
    telemetry_tracker,
)
from app.services.memory_utils import trim_memory
from app.services.vector_store import VectorDocument

logger = logging.getLogger("contextcortex.indexer.pipeline")

T = TypeVar("T")
_CHANNEL_SENTINEL = object()


class BoundedChannel(Generic[T]):
    """Thread-safe bounded channel with backpressure, completion, and error propagation
    (modeled after C# System.Threading.Channels.Channel.CreateBounded<T>)."""

    def __init__(self, capacity: int = 64) -> None:
        self.capacity = max(1, int(capacity))
        self._queue: "queue.Queue[Any]" = queue.Queue(maxsize=self.capacity)
        self._lock = threading.Lock()
        self._completed = False
        self._cancelled = False
        self._error: Optional[BaseException] = None

    def write(self, item: T, timeout: float = 0.25) -> bool:
        """Writes an item to the channel, blocking while full unless completed or cancelled."""
        while True:
            with self._lock:
                if self._cancelled or self._error is not None:
                    return False
                if self._completed:
                    raise RuntimeError("Cannot write to a completed BoundedChannel.")
            try:
                self._queue.put(item, timeout=timeout)
                return True
            except queue.Full:
                continue

    def complete(self) -> None:
        """Marks the channel as complete (no further items will be written)."""
        with self._lock:
            if self._completed:
                return
            self._completed = True
        self._put_sentinel()

    def cancel(self) -> None:
        """Cancels the channel and unblocks any waiting readers or writers."""
        with self._lock:
            self._cancelled = True
            self._completed = True
        self._drain_and_put_sentinel()

    def fail(self, exc: BaseException) -> None:
        """Signals an upstream failure and unblocks readers and writers."""
        with self._lock:
            if self._error is None:
                self._error = exc
            self._completed = True
        self._drain_and_put_sentinel()

    @property
    def error(self) -> Optional[BaseException]:
        with self._lock:
            return self._error

    def _put_sentinel(self) -> None:
        while True:
            try:
                self._queue.put(_CHANNEL_SENTINEL, timeout=0.05)
                return
            except queue.Full:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass

    def _drain_and_put_sentinel(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._put_sentinel()

    def read_all(self) -> Iterator[T]:
        """Yields items until the channel is completed and drained, raising any upstream error."""
        while True:
            with self._lock:
                if self._cancelled:
                    return
                if self._error is not None and self._queue.empty():
                    raise self._error
            try:
                item = self._queue.get(timeout=0.1)
            except queue.Empty:
                with self._lock:
                    if self._error is not None:
                        raise self._error
                    if self._completed and self._queue.empty():
                        return
                continue

            if item is _CHANNEL_SENTINEL:
                with self._lock:
                    if self._error is not None:
                        raise self._error
                self._put_sentinel()
                return

            yield item


@dataclass
class ParsedFileItem:
    """Single parsed file output produced by Stage 1 (AST/Markdown chunker)."""

    filepath: str
    rel_path: str
    repo: str
    points: List[VectorDocument] = field(default_factory=list)
    symbols: List[Dict[str, Any]] = field(default_factory=list)
    summary_tuple: Optional[Tuple] = None
    relationships: List[Dict[str, Any]] = field(default_factory=list)
    routes: List[Dict[str, Any]] = field(default_factory=list)
    calls: List[Dict[str, Any]] = field(default_factory=list)
    indexed_file_row: Optional[Tuple] = None
    extra_meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PendingPersistBatch:
    """Coalesced batch of parsed files with in-flight embedding slice futures from Stage 2/3."""

    items: List[ParsedFileItem]
    point_hashes: List[Tuple[VectorDocument, str]]
    cached_map: Dict[str, Dict[str, Any]]
    unseen_hashes: List[str]
    slice_futures: List[Tuple[List[str], Future]]
    active_model: str
    use_raw_hybrid_future: bool = False


class ChannelIngestionPipeline:
    """4-stage bounded channel pipeline:
    Stage 1 (Producer): Parses files into AST/Markdown chunks -> parsed_channel.
    Stage 2 (Coalescer & Cache Filter): Queries embedding_cache by SHA256(content), slices cache misses,
      and submits slice tasks immediately to Stage 3 -> persist_channel.
    Stage 3 (Parallel API Pool): Persistent ThreadPoolExecutor running concurrent API embedding slices
      across batches with HTTP 429 Retry-After & AIMD concurrency control.
    Stage 4 (Consumer): Awaits completed slice futures per batch, caches vectors, and persists to DB/vector store.
    """

    def __init__(
        self,
        persist_batch_fn: Callable[[List[ParsedFileItem]], None],
        file_batch_size: int = 25,
        parsed_channel_capacity: int = 64,
        persist_channel_capacity: int = 8,
    ) -> None:
        self.persist_batch_fn = persist_batch_fn
        self.file_batch_size = max(1, int(file_batch_size))
        self.parsed_channel: BoundedChannel[ParsedFileItem] = BoundedChannel(capacity=parsed_channel_capacity)
        self.persist_channel: BoundedChannel[PendingPersistBatch] = BoundedChannel(capacity=persist_channel_capacity)

    def run(self, producer_fn: Callable[[BoundedChannel[ParsedFileItem]], None]) -> None:
        """Runs the 4-stage pipeline to completion, propagating any stage exception."""
        import app.services.embeddings as emb_service
        import app.services.indexing.processor as proc_service
        from app.services.database import get_cached_embeddings_batch, set_cached_embeddings_batch
        from app.services.embedding_batcher import execute_api_embeddings_batch

        max_conc = max(1, int(getattr(emb_service, "EMBEDDING_API_CONCURRENCY", 4) or 4))
        inflight_hash_futures: Dict[str, Future] = {}
        inflight_lock = threading.Lock()

        embed_executor = ThreadPoolExecutor(max_workers=max(4, max_conc * 2))

        def _stage1_producer() -> None:
            try:
                producer_fn(self.parsed_channel)
                self.parsed_channel.complete()
            except BaseException as exc:
                logger.error(f"Pipeline Stage 1 (Producer) failed: {exc}")
                self.parsed_channel.fail(exc)
                self.persist_channel.fail(exc)

        def _stage2_coalescer() -> None:
            try:
                batch_items: List[ParsedFileItem] = []
                for item in self.parsed_channel.read_all():
                    batch_items.append(item)
                    if len(batch_items) >= self.file_batch_size:
                        self._dispatch_batch(
                            batch_items,
                            embed_executor,
                            inflight_hash_futures,
                            inflight_lock,
                            emb_service,
                            proc_service,
                            get_cached_embeddings_batch,
                            execute_api_embeddings_batch,
                        )
                        batch_items = []
                if batch_items:
                    self._dispatch_batch(
                        batch_items,
                        embed_executor,
                        inflight_hash_futures,
                        inflight_lock,
                        emb_service,
                        proc_service,
                        get_cached_embeddings_batch,
                        execute_api_embeddings_batch,
                    )
                self.persist_channel.complete()
            except BaseException as exc:
                logger.error(f"Pipeline Stage 2 (Coalescer) failed: {exc}")
                self.parsed_channel.cancel()
                self.persist_channel.fail(exc)

        t1 = threading.Thread(target=_stage1_producer, name="cc-pipeline-stage1-parser", daemon=True)
        t2 = threading.Thread(target=_stage2_coalescer, name="cc-pipeline-stage2-coalescer", daemon=True)
        t1.start()
        t2.start()

        try:
            for pending_batch in self.persist_channel.read_all():
                self._finalize_and_persist_batch(
                    pending_batch,
                    proc_service,
                    set_cached_embeddings_batch,
                )
            t1.join()
            t2.join()
            if self.parsed_channel.error is not None:
                raise self.parsed_channel.error
            if self.persist_channel.error is not None:
                raise self.persist_channel.error
        finally:
            self.parsed_channel.cancel()
            self.persist_channel.cancel()
            embed_executor.shutdown(wait=True, cancel_futures=False)

    def _dispatch_batch(
        self,
        items: List[ParsedFileItem],
        embed_executor: ThreadPoolExecutor,
        inflight_hash_futures: Dict[str, Future],
        inflight_lock: threading.Lock,
        emb_service: Any,
        proc_service: Any,
        get_cached_embeddings_batch: Callable,
        execute_api_embeddings_batch: Callable,
    ) -> None:
        active_model = proc_service._get_indexer_attr("DENSE_MODEL_NAME", emb_service.DENSE_MODEL_NAME)
        point_hashes: List[Tuple[VectorDocument, str]] = []
        hash_to_text: Dict[str, str] = {}

        for item in items:
            for pt in item.points:
                embed_text = pt.metadata.pop("_embed_text", None) if isinstance(pt.metadata, dict) else None
                if pt.dense_vector is not None:
                    continue
                raw_content = (pt.text or "").strip()
                formatted = embed_text or raw_content
                if not formatted:
                    continue
                h = proc_service.compute_text_hash(raw_content)
                point_hashes.append((pt, h))
                if h not in hash_to_text:
                    hash_to_text[h] = formatted

        if not point_hashes:
            self.persist_channel.write(
                PendingPersistBatch(
                    items=items,
                    point_hashes=[],
                    cached_map={},
                    unseen_hashes=[],
                    slice_futures=[],
                    active_model=active_model,
                )
            )
            return

        all_hashes = list(hash_to_text.keys())
        cached_map = get_cached_embeddings_batch(all_hashes, model_name=active_model)

        unseen_hashes: List[str] = []
        unseen_texts: List[str] = []
        for h in all_hashes:
            if h not in cached_map:
                unseen_hashes.append(h)
                unseen_texts.append(hash_to_text[h])

        embed_fn = proc_service._get_indexer_attr(
            "get_hybrid_embeddings_batch",
            proc_service.get_hybrid_embeddings_batch,
        )
        is_default_embed_fn = embed_fn is emb_service.get_hybrid_embeddings_batch
        is_api_provider = getattr(emb_service, "EMBEDDING_PROVIDER", "local") == "api"

        slice_futures: List[Tuple[List[str], Future]] = []
        use_raw_hybrid = False

        if unseen_hashes:
            if is_default_embed_fn and is_api_provider:
                api_bs = max(1, min(int(getattr(emb_service, "EMBEDDING_BATCH_SIZE", 128) or 128), 256))
                max_tok = max(1, int(getattr(emb_service, "EMBEDDING_MAX_TOKENS_PER_REQUEST", 100000) or 100000))
                max_conc = max(1, int(getattr(emb_service, "EMBEDDING_API_CONCURRENCY", 4) or 4))
                tpm = max(0, int(getattr(emb_service, "EMBEDDING_TPM_LIMIT", 0) or 0))
                client = getattr(emb_service, "_openai_client", None)
                model_name = getattr(emb_service, "DENSE_MODEL_NAME", active_model)

                # Partition (hash, text) pairs into token- and size-bounded slices
                slices_pairs: List[Tuple[List[str], List[str]]] = []
                cur_h: List[str] = []
                cur_t: List[str] = []
                cur_tok = 0
                for h, t in zip(unseen_hashes, unseen_texts):
                    t_tok = estimate_token_count(t)
                    if cur_t and (len(cur_t) >= api_bs or (cur_tok + t_tok) > max_tok):
                        slices_pairs.append((cur_h, cur_t))
                        cur_h, cur_t, cur_tok = [h], [t], t_tok
                    else:
                        cur_h.append(h)
                        cur_t.append(t)
                        cur_tok += t_tok
                if cur_t:
                    slices_pairs.append((cur_h, cur_t))

                active_futs: List[Future] = []
                for s_hashes, s_texts in slices_pairs:
                    active_futs = [f for f in active_futs if not f.done()]
                    eff_conc = telemetry_tracker.get_effective_concurrency(max_conc)
                    while len(active_futs) >= eff_conc:
                        time.sleep(0.005)
                        active_futs = [f for f in active_futs if not f.done()]
                        eff_conc = telemetry_tracker.get_effective_concurrency(max_conc)

                    fut = embed_executor.submit(
                        execute_api_embeddings_batch,
                        client=client,
                        texts=s_texts,
                        model_name=model_name,
                        batch_size=len(s_texts),
                        max_concurrency=1,
                        max_tokens_per_request=max_tok,
                        tpm_limit=tpm,
                    )
                    active_futs.append(fut)
                    slice_futures.append((s_hashes, fut))
            else:
                use_raw_hybrid = True
                fut = embed_executor.submit(embed_fn, unseen_texts)
                slice_futures.append((unseen_hashes, fut))

        self.persist_channel.write(
            PendingPersistBatch(
                items=items,
                point_hashes=point_hashes,
                cached_map=cached_map,
                unseen_hashes=unseen_hashes,
                slice_futures=slice_futures,
                active_model=active_model,
                use_raw_hybrid_future=use_raw_hybrid,
            )
        )

    def _finalize_and_persist_batch(
        self,
        batch: PendingPersistBatch,
        proc_service: Any,
        set_cached_embeddings_batch: Callable,
    ) -> None:
        if batch.point_hashes:
            items_to_cache: List[Dict[str, Any]] = []
            if batch.use_raw_hybrid_future:
                for s_hashes, fut in batch.slice_futures:
                    new_vectors = fut.result()
                    for i, h in enumerate(s_hashes):
                        nv = new_vectors[i] if i < len(new_vectors) and isinstance(new_vectors[i], dict) else {}
                        dense_v = nv.get("dense")
                        s_indices, s_values = proc_service._extract_sparse_tuple(nv.get("sparse"))
                        batch.cached_map[h] = {
                            "dense": dense_v,
                            "sparse_indices": s_indices,
                            "sparse_values": s_values,
                        }
                        items_to_cache.append({
                            "chunk_hash": h,
                            "dense_vector": dense_v,
                            "sparse_indices": s_indices,
                            "sparse_values": s_values,
                            "model_name": batch.active_model,
                        })
            else:
                for s_hashes, fut in batch.slice_futures:
                    dense_vecs = fut.result()
                    for i, h in enumerate(s_hashes):
                        dense_v = dense_vecs[i] if i < len(dense_vecs) else None
                        batch.cached_map[h] = {
                            "dense": dense_v,
                            "sparse_indices": None,
                            "sparse_values": None,
                        }
                        items_to_cache.append({
                            "chunk_hash": h,
                            "dense_vector": dense_v,
                            "sparse_indices": None,
                            "sparse_values": None,
                            "model_name": batch.active_model,
                        })

            if items_to_cache:
                from app.services.indexing.db_write_channel import submit_db_write

                submit_db_write(lambda: set_cached_embeddings_batch(items_to_cache))
                trim_memory()

            for pt, h in batch.point_hashes:
                bv = batch.cached_map.get(h, {})
                pt.dense_vector = bv.get("dense")
                pt.sparse_indices = bv.get("sparse_indices")
                pt.sparse_values = bv.get("sparse_values")

        self.persist_batch_fn(batch.items)
