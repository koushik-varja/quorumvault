import {useEffect, useState} from 'react';
import {RefreshCw} from 'lucide-react';
import {api} from '../api/client';
import {Loading} from '../components/Common';
import type {NodeInfo} from '../types';
import {formatBytes as fmt, statusClass} from '../utils/format';

export function ClusterPage() {
  const [nodes, setNodes] = useState<NodeInfo[] | null>(null);
  const load = () => api<NodeInfo[]>('/cluster').then(setNodes);
  useEffect(() => { void load(); const id = window.setInterval(() => void load(), 5000); return () => window.clearInterval(id); }, []);
  return <><div className="pageHead"><div><div className="eyebrow">LIVE HEARTBEATS</div><h1>Storage cluster</h1></div><button className="iconBtn" onClick={() => void load()}><RefreshCw size={17}/></button></div>{!nodes ? <Loading/> : <div className="nodeGrid">{nodes.map(node => <div className="nodeCard" key={node.id}><div className="nodeTop"><div><span className={`healthDot ${statusClass(node.status)}`}></span><b>{node.id}</b></div><span className={`badge ${statusClass(node.status)}`}>{node.status}</span></div><div className="nodeMetric"><span>Heartbeat</span><b>{node.last_heartbeat ? new Date(node.last_heartbeat).toLocaleTimeString() : '—'}</b></div><div className="nodeMetric"><span>Stored chunks</span><b>{node.chunk_count}</b></div><div className="nodeMetric"><span>Volume used</span><b>{fmt(node.storage_used_bytes)}</b></div><small className="mono">{node.base_url}</small></div>)}</div>}</>;
}
