import {describe, expect, it} from 'vitest';
import {findPersistedUpload, readPersistedUploads, removePersistedUpload, savePersistedUpload, type StorageLike} from './utils/uploadSession';

class MemoryStorage implements StorageLike {
  private values = new Map<string, string>();
  getItem(key: string) { return this.values.get(key) ?? null; }
  setItem(key: string, value: string) { this.values.set(key, value); }
  removeItem(key: string) { this.values.delete(key); }
}

describe('resumable upload metadata', () => {
  it('persists only session metadata and finds the matching manifest', () => {
    const storage = new MemoryStorage();
    const session = {sessionId: 's1', filename: 'large.bin', fileSize: 100, lastModified: 123, chunkSize: 4194304, manifestHash: 'manifest-a', createdAt: '2026-09-08T00:00:00Z'};
    savePersistedUpload(session, storage);
    expect(findPersistedUpload('manifest-a', storage)).toEqual(session);
    const raw = storage.getItem('qv_active_uploads_v1') ?? '';
    expect(raw).not.toContain('Blob');
    expect(readPersistedUploads(storage)).toHaveLength(1);
  });

  it('removes finalized or stale session metadata', () => {
    const storage = new MemoryStorage();
    savePersistedUpload({sessionId: 's1', filename: 'a', fileSize: 1, lastModified: 1, chunkSize: 4, manifestHash: 'x', createdAt: '2026-09-08T00:00:00Z'}, storage);
    removePersistedUpload('s1', storage);
    expect(readPersistedUploads(storage)).toEqual([]);
  });
});
