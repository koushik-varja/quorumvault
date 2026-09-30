import {describe, expect, it} from 'vitest';
import {canAccessPage} from './utils/navigation';

describe('role-aware navigation', () => {
  it('hides administrative pages from USER', () => {
    expect(canAccessPage('USER', 'dashboard')).toBe(true);
    expect(canAccessPage('USER', 'integrity')).toBe(false);
    expect(canAccessPage('USER', 'audit')).toBe(false);
    expect(canAccessPage('USER', 'demo')).toBe(false);
  });

  it('allows ADMIN to access administrative pages', () => {
    expect(canAccessPage('ADMIN', 'integrity')).toBe(true);
    expect(canAccessPage('ADMIN', 'audit')).toBe(true);
    expect(canAccessPage('ADMIN', 'demo')).toBe(true);
  });
});
