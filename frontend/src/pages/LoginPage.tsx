import {useState, type FormEvent} from 'react';
import {Blocks} from 'lucide-react';
import {api, setToken} from '../api/client';

export function LoginPage({onReady}: {onReady: () => void}) {
  const [email, setEmail] = useState('admin@quorumvault.local');
  const [password, setPassword] = useState('QuorumVaultDemo!23');
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const result = await api<{access_token: string}>(`/auth/${mode}`, {method: 'POST', body: JSON.stringify({email, password})});
      setToken(result.access_token); onReady();
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  }
  return <div className="loginWrap"><div className="loginBrand"><div className="vaultMark"><Blocks size={28}/></div><div><b>QuorumVault</b><span>Distributed backup & recovery</span></div></div><form className="loginCard" onSubmit={submit}><div className="eyebrow">CONTROL PLANE</div><h1>{mode === 'login' ? 'Access the vault' : 'Create an account'}</h1><p>Observe placement, integrity and self-healing across the storage cluster.</p><label>Email<input value={email} onChange={e => setEmail(e.target.value)} type="email" required/></label><label>Password<input value={password} onChange={e => setPassword(e.target.value)} type="password" minLength={10} required/></label>{error && <div className="errorBox">{error}</div>}<button className="primary" disabled={busy}>{busy ? 'Working…' : mode === 'login' ? 'Sign in' : 'Register'}</button><button type="button" className="linkBtn" onClick={() => setMode(mode === 'login' ? 'register' : 'login')}>{mode === 'login' ? 'Need a user account? Register' : 'Already registered? Sign in'}</button><div className="demoHint">Demo admin credentials are prefilled when <code>DEMO_MODE=true</code>.</div></form></div>;
}
