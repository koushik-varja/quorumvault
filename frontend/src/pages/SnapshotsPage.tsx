import {useEffect, useState} from 'react';
import {Archive} from 'lucide-react';
import {api} from '../api/client';
import {Empty, Loading} from '../components/Common';
import type {SnapshotInfo} from '../types';

export function SnapshotsPage() {
  const [rows, setRows] = useState<SnapshotInfo[] | null>(null); const [name, setName] = useState('Before Final Submission');
  const load = () => api<SnapshotInfo[]>('/snapshots').then(setRows);
  useEffect(() => { void load(); }, []);
  async function create() { await api('/snapshots', {method: 'POST', body: JSON.stringify({name})}); await load(); }
  async function restore(id: string) { if (confirm('Restore this snapshot as new file versions? Historical versions will remain intact.')) { await api(`/snapshots/${id}/restore`, {method: 'POST'}); alert('Snapshot restored as new versions.'); } }
  return <><div className="pageHead"><div><div className="eyebrow">POINT-IN-TIME STATE</div><h1>Snapshots</h1></div></div><section className="panel inlineForm"><input value={name} onChange={e => setName(e.target.value)} placeholder="Snapshot name"/><button className="primary compact" onClick={() => void create()}>Create snapshot</button></section>{rows === null ? <Loading/> : rows.length === 0 ? <Empty text="No snapshots yet."/> : <div className="cards">{rows.map(snapshot => <div className="snapshotCard" key={snapshot.id}><Archive/><div><b>{snapshot.name}</b><small>{snapshot.entry_count} files · {new Date(snapshot.created_at).toLocaleString()}</small></div><button className="secondary" onClick={() => void restore(snapshot.id)}>Restore</button></div>)}</div>}</>;
}
