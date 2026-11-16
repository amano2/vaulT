"""Logging setup for VaultMCP.

CRITICAL INVARIANT:
In stdio transport mode, stdout carries JSON-RPC protocol frames exclusively.
All log messages must stream strictly to stderr.
"""

import logging
import sys


def setup_logging(level: int = logging.INFO, to_stderr_only: bool = True) -> logging.Logger:
    """Configures the root and 'vaultmcp' logger.

    Always binds a StreamHandler targeting sys.stderr.
    """
    logger = logging.getLogger("vaultmcp")
    logger.setLevel(level)

    # Avoid duplicate handlers if called multiple times
    if not any(isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) == sys.stderr for h in logger.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(level)
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    # Prevent propagation to root logger if root has stdout handlers
    logger.propagate = False
    return logger
