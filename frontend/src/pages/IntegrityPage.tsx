import {useEffect, useState} from 'react';
import {ShieldCheck, Wrench} from 'lucide-react';
import {api} from '../api/client';
import {Empty, Loading} from '../components/Common';
import type {IntegrityState} from '../types';
import {statusClass} from '../utils/format';

export function IntegrityPage() {
  const [data, setData] = useState<IntegrityState | null>(null); const [busy, setBusy] = useState('');
  const load = () => api<IntegrityState>('/integrity').then(setData);
  useEffect(() => { void load(); }, []);
  async function run(kind: 'integrity' | 'repair') { setBusy(kind); try { await api(kind === 'integrity' ? '/integrity/scan' : '/repairs/scan', {method: 'POST'}); await load(); } finally { setBusy(''); } }
  return <><div className="pageHead"><div><div className="eyebrow">CHECKSUM & SELF-HEALING</div><h1>Integrity & repair</h1></div><div className="actions"><button className="secondary" disabled={!!busy} onClick={() => void run('integrity')}><ShieldCheck size={16}/> Scan integrity</button><button className="primary compact" disabled={!!busy} onClick={() => void run('repair')}><Wrench size={16}/> Repair scan</button></div></div>{!data ? <Loading/> : <><section className="panel"><div className="panelTitle">Data health · latest objects</div><div className="stateStrip">{Object.entries(data.data_health.objects).map(([key, value]) => <div key={key}><span className={`healthDot ${statusClass(key)}`}></span><b>{value}</b><small>{key}</small></div>)}</div></section><div className="stateStrip">{Object.entries(data.replica_states).map(([key, value]) => <div key={key}><span className={`healthDot ${statusClass(key)}`}></span><b>{value}</b><small>{key}</small></div>)}</div><section className="panel"><div className="panelTitle">Recent repair jobs</div>{data.repairs.length === 0 ? <Empty text="No repair jobs recorded."/> : data.repairs.map(job => <div className="repairRow" key={job.id}><span className={`badge ${statusClass(job.state)}`}>{job.state}</span><span className="mono">{job.chunk_hash.slice(0, 14)}…</span><span>{job.source || '—'} → {job.target || '—'}</span><span>{job.duration_ms == null ? '—' : `${job.duration_ms} ms`}</span></div>)}</section></>}</>;
}
