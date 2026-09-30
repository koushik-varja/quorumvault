from sqlalchemy import func, select
from sqlalchemy.orm import Session
from fastapi import HTTPException

from ..models import FileVersion, LogicalFile, Snapshot, SnapshotEntry
from .audit import record
from .versioning import restore_file_version


def create_snapshot(db: Session, owner_id: str, name: str) -> Snapshot:
    snapshot = Snapshot(owner_id=owner_id, name=name.strip())
    db.add(snapshot)
    db.flush()
    files = db.scalars(select(LogicalFile).where(LogicalFile.owner_id == owner_id)).all()
    captured = 0
    for logical in files:
        latest_number = db.scalar(
            select(func.max(FileVersion.version_number)).where(FileVersion.logical_file_id == logical.id)
        )
        if latest_number is None:
            continue
        version = db.scalar(
            select(FileVersion).where(
                FileVersion.logical_file_id == logical.id,
                FileVersion.version_number == latest_number,
            )
        )
        if version is not None:
            db.add(
                SnapshotEntry(
                    snapshot_id=snapshot.id,
                    logical_file_id=logical.id,
                    file_version_id=version.id,
                )
            )
            captured += 1
    record(db, 'SNAPSHOT_CREATED', f'Snapshot {snapshot.name} captured {captured} logical files', owner_id)
    db.commit()
    return snapshot


def restore_snapshot(db: Session, snapshot: Snapshot, owner_id: str) -> list[FileVersion]:
    if snapshot.owner_id != owner_id:
        raise HTTPException(status_code=404, detail='Snapshot not found')
    restored: list[FileVersion] = []
    # Each clone is committed by restore_file_version so its version-number lock spans
    # allocation through persistence. Snapshot entries themselves remain immutable.
    for entry in list(snapshot.entries):
        source = db.get(FileVersion, entry.file_version_id)
        if source is None:
            continue
        restored.append(restore_file_version(db, source, owner_id))
    record(db, 'SNAPSHOT_RESTORED', f'Snapshot {snapshot.name} restored as new versions', owner_id)
    db.commit()
    return restored
