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


def _extract_filepath_from_embed_text(text: str) -> Optional[str]:
    """Extracts the File: or Document: path header from a formatted embedding string if present."""
    if not text:
        return None
    for line in text.splitlines()[:5]:
        if line.startswith("File: "):
            return line[len("File: "):].strip()
        if line.startswith("Document: "):
            return line[len("Document: "):].strip()
    return None


def _chars_per_token_for_text(text: str) -> int:
    """Returns conservative chars-per-token ratio: 2 for dense/minified code or data, 4 for normal prose/code."""
    if not text:
        return 4
    lines = text.splitlines()
    body = "\n".join(lines[5:]) if len(lines) > 5 and lines[0].startswith("Repo: ") else text
    sample = body[:8192]
    if not sample:
        return 4
    punct_count = sum(1 for ch in sample if not ch.isalnum() and not ch.isspace())
    if (punct_count / len(sample)) >= 0.10 or (max((len(ln) for ln in sample.splitlines()), default=0) > 500 and punct_count > 0):
        return 2
    return 4


def truncate_text_to_token_limit(
    text: str,
    max_tokens_per_input: int = 8000,
    filepath: Optional[str] = None,
) -> str:
    """Truncates a single input text so its estimated token count does not exceed max_tokens_per_input."""
    if not text or not max_tokens_per_input or max_tokens_per_input <= 0:
        return text
    chars_per_tok = _chars_per_token_for_text(text)
    max_chars = int(max_tokens_per_input) * chars_per_tok
    if len(text) <= max_chars:
        return text
    est_tokens = max(1, len(text) // chars_per_tok)
    label = filepath or _extract_filepath_from_embed_text(text) or "<unknown>"
    logger.warning(
        f"Truncating oversized embedding input from '{label}' "
        f"(~{est_tokens} estimated tokens, {len(text)} chars, {chars_per_tok} chars/token) "
        f"to max_tokens_per_input={max_tokens_per_input} ({max_chars} chars)."
    )
    return text[:max_chars]


def partition_texts_into_slices(
    texts: List[str],
    max_items_per_slice: int = 128,
    max_tokens_per_request: int = 100000,
    max_tokens_per_input: Optional[int] = None,
) -> List[List[str]]:
    """Partitions input texts into request slices bounded by both item count and estimated token limit."""
    if not texts:
        return []
    max_items = max(1, int(max_items_per_slice or 128))
    max_tokens = max(1, int(max_tokens_per_request or 100000))

    slices: List[List[str]] = []
    current_slice: List[str] = []
    current_tokens = 0

    for raw_text in texts:
        text = (
            truncate_text_to_token_limit(raw_text, max_tokens_per_input=max_tokens_per_input)
            if max_tokens_per_input and max_tokens_per_input > 0
            else raw_text
        )
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


def _is_bad_request_input_error(exc: Exception) -> bool:
    """Returns True if the exception represents an HTTP 400 invalid input or token limit error."""
    status_code = getattr(exc, "status_code", None)
    if status_code == 400:
        return True
    resp = getattr(exc, "response", None)
    if resp is not None and getattr(resp, "status_code", None) == 400:
        return True
    cls_name = exc.__class__.__name__.lower()
    if "badrequest" in cls_name or "invalidrequest" in cls_name:
        return True
    msg = str(exc).lower()
    return (
        "error code: 400" in msg
        or "status code 400" in msg
        or "http 400" in msg
        or "maximum input length" in msg
        or "maximum context length" in msg
        or "context_length_exceeded" in msg
        or ("invalid 'input" in msg and "tokens" in msg)
    )


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

    def set_target_concurrency(self, target_concurrency: int) -> None:
        with self._lock:
            self._current_concurrency = max(1, int(target_concurrency or 1))
            self._consecutive_successes = 0

    def get_effective_concurrency(self, max_concurrency: int) -> int:
        max_c = max(1, int(max_concurrency or 1))
        with self._lock:
            if self._current_concurrency is None:
                self._current_concurrency = max_c
            return max(1, min(self._current_concurrency, max_c))

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
    max_tokens_per_input: int = 8000,
    tpm_limit: int = 0,
    max_retries: int = 5,
    sleep_fn: Callable[[float], None] = time.sleep,
    filepaths: Optional[List[Optional[str]]] = None,
) -> List[Optional[List[float]]]:
    """Partitions texts into slices and dispatches OpenAI embedding requests in parallel with AIMD 429 handling and HTTP 400 batch bisection."""
    if not texts:
        return []
    if client is None:
        raise RuntimeError("API Embedding client not initialized.")

    api_bs = max(1, min(int(batch_size or 128), 256))
    max_req_tokens = max(1, int(max_tokens_per_request or 100000))
    max_in_tokens = int(max_tokens_per_input) if max_tokens_per_input is not None else 8000

    # Pre-truncate any oversized inputs and pair with optional filepaths before slicing
    slices: List[Tuple[List[str], List[Optional[str]]]] = []
    cur_texts: List[str] = []
    cur_paths: List[Optional[str]] = []
    cur_tokens = 0

    for idx, raw_t in enumerate(texts):
        fp = filepaths[idx] if filepaths and idx < len(filepaths) else None
        t = (
            truncate_text_to_token_limit(raw_t, max_tokens_per_input=max_in_tokens, filepath=fp)
            if max_in_tokens > 0
            else raw_t
        )
        t_tok = estimate_token_count(t)
        if cur_texts and (len(cur_texts) >= api_bs or (cur_tokens + t_tok) > max_req_tokens):
            slices.append((cur_texts, cur_paths))
            cur_texts = [t]
            cur_paths = [fp]
            cur_tokens = t_tok
        else:
            cur_texts.append(t)
            cur_paths.append(fp)
            cur_tokens += t_tok

    if cur_texts:
        slices.append((cur_texts, cur_paths))
    if not slices:
        return []

    start_time = time.monotonic()
    effective_concurrency = telemetry_tracker.get_effective_concurrency(max_concurrency)

    def _embed_items_with_bisect(
        slice_idx: int,
        batch_slice: List[str],
        slice_paths: List[Optional[str]],
    ) -> List[Optional[List[float]]]:
        slice_tokens = sum(estimate_token_count(t) for t in batch_slice)
        telemetry_tracker.pace_tokens(slice_tokens, tpm_limit, sleep_fn=sleep_fn)

        attempt = 0
        trunc_retries = 0
        max_trunc_retries = 3
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
                vecs: List[Optional[List[float]]] = [d.embedding for d in data_sorted]
                telemetry_tracker.record_slice_success(max_concurrency)
                return vecs
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
                if _is_bad_request_input_error(exc):
                    if len(batch_slice) > 1:
                        mid = len(batch_slice) // 2
                        logger.warning(
                            f"Embedding slice {slice_idx + 1}/{len(slices)} ({len(batch_slice)} inputs) failed with HTTP 400 ({exc}). "
                            f"Splitting batch into halves ({mid} and {len(batch_slice) - mid}) to isolate bad input."
                        )
                        left_vecs = _embed_items_with_bisect(slice_idx, batch_slice[:mid], slice_paths[:mid])
                        right_vecs = _embed_items_with_bisect(slice_idx, batch_slice[mid:], slice_paths[mid:])
                        return left_vecs + right_vecs
                    bad_path = (
                        (slice_paths[0] if slice_paths and slice_paths[0] else None)
                        or _extract_filepath_from_embed_text(batch_slice[0])
                        or "<unknown>"
                    )
                    if trunc_retries < max_trunc_retries and len(batch_slice[0]) > 64:
                        trunc_retries += 1
                        new_len = max(32, len(batch_slice[0]) // 2)
                        batch_slice = [batch_slice[0][:new_len]]
                        logger.warning(
                            f"Single embedding input from '{bad_path}' rejected with HTTP 400 ({exc}). "
                            f"Truncating in half to {new_len} chars (retry {trunc_retries}/{max_trunc_retries})."
                        )
                        continue
                    logger.error(
                        f"Skipping bad embedding input from '{bad_path}' (~{estimate_token_count(batch_slice[0])} estimated tokens) "
                        f"after HTTP 400 error: {exc}"
                    )
                    return [None]
                raise

    def _embed_single_slice(
        slice_idx: int,
        batch_slice: List[str],
        slice_paths: List[Optional[str]],
    ) -> Tuple[int, List[Optional[List[float]]]]:
        return slice_idx, _embed_items_with_bisect(slice_idx, batch_slice, slice_paths)

    if len(slices) == 1 or effective_concurrency <= 1:
        ordered_embeddings: List[Optional[List[float]]] = []
        for idx, (s_texts, s_paths) in enumerate(slices):
            _, vecs = _embed_single_slice(idx, s_texts, s_paths)
            ordered_embeddings.extend(vecs)
    else:
        workers = min(len(slices), effective_concurrency)
        results_by_index: Dict[int, List[Optional[List[float]]]] = {}
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_embed_single_slice, idx, s_texts, s_paths): idx
                for idx, (s_texts, s_paths) in enumerate(slices)
            }
            for future in as_completed(futures):
                s_idx, vecs = future.result()
                results_by_index[s_idx] = vecs
        ordered_embeddings = []
        for idx in range(len(slices)):
            ordered_embeddings.extend(results_by_index[idx])

    elapsed = time.monotonic() - start_time
    embedded_count = sum(1 for v in ordered_embeddings if v is not None)
    telemetry_tracker.record_batch_completion(embedded_count, elapsed)
    return ordered_embeddings
