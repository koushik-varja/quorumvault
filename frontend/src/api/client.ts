const BASE = import.meta.env.VITE_API_BASE || '/api';

export const token = (): string | null => localStorage.getItem('qv_token');

export const setToken = (value: string | null): void => {
  if (value) localStorage.setItem('qv_token', value);
  else localStorage.removeItem('qv_token');
};

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers || {});
  const authToken = token();
  if (authToken) headers.set('Authorization', `Bearer ${authToken}`);
  if (
    options.body &&
    !(options.body instanceof Blob) &&
    !(options.body instanceof ArrayBuffer) &&
    !headers.has('Content-Type')
  ) {
    headers.set('Content-Type', 'application/json');
  }
  const response = await fetch(`${BASE}${path}`, {...options, headers});
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as {detail?: unknown};
      message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
    } catch {
      // Keep the status-based message when the response is not JSON.
    }
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function downloadVersion(fileId: string, version: number, filename: string): Promise<void> {
  const headers = new Headers();
  const authToken = token();
  if (authToken) headers.set('Authorization', `Bearer ${authToken}`);
  const response = await fetch(`${BASE}/files/${fileId}/versions/${version}/download`, {headers});
  if (!response.ok) throw new Error(`Download failed (${response.status})`);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
