import {useCallback, useState} from 'react';
import {api} from '../api/client';
import type {
  ChunkDescriptor,
  FinalizeUploadResponse,
  UploadSessionCreateResponse,
  UploadSessionStatusResponse,
} from '../types';
import {
  findPersistedUpload,
  fingerprintSource,
  removePersistedUpload,
  savePersistedUpload,
  type PersistedUploadSession,
} from '../utils/uploadSession';

export const DEFAULT_CHUNK_SIZE = 4 * 1024 * 1024;

interface PreparedChunk extends ChunkDescriptor {
  blob: Blob;
}

interface PreparedFile {
  file: File;
  chunks: PreparedChunk[];
  manifestHash: string;
}

export interface UploadProgress {
  percent: number;
  label: string;
  uploadedChunks: number;
  remainingChunks: number;
  totalChunks: number;
  resumed: boolean;
}

export interface ResumeOffer {
  session: PersistedUploadSession;
  status: UploadSessionStatusResponse;
}

export interface UploadResult extends FinalizeUploadResponse {
  missingTransferred: number;
  totalChunks: number;
  resumed: boolean;
}

async function sha256(blob: Blob): Promise<string> {
  const bytes = await blob.arrayBuffer();
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, '0')).join('');
}

async function hashText(value: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

async function prepareFile(file: File, onHash: (complete: number, total: number) => void): Promise<PreparedFile> {
  const chunks: PreparedChunk[] = [];
  const expectedChunks = Math.max(1, Math.ceil(file.size / DEFAULT_CHUNK_SIZE));
  for (let offset = 0, index = 0; offset < file.size || (file.size === 0 && index === 0); offset += DEFAULT_CHUNK_SIZE, index += 1) {
    const blob = file.slice(offset, Math.min(offset + DEFAULT_CHUNK_SIZE, file.size));
    const hash = await sha256(blob);
    chunks.push({index, hash, size: blob.size, blob});
    onHash(index + 1, expectedChunks);
    if (file.size === 0) break;
  }
  const manifestHash = await hashText(
    fingerprintSource(file.name, file.size, file.lastModified, chunks.map((chunk) => chunk.hash)),
  );
  return {file, chunks, manifestHash};
}

export function useResumableUpload(onComplete: (result: UploadResult) => void) {
  const [prepared, setPrepared] = useState<PreparedFile | null>(null);
  const [resumeOffer, setResumeOffer] = useState<ResumeOffer | null>(null);
  const [progress, setProgress] = useState<UploadProgress | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  const transfer = useCallback(async (
    fileState: PreparedFile,
    sessionId: string,
    missingChunks: number[],
    resumed: boolean,
  ) => {
    setBusy(true);
    setResumeOffer(null);
    const total = fileState.chunks.length;
    const alreadyUploaded = total - missingChunks.length;
    try {
      for (let position = 0; position < missingChunks.length; position += 1) {
        const index = missingChunks[position];
        const chunk = fileState.chunks[index];
        await api<Record<string, unknown>>(`/uploads/sessions/${sessionId}/chunks/${index}`, {
          method: 'PUT',
          body: chunk.blob,
          headers: {'Content-Type': 'application/octet-stream'},
        });
        const uploaded = alreadyUploaded + position + 1;
        setProgress({
          percent: Math.round((uploaded / total) * 90),
          label: resumed ? 'Resuming missing chunks' : 'Replicating missing chunks',
          uploadedChunks: uploaded,
          remainingChunks: total - uploaded,
          totalChunks: total,
          resumed,
        });
      }
      const result = await api<FinalizeUploadResponse>(`/uploads/sessions/${sessionId}/finalize`, {method: 'POST'});
      removePersistedUpload(sessionId);
      const complete: UploadResult = {
        ...result,
        missingTransferred: missingChunks.length,
        totalChunks: total,
        resumed,
      };
      setProgress({
        percent: 100,
        label: resumed ? 'Resumed upload finalized' : 'Upload finalized',
        uploadedChunks: total,
        remainingChunks: 0,
        totalChunks: total,
        resumed,
      });
      setMessage(
        `${resumed ? 'Resumed and stored' : 'Stored'} ${total} chunks; transferred ${missingChunks.length}.`,
      );
      onComplete(complete);
    } catch (error) {
      setMessage(`${(error as Error).message}. The session metadata was kept so you can retry or resume.`);
      throw error;
    } finally {
      setBusy(false);
    }
  }, [onComplete]);

  const startNew = useCallback(async (fileState: PreparedFile) => {
    setBusy(true);
    setMessage('');
    try {
      const session = await api<UploadSessionCreateResponse>('/uploads/sessions', {
        method: 'POST',
        body: JSON.stringify({
          file_name: fileState.file.name,
          expected_size: fileState.file.size,
          content_type: fileState.file.type || 'application/octet-stream',
          chunks: fileState.chunks.map(({index, hash, size}) => ({index, hash, size})),
        }),
      });
      savePersistedUpload({
        sessionId: session.session_id,
        filename: fileState.file.name,
        fileSize: fileState.file.size,
        lastModified: fileState.file.lastModified,
        chunkSize: session.chunk_size,
        manifestHash: fileState.manifestHash,
        createdAt: session.created_at || new Date().toISOString(),
      });
      await transfer(fileState, session.session_id, session.missing_chunks, false);
    } finally {
      setBusy(false);
    }
  }, [transfer]);

  const selectFile = useCallback(async (file: File) => {
    setBusy(true);
    setMessage('');
    setResumeOffer(null);
    setProgress({percent: 0, label: 'Hashing chunks', uploadedChunks: 0, remainingChunks: 0, totalChunks: 0, resumed: false});
    try {
      const fileState = await prepareFile(file, (complete, total) => {
        setProgress({
          percent: Math.round((complete / total) * 25),
          label: 'Hashing chunks',
          uploadedChunks: 0,
          remainingChunks: total,
          totalChunks: total,
          resumed: false,
        });
      });
      setPrepared(fileState);
      const persisted = findPersistedUpload(fileState.manifestHash);
      if (persisted) {
        try {
          const status = await api<UploadSessionStatusResponse>(`/uploads/sessions/${persisted.sessionId}`);
          const valid =
            status.status === 'ACTIVE' &&
            status.file_name === file.name &&
            status.expected_size === file.size &&
            status.chunk_size === persisted.chunkSize;
          if (valid) {
            setResumeOffer({session: persisted, status});
            setProgress({
              percent: Math.round((status.received_chunks.length / fileState.chunks.length) * 90),
              label: 'Previous unfinished upload found',
              uploadedChunks: status.received_chunks.length,
              remainingChunks: status.missing_chunks.length,
              totalChunks: fileState.chunks.length,
              resumed: true,
            });
            setMessage('Resume previous upload or restart it from a fresh session.');
            return;
          }
          removePersistedUpload(persisted.sessionId);
        } catch {
          removePersistedUpload(persisted.sessionId);
        }
      }
      await startNew(fileState);
    } finally {
      setBusy(false);
    }
  }, [startNew]);

  const resume = useCallback(async () => {
    if (!prepared || !resumeOffer) return;
    const status = await api<UploadSessionStatusResponse>(`/uploads/sessions/${resumeOffer.session.sessionId}`);
    if (status.status !== 'ACTIVE') {
      removePersistedUpload(resumeOffer.session.sessionId);
      setResumeOffer(null);
      setMessage('The previous session is no longer active. Start a new upload.');
      return;
    }
    await transfer(prepared, status.session_id, status.missing_chunks, true);
  }, [prepared, resumeOffer, transfer]);

  const restart = useCallback(async () => {
    if (!prepared) return;
    if (resumeOffer) {
      try {
        await api<{session_id: string; status: string}>(`/uploads/sessions/${resumeOffer.session.sessionId}`, {
          method: 'DELETE',
        });
      } catch {
        // A missing/expired backend session is already safe to replace locally.
      }
      removePersistedUpload(resumeOffer.session.sessionId);
      setResumeOffer(null);
    }
    await startNew(prepared);
  }, [prepared, resumeOffer, startNew]);

  return {selectFile, resume, restart, resumeOffer, progress, message, busy};
}
