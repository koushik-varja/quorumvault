import {useCallback, useEffect, useState} from 'react';
import {ChevronRight, FileClock, UploadCloud} from 'lucide-react';
import {api} from '../api/client';
import {Empty, Loading} from '../components/Common';
import {useResumableUpload} from '../hooks/useResumableUpload';
import type {FileDetail, FileRow} from '../types';
import {formatBytes as fmt} from '../utils/format';
import {FileDetailPage} from './FileDetailPage';

export function FilesPage() {
  const [files, setFiles] = useState<FileRow[] | null>(null);
  const [selected, setSelected] = useState<FileDetail | null>(null);
  const load = useCallback(async () => setFiles(await api<FileRow[]>('/files')), []);
  useEffect(() => { void load(); }, [load]);
  const uploader = useResumableUpload(() => { void load(); });
  async function detail(id: string) { setSelected(await api<FileDetail>(`/files/${id}`)); }
  async function reloadSelected() { if (selected) setSelected(await api<FileDetail>(`/files/${selected.id}`)); await load(); }
  if (selected) return <FileDetailPage file={selected} onBack={() => setSelected(null)} onReload={reloadSelected}/>;
  return <><div className="pageHead"><div><div className="eyebrow">IMMUTABLE VERSIONS</div><h1>Files</h1></div><label className="uploadBtn"><UploadCloud size={17}/> Select file<input type="file" hidden disabled={uploader.busy} onChange={event => { const file = event.target.files?.[0]; if (file) void uploader.selectFile(file); event.currentTarget.value = ''; }}/></label></div>{uploader.progress && <div className="progressCard"><div><span>{uploader.progress.label}{uploader.progress.resumed ? ' · resumed session' : ''}</span><b>{uploader.progress.percent}%</b></div><div className="progressTrack"><i style={{width: `${uploader.progress.percent}%`}}/></div><div className="progressMeta"><span>{uploader.progress.uploadedChunks} uploaded</span><span>{uploader.progress.remainingChunks} remaining</span><span>{uploader.progress.totalChunks} total</span></div></div>}{uploader.resumeOffer && <div className="resumeCard"><div><b>Resume previous upload</b><small>{uploader.resumeOffer.status.received_chunks.length} chunks already received · {uploader.resumeOffer.status.missing_chunks.length} remaining</small></div><div className="actions"><button className="primary compact" disabled={uploader.busy} onClick={() => void uploader.resume()}>Resume</button><button className="secondary compact" disabled={uploader.busy} onClick={() => void uploader.restart()}>Restart Upload</button></div></div>}{uploader.message && <div className="notice">{uploader.message}</div>}{files === null ? <Loading/> : files.length === 0 ? <Empty text="No files yet. Upload a file; it will be chunked, hashed and replicated across the cluster."/> : <section className="panel"><div className="fileTable">{files.map(file => <button className="fileRow" key={file.id} onClick={() => void detail(file.id)}><div className="fileIcon"><FileClock/></div><div className="fileMain"><b>{file.name}</b><small>v{file.latest_version} · {fmt(file.size_bytes)}</small></div><time>{new Date(file.created_at).toLocaleDateString()}</time><ChevronRight size={17}/></button>)}</div></section>}</>;
}
