import type {UserRole} from '../types';

export type Page = 'dashboard' | 'files' | 'snapshots' | 'cluster' | 'integrity' | 'audit' | 'demo';

export const ADMIN_PAGES: readonly Page[] = ['integrity', 'audit', 'demo'];

export function canAccessPage(role: UserRole, page: Page): boolean {
  return role === 'ADMIN' || !ADMIN_PAGES.includes(page);
}
