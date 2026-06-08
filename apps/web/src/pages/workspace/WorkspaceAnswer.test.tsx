import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { ChatRelatedLink } from '../../lib/runtimeApi';
import { AssistantAnswer, truthSurfaceCopy } from './WorkspaceAnswer';

const noop = () => {};

function lightspeedLink(): ChatRelatedLink {
  return {
    label: 'OpenShift Lightspeed 공식 답변',
    href: '/external/lightspeed/unit-test',
    kind: 'external_tool',
    summary: 'OpenShift Lightspeed가 반환한 OpenShift 공식 기준 답변',
    source_lane: 'openshift_lightspeed',
    boundary_truth: 'external_openshift_lightspeed',
    runtime_truth_label: 'OpenShift Lightspeed',
    boundary_badge: 'Lightspeed',
  };
}

describe('WorkspaceAnswer Lightspeed surface', () => {
  it('maps OpenShift Lightspeed truth metadata to the Lightspeed label', () => {
    expect(truthSurfaceCopy(lightspeedLink())).toEqual({
      label: 'Lightspeed',
      meta: ['OpenShift Lightspeed'],
    });
  });

  it('renders Lightspeed badge and external answer related link', () => {
    const html = renderToStaticMarkup(
      <AssistantAnswer
        content="답변: Events에서 FailedScheduling 여부를 먼저 확인합니다."
        citations={[]}
        relatedLinks={[lightspeedLink()]}
        relatedSections={[]}
        visionMode="atlas_canvas"
        primarySourceLane="openshift_lightspeed"
        primaryBoundaryTruth="external_openshift_lightspeed"
        primaryRuntimeTruthLabel="OpenShift Lightspeed"
        primaryBoundaryBadge="Lightspeed"
        onCitationClick={noop}
        onRelatedLinkClick={noop}
        onToggleFavoriteLink={noop}
        onCheckSectionLink={noop}
        isFavoriteLink={() => false}
        isCheckedSectionLink={() => false}
      />,
    );

    expect(html).toContain('assistant-truth-chip');
    expect(html).toContain('Lightspeed');
    expect(html).toContain('OpenShift Lightspeed 공식 답변');
    expect(html).toContain('OpenShift Lightspeed가 반환한 OpenShift 공식 기준 답변');
    expect(html).toContain('related-link-badge');
  });

  it('renders GFM-style markdown tables instead of plain pipe text', () => {
    const html = renderToStaticMarkup(
      <AssistantAnswer
        content={[
          '답변: 설정 값을 확인한 뒤 아래 체크리스트로 점검합니다.',
          '',
          '요약 점검 체크리스트',
          '| 점검 항목 | 확인 사항 | 관련 근거 |',
          '| :--- | :--- | :--- |',
          '| Operator | Pipeline Operator가 설치되었는가? | PAC 기본 조건 |',
          '| Feature | `pipelines-as-code`가 활성화되었는가? | PAC 기본 조건 |',
        ].join('\n')}
        citations={[]}
        relatedLinks={[]}
        relatedSections={[]}
        visionMode="atlas_canvas"
        onCitationClick={noop}
        onRelatedLinkClick={noop}
        onToggleFavoriteLink={noop}
        onCheckSectionLink={noop}
        isFavoriteLink={() => false}
        isCheckedSectionLink={() => false}
      />,
    );

    expect(html).toContain('class="assistant-table"');
    expect(html).toContain('<th><span>점검 항목</span></th>');
    expect(html).toContain('<td><span>Pipeline Operator가 설치되었는가?</span></td>');
    expect(html).toContain('<code class="inline-code">pipelines-as-code</code>');
    expect(html).not.toContain(':---');
  });
});
