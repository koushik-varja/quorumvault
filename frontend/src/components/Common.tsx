import {RefreshCw} from 'lucide-react';
import type {ReactNode} from 'react';

export function Stat({label, value, detail, icon}: {label: string; value: string; detail?: string; icon: ReactNode}) {
  return <div className="stat"><div className="statIcon">{icon}</div><div><span>{label}</span><strong>{value}</strong>{detail && <small>{detail}</small>}</div></div>;
}

export function Loading() {
  return <div className="loading"><RefreshCw className="spin" size={18}/> Loading live state…</div>;
}

export function Empty({text}: {text: string}) {
  return <div className="empty">{text}</div>;
}
