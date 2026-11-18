import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("contextcortex.embeddings")


def estimate_token_count(text: str) -> int:
    """Estimates token count for a single string (~4 characters per token, minimum 1)."""
    if not text:
        return 1
    return max(1, len(text) // 4)


def partition_texts_into_slices(
    texts: List[str],
    max_items_per_slice: int = 128,
    max_tokens_per_request: int = 100000,
) -> List[List[str]]:
    """Partitions input texts into request slices bounded by both item count and estimated token limit."""
    if not texts:
        return []
    max_items = max(1, int(max_items_per_slice or 128))
    max_tokens = max(1, int(max_tokens_per_request or 100000))

    slices: List[List[str]] = []
    current_slice: List[str] = []
    current_tokens = 0

    for text in texts:
        t_tokens = estimate_token_count(text)
        if current_slice and (
            len(current_slice) >= max_items or (current_tokens + t_tokens) > max_tokens
        ):
            slices.append(current_slice)
            current_slice = [text]
            current_tokens = t_tokens
        else:
            current_slice.append(text)
            current_tokens += t_tokens

    if current_slice:
        slices.append(current_slice)
    return slices


def _extract_retry_after_seconds(exc: Exception, default_wait: float) -> float:
    """Extracts Retry-After or retry-after-ms wait duration from an HTTP 429 exception if present."""
    headers: Dict[str, Any] = {}
    resp = getattr(exc, "response", None)
    if resp is not None:
        resp_headers = getattr(resp, "headers", None)
        if resp_headers:
            try:
                headers = {str(k).lower(): str(v) for k, v in dict(resp_headers).items()}
            except Exception:
                pass
    exc_headers = getattr(exc, "headers", None)
    if not headers and exc_headers:
        try:
            headers = {str(k).lower(): str(v) for k, v in dict(exc_headers).items()}
        except Exception:
            pass

    if "retry-after-ms" in headers:
        try:
            return max(0.05, float(headers["retry-after-ms"].strip()) / 1000.0)
        except (ValueError, TypeError):
            pass

    if "retry-after" in headers:
        try:
            return max(0.05, float(headers["retry-after"].strip()))
        except (ValueError, TypeError):
            pass

    return max(0.05, default_wait)


def _is_rate_limit_error(exc: Exception) -> bool:
    """Returns True if the exception represents an HTTP 429 rate-limit error."""
    status_code = getattr(exc, "status_code", None)
    if status_code == 429:
        return True
    resp = getattr(exc, "response", None)
    if resp is not None and getattr(resp, "status_code", None) == 429:
        return True
    cls_name = exc.__class__.__name__.lower()
    if "ratelimit" in cls_name:
        return True
    msg = str(exc).lower()
    return "429" in msg or "rate limit" in msg or "rate_limit" in msg


class EmbeddingTelemetryAndPacer:
    """Tracks embedding throughput, HTTP 429 wait times, AIMD concurrency, and optional TPM pacing."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.chunks_embedded: int = 0
        self.embedding_seconds: float = 0.0
        self.rate_limit_wait_seconds: float = 0.0
        self.rate_limit_hits: int = 0
        self._current_concurrency: Optional[int] = None
        self._consecutive_successes: int = 0
        self._window_start: float = time.monotonic()
        self._window_tokens: int = 0

    def reset(self, target_concurrency: Optional[int] = None) -> None:
        with self._lock:
            self.chunks_embedded = 0
            self.embedding_seconds = 0.0
            self.rate_limit_wait_seconds = 0.0
            self.rate_limit_hits = 0
            self._current_concurrency = (
                max(1, int(target_concurrency)) if target_concurrency is not None else None
            )
            self._consecutive_successes = 0
            self._window_start = time.monotonic()
            self._window_tokens = 0

    def get_effective_concurrency(self, max_concurrency: int) -> int:
        max_c = max(1, int(max_concurrency or 1))
        with self._lock:
            if self._current_concurrency is None or self._current_concurrency > max_c:
                self._current_concurrency = max_c
            return max(1, self._current_concurrency)

    def record_rate_limit(self, wait_seconds: float, max_concurrency: int) -> int:
        max_c = max(1, int(max_concurrency or 1))
        with self._lock:
            if self._current_concurrency is None:
                self._current_concurrency = max_c
            self._current_concurrency = max(1, self._current_concurrency // 2)
            self._consecutive_successes = 0
            self.rate_limit_hits += 1
            self.rate_limit_wait_seconds += max(0.0, float(wait_seconds))
            return self._current_concurrency

    def record_slice_success(self, max_concurrency: int) -> int:
        max_c = max(1, int(max_concurrency or 1))
        with self._lock:
            if self._current_concurrency is None:
                self._current_concurrency = max_c
            self._consecutive_successes += 1
            if self._current_concurrency < max_c and self._consecutive_successes >= 2:
                self._current_concurrency = min(max_c, self._current_concurrency + 1)
                self._consecutive_successes = 0
            return self._current_concurrency

    def record_batch_completion(self, chunks_count: int, elapsed_seconds: float) -> None:
        with self._lock:
            self.chunks_embedded += max(0, int(chunks_count))
            self.embedding_seconds += max(0.0, float(elapsed_seconds))
        try:
            from app.services.indexing.git_progress import progress_tracker
            snap = self.get_telemetry_snapshot()
            progress_tracker.update_embedding_telemetry(snap)
        except Exception:
            pass

    def pace_tokens(
        self,
        tokens: int,
        tpm_limit: int,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> float:
        if tpm_limit <= 0 or tokens <= 0:
            return 0.0
        wait_time = 0.0
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._window_start
            if elapsed >= 60.0:
                self._window_start = now
                self._window_tokens = 0
            if self._window_tokens + tokens > tpm_limit and self._window_tokens > 0:
                wait_time = max(0.0, 60.0 - elapsed)
                self._window_start = now + wait_time
                self._window_tokens = tokens
            else:
                self._window_tokens += tokens
        if wait_time > 0:
            sleep_fn(wait_time)
        return wait_time

    def get_telemetry_snapshot(self, max_concurrency: Optional[int] = None) -> Dict[str, Any]:
        with self._lock:
            chunks = self.chunks_embedded
            secs = round(self.embedding_seconds, 4)
            wait_secs = round(self.rate_limit_wait_seconds, 4)
            hits = self.rate_limit_hits
            cps = round(chunks / self.embedding_seconds, 2) if self.embedding_seconds > 0 else 0.0
            active_c = self._current_concurrency
            if active_c is None and max_concurrency is not None:
                active_c = max(1, int(max_concurrency))
        return {
            "chunks_embedded": chunks,
            "embedding_seconds": secs,
            "embedding_chunks_per_sec": cps,
            "rate_limit_wait_seconds": wait_secs,
            "rate_limit_hits": hits,
            "active_concurrency": active_c or 1,
        }


telemetry_tracker = EmbeddingTelemetryAndPacer()


def execute_api_embeddings_batch(
    client: Any,
    texts: List[str],
    model_name: str,
    batch_size: int = 128,
    max_concurrency: int = 4,
    max_tokens_per_request: int = 100000,
    tpm_limit: int = 0,
    max_retries: int = 5,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> List[List[float]]:
    """Partitions texts into slices and dispatches OpenAI embedding requests in parallel with AIMD 429 handling."""
    if not texts:
        return []
    if client is None:
        raise RuntimeError("API Embedding client not initialized.")

    api_bs = max(1, min(int(batch_size or 128), 256))
    slices = partition_texts_into_slices(
        texts,
        max_items_per_slice=api_bs,
        max_tokens_per_request=max_tokens_per_request,
    )
    if not slices:
        return []

    start_time = time.monotonic()
    effective_concurrency = telemetry_tracker.get_effective_concurrency(max_concurrency)

    def _embed_single_slice(slice_idx: int, batch_slice: List[str]) -> Tuple[int, List[List[float]]]:
        slice_tokens = sum(estimate_token_count(t) for t in batch_slice)
        telemetry_tracker.pace_tokens(slice_tokens, tpm_limit, sleep_fn=sleep_fn)

        attempt = 0
        backoff = 1.0
        while True:
            try:
                response = client.embeddings.create(
                    input=batch_slice,
                    model=model_name,
                )
                data_sorted = sorted(
                    response.data,
                    key=lambda d: getattr(d, "index", 0),
                ) if all(hasattr(d, "index") for d in response.data) else response.data
                vecs = [d.embedding for d in data_sorted]
                telemetry_tracker.record_slice_success(max_concurrency)
                return slice_idx, vecs
            except Exception as exc:
                if _is_rate_limit_error(exc) and attempt < max_retries:
                    attempt += 1
                    wait_secs = _extract_retry_after_seconds(exc, backoff)
                    new_conc = telemetry_tracker.record_rate_limit(wait_secs, max_concurrency)
                    logger.warning(
                        f"Embedding deployment rate limit (HTTP 429) reached on slice {slice_idx + 1}/{len(slices)}. "
                        f"Waiting {wait_secs:.2f}s before retry {attempt}/{max_retries} "
                        f"(AIMD reduced concurrency to {new_conc})."
                    )
                    try:
                        from app.services.indexing.git_progress import progress_tracker
                        progress_tracker.update_embedding_telemetry(
                            telemetry_tracker.get_telemetry_snapshot(max_concurrency)
                        )
                    except Exception:
                        pass
                    sleep_fn(wait_secs)
                    backoff = min(30.0, backoff * 2.0)
                    continue
                raise

    if len(slices) == 1 or effective_concurrency <= 1:
        ordered_embeddings: List[List[float]] = []
        for idx, s in enumerate(slices):
            _, vecs = _embed_single_slice(idx, s)
            ordered_embeddings.extend(vecs)
    else:
        workers = min(len(slices), effective_concurrency)
        results_by_index: Dict[int, List[List[float]]] = {}
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_embed_single_slice, idx, s): idx
                for idx, s in enumerate(slices)
            }
            for future in as_completed(futures):
                s_idx, vecs = future.result()
                results_by_index[s_idx] = vecs
        ordered_embeddings = []
        for idx in range(len(slices)):
            ordered_embeddings.extend(results_by_index[idx])

    elapsed = time.monotonic() - start_time
    telemetry_tracker.record_batch_completion(len(texts), elapsed)
    return ordered_embeddings
