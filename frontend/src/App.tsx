import {useEffect, useState, type ReactNode} from 'react';
import {api, setToken, token} from './api/client';
import {AppShell} from './components/AppShell';
import {AuditPage} from './pages/AuditPage';
import {ClusterPage} from './pages/ClusterPage';
import {DashboardPage} from './pages/DashboardPage';
import {DemoLabPage} from './pages/DemoLabPage';
import {FilesPage} from './pages/FilesPage';
import {IntegrityPage} from './pages/IntegrityPage';
import {LoginPage} from './pages/LoginPage';
import {SnapshotsPage} from './pages/SnapshotsPage';
import type {CurrentUser} from './types';
import {canAccessPage, type Page} from './utils/navigation';

export default function App() {
  const [ready, setReady] = useState(Boolean(token()));
  const [page, setPage] = useState<Page>('dashboard');
  const [me, setMe] = useState<CurrentUser | null>(null);
  useEffect(() => {
    if (!ready) { setMe(null); return; }
    void api<CurrentUser>('/me').then(user => { setMe(user); if (!canAccessPage(user.role, page)) setPage('dashboard'); }).catch(() => { setToken(null); setReady(false); });
  }, [ready, page]);
  if (!ready) return <LoginPage onReady={() => setReady(true)}/>;
  if (!me) return <div className="loading">Loading account…</div>;
  const content: Record<Page, ReactNode> = {
    dashboard: <DashboardPage/>,
    files: <FilesPage/>,
    snapshots: <SnapshotsPage/>,
    cluster: <ClusterPage/>,
    integrity: <IntegrityPage/>,
    audit: <AuditPage/>,
    demo: <DemoLabPage/>,
  };
  return <AppShell user={me} page={page} setPage={setPage} onSignOut={() => setReady(false)}>{content[page]}</AppShell>;
}
