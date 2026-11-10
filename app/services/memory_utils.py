import ctypes
import gc
import logging
import platform

logger = logging.getLogger("contextcortex.memory")


def trim_memory() -> bool:
    """Forces Python garbage collection and invokes glibc malloc_trim on Linux.

    Releases unreturned virtual memory, thread arena scratch buffers, and
    fragmented dirty pages back to the operating system kernel.
    Safely no-ops on non-Linux or non-glibc platforms.
    """
    gc.collect()
    if platform.system() == "Linux":
        try:
            libc = ctypes.CDLL("libc.so.6")
            if hasattr(libc, "malloc_trim"):
                res = libc.malloc_trim(0)
                logger.debug("malloc_trim(0) returned %s", res)
                return bool(res)
        except Exception as e:
            logger.debug("malloc_trim invocation failed or unavailable: %s", e)
    return False
