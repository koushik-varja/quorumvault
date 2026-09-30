import {useEffect, useState} from 'react';
import {Activity, Archive, Copy, Database, HardDrive, ShieldCheck} from 'lucide-react';
import {api} from '../api/client';
import {Empty, Loading, Stat} from '../components/Common';
import type {Dashboard} from '../types';
import {formatBytes as fmt} from '../utils/format';

export function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  useEffect(() => { void api<Dashboard>('/dashboard').then(setData); }, []);
  if (!data) return <Loading/>;
  return <><div className="pageHead"><div><div className="eyebrow">SYSTEM OVERVIEW</div><h1>Storage health at a glance</h1></div><span className={`badge ${data.healthy_nodes === data.node_count ? 'good' : 'warn'}`}>{data.healthy_nodes}/{data.node_count} nodes healthy</span></div><div className="stats"><Stat label="Logical storage" value={fmt(data.logical_storage_bytes)} icon={<Database/>}/><Stat label="Physical storage" value={fmt(data.physical_storage_bytes)} detail={`${fmt(data.unique_chunk_bytes)} unique before replicas`} icon={<HardDrive/>}/><Stat label="Dedup savings" value={fmt(data.dedup_savings_bytes)} detail="latest versions" icon={<Copy/>}/><Stat label="Files / snapshots" value={`${data.file_count} / ${data.snapshot_count}`} icon={<Archive/>}/></div><div className="grid2"><section className="panel"><div className="panelTitle"><span>Reliability</span><ShieldCheck size={18}/></div><div className="reliability"><div><strong>{data.degraded_chunks}</strong><span>degraded chunks</span></div><div><strong>{data.active_repairs}</strong><span>active repairs</span></div><div><strong>{data.metrics.integrity_errors || '0'}</strong><span>integrity errors</span></div></div></section><section className="panel"><div className="panelTitle"><span>Recent activity</span><Activity size={18}/></div>{data.activity.length ? data.activity.map((item, index) => <div className="activityRow" key={`${item.created_at}-${index}`}><span className="dot"></span><div><b>{item.type.replaceAll('_', ' ')}</b><small>{item.message}</small></div><time>{new Date(item.created_at).toLocaleTimeString()}</time></div>) : <Empty text="No activity yet. Upload a file to begin."/>}</section></div></>;
}
