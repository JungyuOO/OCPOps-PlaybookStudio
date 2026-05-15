import { afterEach, describe, expect, it } from 'vitest';
import { applyRuntimeIdentityHeader, setRuntimeIdentityUser } from './runtimeApi';

describe('runtime identity headers', () => {
  afterEach(() => {
    setRuntimeIdentityUser(null);
  });

  it('does not inject env-token when no trusted identity exists', () => {
    const headers = applyRuntimeIdentityHeader(new Headers());

    expect(headers.has('X-User')).toBe(false);
    expect(headers.has('X-Forwarded-User')).toBe(false);
    expect(headers.has('X-Remote-User')).toBe(false);
  });

  it('preserves explicit trusted identity headers', () => {
    const headers = new Headers({ 'X-Forwarded-User': 'alice@example.com' });

    const result = applyRuntimeIdentityHeader(headers);

    expect(result.get('X-Forwarded-User')).toBe('alice@example.com');
    expect(result.has('X-User')).toBe(false);
  });

  it('injects the active profile identity after the app marks it trusted', () => {
    setRuntimeIdentityUser('env-token');

    const result = applyRuntimeIdentityHeader(new Headers());

    expect(result.get('X-User')).toBe('env-token');
  });
});
