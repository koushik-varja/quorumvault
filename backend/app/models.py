import enum
import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, BigInteger, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base


def uuid_str() -> str:
    return str(uuid.uuid4())

class UserRole(str, enum.Enum):
    USER = 'USER'
    ADMIN = 'ADMIN'

class NodeStatus(str, enum.Enum):
    HEALTHY = 'HEALTHY'
    UNHEALTHY = 'UNHEALTHY'
    SIMULATED_DOWN = 'SIMULATED_DOWN'

class ReplicaState(str, enum.Enum):
    HEALTHY = 'HEALTHY'
    DEGRADED = 'DEGRADED'
    CORRUPTED = 'CORRUPTED'
    UNAVAILABLE = 'UNAVAILABLE'
    REPAIRING = 'REPAIRING'

class UploadStatus(str, enum.Enum):
    ACTIVE = 'ACTIVE'
    FINALIZED = 'FINALIZED'
    ABORTED = 'ABORTED'

class RepairState(str, enum.Enum):
    PENDING = 'PENDING'
    RUNNING = 'RUNNING'
    SUCCEEDED = 'SUCCEEDED'
    FAILED = 'FAILED'

class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.USER)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class LogicalFile(Base):
    __tablename__ = 'logical_files'
    __table_args__ = (UniqueConstraint('owner_id', 'name', name='uq_owner_file_name'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    owner = relationship('User')
    versions = relationship('FileVersion', back_populates='logical_file', cascade='all, delete-orphan')

class FileVersion(Base):
    __tablename__ = 'file_versions'
    __table_args__ = (UniqueConstraint('logical_file_id', 'version_number', name='uq_file_version'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    logical_file_id: Mapped[str] = mapped_column(ForeignKey('logical_files.id', ondelete='CASCADE'), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    file_sha256: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    logical_file = relationship('LogicalFile', back_populates='versions')
    chunks = relationship('FileVersionChunk', back_populates='file_version', cascade='all, delete-orphan', order_by='FileVersionChunk.chunk_index')

class Chunk(Base):
    __tablename__ = 'chunks'
    hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    replicas = relationship('ChunkReplica', back_populates='chunk', cascade='all, delete-orphan')

class FileVersionChunk(Base):
    __tablename__ = 'file_version_chunks'
    __table_args__ = (UniqueConstraint('file_version_id', 'chunk_index', name='uq_version_chunk_index'), Index('ix_fvc_chunk_hash', 'chunk_hash'))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    file_version_id: Mapped[str] = mapped_column(ForeignKey('file_versions.id', ondelete='CASCADE'), index=True)
    chunk_hash: Mapped[str] = mapped_column(ForeignKey('chunks.hash', ondelete='RESTRICT'))
    chunk_index: Mapped[int] = mapped_column(Integer)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    file_version = relationship('FileVersion', back_populates='chunks')
    chunk = relationship('Chunk')

class StorageNode(Base):
    __tablename__ = 'storage_nodes'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    base_url: Mapped[str] = mapped_column(String(255), unique=True)
    status: Mapped[NodeStatus] = mapped_column(Enum(NodeStatus), default=NodeStatus.UNHEALTHY, index=True)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    storage_used_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    chunk_count: Mapped[int] = mapped_column(BigInteger, default=0)
    simulated_down: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class ChunkReplica(Base):
    __tablename__ = 'chunk_replicas'
    __table_args__ = (UniqueConstraint('chunk_hash', 'node_id', name='uq_chunk_node'), Index('ix_replica_state', 'state'))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    chunk_hash: Mapped[str] = mapped_column(ForeignKey('chunks.hash', ondelete='CASCADE'), index=True)
    node_id: Mapped[str] = mapped_column(ForeignKey('storage_nodes.id', ondelete='CASCADE'), index=True)
    state: Mapped[ReplicaState] = mapped_column(Enum(ReplicaState), default=ReplicaState.HEALTHY)
    checksum_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    chunk = relationship('Chunk', back_populates='replicas')
    node = relationship('StorageNode')

class UploadSession(Base):
    __tablename__ = 'upload_sessions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expected_size: Mapped[int] = mapped_column(BigInteger)
    chunk_size: Mapped[int] = mapped_column(Integer)
    status: Mapped[UploadStatus] = mapped_column(Enum(UploadStatus), default=UploadStatus.ACTIVE, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class UploadSessionChunk(Base):
    __tablename__ = 'upload_session_chunks'
    __table_args__ = (UniqueConstraint('session_id', 'chunk_index', name='uq_session_chunk_index'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    session_id: Mapped[str] = mapped_column(ForeignKey('upload_sessions.id', ondelete='CASCADE'), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    chunk_hash: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    received: Mapped[bool] = mapped_column(Boolean, default=False)

class Snapshot(Base):
    __tablename__ = 'snapshots'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    entries = relationship('SnapshotEntry', back_populates='snapshot', cascade='all, delete-orphan')

class SnapshotEntry(Base):
    __tablename__ = 'snapshot_entries'
    __table_args__ = (UniqueConstraint('snapshot_id', 'logical_file_id', name='uq_snapshot_file'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey('snapshots.id', ondelete='CASCADE'), index=True)
    logical_file_id: Mapped[str] = mapped_column(ForeignKey('logical_files.id', ondelete='CASCADE'))
    file_version_id: Mapped[str] = mapped_column(ForeignKey('file_versions.id', ondelete='RESTRICT'))
    snapshot = relationship('Snapshot', back_populates='entries')

class RepairJob(Base):
    __tablename__ = 'repair_jobs'
    __table_args__ = (Index('ix_repair_chunk_state', 'chunk_hash', 'state'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    chunk_hash: Mapped[str] = mapped_column(ForeignKey('chunks.hash', ondelete='CASCADE'), index=True)
    source_node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    state: Mapped[RepairState] = mapped_column(Enum(RepairState), default=RepairState.PENDING, index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class AuditEvent(Base):
    __tablename__ = 'audit_events'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    message: Mapped[str] = mapped_column(Text)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
