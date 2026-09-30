import {useEffect, useState} from 'react';
import {api} from '../api/client';
import {Empty, Loading} from '../components/Common';
import type {AuditEventInfo} from '../types';

export function AuditPage() {
  const [rows, setRows] = useState<AuditEventInfo[] | null>(null);
  useEffect(() => { void api<AuditEventInfo[]>('/audit').then(setRows); }, []);
  return <><div className="pageHead"><div><div className="eyebrow">ADMIN AUDIT TRAIL</div><h1>System events</h1></div></div>{!rows ? <Loading/> : <section className="panel">{rows.length === 0 ? <Empty text="No audit events yet."/> : rows.map(event => <div className="auditRow" key={event.id}><span className="dot"></span><div><b>{event.event_type.replaceAll('_', ' ')}</b><small>{event.message}</small></div><time>{new Date(event.created_at).toLocaleString()}</time></div>)}</section>}</>;
}
