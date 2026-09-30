export const ACTIVE_UPLOADS_KEY = 'qv_active_uploads_v1';

export interface PersistedUploadSession {
  sessionId: string;
  filename: string;
  fileSize: number;
  lastModified: number;
  chunkSize: number;
  manifestHash: string;
  createdAt: string;
}

export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

const defaultStorage = (): StorageLike => localStorage;

export function readPersistedUploads(storage: StorageLike = defaultStorage()): PersistedUploadSession[] {
  const raw = storage.getItem(ACTIVE_UPLOADS_KEY);
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((row): row is PersistedUploadSession => {
      if (typeof row !== 'object' || row === null) return false;
      const item = row as Record<string, unknown>;
      return (
        typeof item.sessionId === 'string' &&
        typeof item.filename === 'string' &&
        typeof item.fileSize === 'number' &&
        typeof item.lastModified === 'number' &&
        typeof item.chunkSize === 'number' &&
        typeof item.manifestHash === 'string' &&
        typeof item.createdAt === 'string'
      );
    });
  } catch {
    return [];
  }
}

export function savePersistedUpload(
  session: PersistedUploadSession,
  storage: StorageLike = defaultStorage(),
): void {
  const rows = readPersistedUploads(storage).filter((row) => row.sessionId !== session.sessionId);
  rows.push(session);
  storage.setItem(ACTIVE_UPLOADS_KEY, JSON.stringify(rows.slice(-12)));
}

export function removePersistedUpload(sessionId: string, storage: StorageLike = defaultStorage()): void {
  const rows = readPersistedUploads(storage).filter((row) => row.sessionId !== sessionId);
  if (rows.length) storage.setItem(ACTIVE_UPLOADS_KEY, JSON.stringify(rows));
  else storage.removeItem(ACTIVE_UPLOADS_KEY);
}

export function findPersistedUpload(
  manifestHash: string,
  storage: StorageLike = defaultStorage(),
): PersistedUploadSession | null {
  return readPersistedUploads(storage)
    .filter((row) => row.manifestHash === manifestHash)
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt))[0] ?? null;
}

export function fingerprintSource(
  filename: string,
  fileSize: number,
  lastModified: number,
  chunkHashes: readonly string[],
): string {
  return JSON.stringify({filename, fileSize, lastModified, chunkHashes});
}
