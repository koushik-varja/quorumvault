import{describe,expect,it}from'vitest';import{formatBytes}from'./lib';
describe('formatBytes',()=>{it('formats storage units',()=>{expect(formatBytes(0)).toBe('0 B');expect(formatBytes(1024)).toBe('1.0 KiB');expect(formatBytes(1024*1024)).toBe('1.0 MiB')})})
