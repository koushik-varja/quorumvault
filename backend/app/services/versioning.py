from __future__ import annotations

from contextlib import contextmanager
import threading
from collections.abc import Iterator, Sequence

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..models import FileVersion, FileVersionChunk, LogicalFile
from .audit import record

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _process_lock(key: str) -> threading.RLock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


@contextmanager
def transaction_key_lock(db: Session, key: str) -> Iterator[None]:
    """Serialize a metadata key.

    PostgreSQL uses a transaction-scoped advisory lock, so this remains safe across
    multiple control-plane workers. SQLite uses a process lock for deterministic tests.
    """
    if db.bind is not None and db.bind.dialect.name == 'postgresql':
        db.execute(text('SELECT pg_advisory_xact_lock(hashtext(:key))'), {'key': key})
        yield
        return
    lock = _process_lock(key)
    with lock:
        yield


def get_or_create_logical_file(
    db: Session,
    owner_id: str,
    name: str,
    content_type: str | None,
) -> LogicalFile:
    logical = db.scalar(select(LogicalFile).where(LogicalFile.owner_id == owner_id, LogicalFile.name == name))
    if logical is None:
        logical = LogicalFile(owner_id=owner_id, name=name, content_type=content_type)
        db.add(logical)
        db.flush()
    elif content_type:
        logical.content_type = content_type
    return logical


def create_version(
    db: Session,
    *,
    logical: LogicalFile,
    size_bytes: int,
    file_sha256: str,
    chunks: Sequence[tuple[str, int, int]],
) -> FileVersion:
    latest = db.scalar(
        select(func.max(FileVersion.version_number)).where(FileVersion.logical_file_id == logical.id)
    ) or 0
    version = FileVersion(
        logical_file_id=logical.id,
        version_number=latest + 1,
        size_bytes=size_bytes,
        file_sha256=file_sha256,
    )
    db.add(version)
    db.flush()
    for chunk_hash, chunk_index, chunk_size in chunks:
        db.add(
            FileVersionChunk(
                file_version_id=version.id,
                chunk_hash=chunk_hash,
                chunk_index=chunk_index,
                size_bytes=chunk_size,
            )
        )
    db.flush()
    return version


def restore_file_version(db: Session, source: FileVersion, owner_id: str) -> FileVersion:
    logical = db.get(LogicalFile, source.logical_file_id)
    if logical is None or logical.owner_id != owner_id:
        raise LookupError('file version not found')
    key = f'file:{owner_id}:{logical.name}'
    with transaction_key_lock(db, key):
        # Re-query while holding the database lock in PostgreSQL.
        if db.bind is not None and db.bind.dialect.name == 'postgresql':
            logical = db.scalar(select(LogicalFile).where(LogicalFile.id == logical.id).with_for_update())
            assert logical is not None
        chunk_rows = [(item.chunk_hash, item.chunk_index, item.size_bytes) for item in source.chunks]
        clone = create_version(
            db,
            logical=logical,
            size_bytes=source.size_bytes,
            file_sha256=source.file_sha256,
            chunks=chunk_rows,
        )
        record(
            db,
            'FILE_VERSION_RESTORED',
            f'{logical.name} v{source.version_number} restored as v{clone.version_number}',
            owner_id,
        )
        db.commit()
        return clone
