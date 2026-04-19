"""Reliquary shared storage backends.

One canonical implementation per storage provider. Both
``reliquary-inference`` (verdict pipeline) and ``reliquary`` (delta
checkpoints) consume these by duck-typing against their own local
``StorageBackend`` / ``CheckpointStorageBackend`` Protocols — the
surface is identical: ``put / get / list / delete``.
"""

from reliquary_protocol.storage.r2 import (
    R2BackendError,
    R2ConfigError,
    R2ObjectBackend,
    R2RequestError,
)

__all__ = [
    "R2BackendError",
    "R2ConfigError",
    "R2ObjectBackend",
    "R2RequestError",
]
