import { describe, expect, it } from 'vitest';
import { displayCustomerDocumentTitle } from './customerDocumentTitles';

describe('customerDocumentTitles', () => {
  it('turns raw customer architecture filenames into readable document titles', () => {
    expect(displayCustomerDocumentTitle({
      title: 'KMSC-COCP-RECR-005_아키텍쳐설계서_OCP운영_20260119_FINAL',
    })).toBe('OCP 운영 아키텍처 설계서');
    expect(displayCustomerDocumentTitle({
      title: 'KMSC-COCP-RECR-005_아키텍처설계서_서비스메쉬_20260116_FINAL',
    })).toBe('서비스 메시 아키텍처 설계서');
    expect(displayCustomerDocumentTitle({
      title: 'KMSC-COCP-RECR-005_아키텍처설계서_CICD_20251208_FINAL',
    })).toBe('CI/CD 아키텍처 설계서');
  });

  it('turns raw test and report filenames into book-outline titles', () => {
    expect(displayCustomerDocumentTitle({
      title: '완료보고_20260112_완료본',
    })).toBe('운영 전환 완료 보고');
    expect(displayCustomerDocumentTitle({
      title: 'KMSC-COCP-RTER-003-서비스 통합 및  성능 테스트 결과서_20251205_FINAL',
    })).toBe('서비스 통합/성능 테스트 결과');
    expect(displayCustomerDocumentTitle({
      title: 'KMSC-COCP-RECR-005_서비스단위테스트계획서_20251208',
    })).toBe('서비스 단위 테스트 계획');
  });

  it('keeps already-friendly titles unchanged', () => {
    expect(displayCustomerDocumentTitle({
      title: 'KOMSCO 지급결제플랫폼 OCP 운영 플레이북',
    })).toBe('KOMSCO 지급결제플랫폼 OCP 운영 플레이북');
    expect(displayCustomerDocumentTitle({
      title: 'Test 1 - Surya',
    })).toBe('Test 1 - Surya');
  });
});
