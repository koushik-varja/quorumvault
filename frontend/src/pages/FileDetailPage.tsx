import {Download, RotateCcw} from 'lucide-react';
import {api, downloadVersion} from '../api/client';
import type {FileDetail, VersionRestoreResponse} from '../types';
import {formatBytes as fmt, statusClass} from '../utils/format';

export function FileDetailPage({file, onBack, onReload}: {file: FileDetail; onBack: () => void; onReload: () => Promise<void>}) {
  const latest = Math.max(...file.versions.map(v => v.version_number));
  async function restore(version: number) {
    if (!confirm(`Restore version ${version} as a new version? Existing history will remain unchanged.`)) return;
    await api<VersionRestoreResponse>(`/files/${file.id}/versions/${version}/restore`, {method: 'POST'});
    await onReload();
  }
  return <><button className="back" onClick={onBack}>← Files</button><div className="pageHead"><div><div className="eyebrow">FILE DETAIL</div><h1>{file.name}</h1></div><span className="badge">{file.versions.length} versions</span></div>{file.versions.map(version => <section className="panel version" key={version.id}><div className="panelTitle"><span>Version {version.version_number} · {fmt(version.size_bytes)}</span><div className="actions"><button className="iconBtn" title="Download verified reconstruction" onClick={() => void downloadVersion(file.id, version.version_number, file.name)}><Download size={17}/></button>{version.version_number < latest && <button className="secondary compact" onClick={() => void restore(version.version_number)}><RotateCcw size={15}/> Restore this version</button>}</div></div><div className="mono smallHash">SHA-256 {version.file_sha256}</div><div className="chunkTable"><div className="thead"><span>#</span><span>Chunk hash</span><span>Replicas</span></div>{version.chunks.map(chunk => <div className="trow" key={chunk.index}><span>{chunk.index}</span><span className="mono">{chunk.hash.slice(0, 18)}…</span><span className="replicas">{chunk.replicas.map(replica => <span title={replica.state} className={`nodePill ${statusClass(replica.state)}`} key={replica.node_id}>{replica.node_id}</span>)}</span></div>)}</div></section>)}</>;
}
