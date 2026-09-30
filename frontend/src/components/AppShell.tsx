import {Activity, Archive, Blocks, FileClock, Files as FilesIcon, FlaskConical, HardDrive, LogOut, ShieldCheck} from 'lucide-react';
import type {ReactNode} from 'react';
import {setToken} from '../api/client';
import type {CurrentUser} from '../types';
import {canAccessPage, type Page} from '../utils/navigation';

const NAV: Array<[Page, string, ReactNode]> = [
  ['dashboard', 'Dashboard', <Activity/>],
  ['files', 'Files', <FilesIcon/>],
  ['snapshots', 'Snapshots', <Archive/>],
  ['cluster', 'Cluster', <HardDrive/>],
  ['integrity', 'Integrity & Repair', <ShieldCheck/>],
  ['audit', 'Audit Log', <FileClock/>],
  ['demo', 'Demo Lab', <FlaskConical/>],
];

export function AppShell({user, page, setPage, children, onSignOut}: {user: CurrentUser; page: Page; setPage: (page: Page) => void; children: ReactNode; onSignOut: () => void}) {
  const nav = NAV.filter(([id]) => canAccessPage(user.role, id));
  return <div className="shell"><aside><div className="brand"><div className="vaultMark"><Blocks size={23}/></div><div><b>QuorumVault</b><span>Control plane</span></div></div><nav>{nav.map(([id, label, icon]) => <button key={id} className={page === id ? 'active' : ''} onClick={() => setPage(id)}>{icon}<span>{label}</span></button>)}</nav><div className="account"><div><b>{user.email}</b><small>{user.role}</small></div><button title="Sign out" onClick={() => { setToken(null); onSignOut(); }}><LogOut size={17}/></button></div></aside><main>{children}</main></div>;
}
