"""Shared helpers and limits for VaultMCP tools."""

DEFAULT_MAX_BYTES = 20480  # 20 KB limit


def truncate_output(text: str, max_bytes: int = DEFAULT_MAX_BYTES) -> tuple[str, bool]:
    """Truncates output string if its UTF-8 byte length exceeds max_bytes."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text, False

    # Truncate at valid character boundary
    truncated_bytes = encoded[: max_bytes - 60]
    # Decode ignoring broken trailing characters
    decoded = truncated_bytes.decode("utf-8", errors="ignore")
    notice = "\n\n[... Truncated: output exceeded 20 KB maximum size limit ...]"
    return decoded + notice, True
