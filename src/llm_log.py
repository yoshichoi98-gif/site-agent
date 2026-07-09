"""
Shared LLM call logger. Keeps llm_log.jsonl open for the process lifetime
so each LLM call doesn't pay an open()/close() round-trip.

One module-level file handle, written to by all three callers
(planner, extractor, location_extractor). Thread-safe enough for asyncio
(single-threaded event loop — writes never interleave).
"""
import json
import os

from src.config import LLM_LOG_PATH

_handle = None


def _get_handle():
    global _handle
    if _handle is None or _handle.closed:
        os.makedirs(os.path.dirname(LLM_LOG_PATH), exist_ok=True)
        _handle = open(LLM_LOG_PATH, "a", buffering=1)  # line-buffered: flushes after each \n
    return _handle


def write(record: dict) -> None:
    """Append one JSON record to llm_log.jsonl. Non-blocking for asyncio."""
    _get_handle().write(json.dumps(record) + "\n")


def close() -> None:
    """Call at process exit if you want an explicit flush."""
    global _handle
    if _handle and not _handle.closed:
        _handle.close()
        _handle = None
