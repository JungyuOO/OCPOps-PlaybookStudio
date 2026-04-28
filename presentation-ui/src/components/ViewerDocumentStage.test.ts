import { describe, expect, it } from 'vitest';

import { looksLikeSensitiveNetworkBlock } from './ViewerDocumentStage';

describe('ViewerDocumentStage sensitive network detection', () => {
  it('flags hosts-style operational network mappings', () => {
    const text = [
      '10.20.30.40 app-a.customer.example.com',
      '10.20.30.41 app-b.customer.example.com',
      '10.20.30.42 api.customer.example.com',
    ].join('\n');

    expect(looksLikeSensitiveNetworkBlock(text, 'Hosts')).toBe(true);
  });

  it('does not flag ordinary prose with a single public URL', () => {
    const text = 'Open the console route from the documented URL and confirm the authentication flow.';

    expect(looksLikeSensitiveNetworkBlock(text, 'Install validation')).toBe(false);
  });

  it('flags dense DNS/domain mapping tables even without IP addresses', () => {
    const text = [
      'Service API | api-a.customer.example.com | api-b.customer.example.com',
      'Admin API | admin-a.customer.example.com | admin-b.customer.example.com',
      'Web | web-a.customer.example.com | web-b.customer.example.com',
    ].join('\n');

    expect(looksLikeSensitiveNetworkBlock(text, '도메인 구성')).toBe(true);
  });
});
