import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { ChatRelatedLink } from '../../lib/runtimeApi';
import {
  AssistantAnswer,
  copyableCommandTextFromCodeBlock,
  splitAnnotatedCommandCards,
  truthSurfaceCopy,
} from './WorkspaceAnswer';

const noop = () => {};

function lightspeedLink(): ChatRelatedLink {
  return {
    label: 'OpenShift Lightspeed 공식 답변',
    href: '/external/lightspeed/unit-test',
    kind: 'external_tool',
    summary: 'OpenShift Lightspeed가 반환한 OpenShift 공식 기준 답변',
    created_at: '2026-06-09T07:33:48.065101Z',
    source_lane: 'openshift_lightspeed',
    boundary_truth: 'external_openshift_lightspeed',
    runtime_truth_label: 'OpenShift Lightspeed',
    boundary_badge: 'Lightspeed + Customer',
  };
}

function goldLink(): ChatRelatedLink {
  return {
    label: '스토리지',
    href: '/playbooks/wiki-runtime/active/storage/index.html#lvms-creating-lvms-cluster-using-cli_logical-volume-manager-storage',
    kind: 'book',
    summary: '로컬 스토리지를 사용하는 영구 스토리지 > 논리 볼륨 관리자 스토리지를 사용하는 영구 스토리지 > LVMCluster 사용자 정의 리소스를 생성하는 방법 > CLI를 사용하여 LVMCluster CR 생성',
    source_lane: 'official_ko',
    boundary_truth: 'official_gold_playbook_runtime',
    runtime_truth_label: 'OpenShift 4.20 Gold Playbook',
    boundary_badge: 'Gold Playbook',
  };
}

describe('WorkspaceAnswer Lightspeed surface', () => {
  it('maps OpenShift Lightspeed truth metadata to the official label', () => {
    expect(truthSurfaceCopy(lightspeedLink())).toEqual({
      label: 'OpenShift Lightspeed',
      meta: ['OpenShift Lightspeed'],
    });
  });

  it('renders OpenShift Lightspeed as a compact external answer source', () => {
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
        primaryBoundaryBadge="Lightspeed + Customer"
        onCitationClick={noop}
        onRelatedLinkClick={noop}
        onToggleFavoriteLink={noop}
        onCheckSectionLink={noop}
        isFavoriteLink={() => false}
        isCheckedSectionLink={() => false}
      />,
    );

    expect(html).toContain('assistant-truth-chip');
    expect(html).toContain('OpenShift Lightspeed');
    expect(html).not.toContain('Lightspeed + Customer');
    expect(html).toContain('related-link-card--source-line');
    expect(html).toContain('2026-06-09');
    expect(html).not.toContain('OpenShift Lightspeed 공식 답변');
    expect(html).not.toContain('OpenShift Lightspeed가 반환한 OpenShift 공식 기준 답변');
    expect(html).toContain('related-link-badge');
  });

  it('renders related links as badge plus one-line subject without summaries', () => {
    const html = renderToStaticMarkup(
      <AssistantAnswer
        content="답변: LVMCluster CR 생성 기준을 확인합니다."
        citations={[]}
        relatedLinks={[lightspeedLink(), goldLink()]}
        relatedSections={[]}
        visionMode="atlas_canvas"
        primarySourceLane="openshift_lightspeed"
        primaryBoundaryTruth="external_openshift_lightspeed"
        primaryRuntimeTruthLabel="OpenShift Lightspeed"
        primaryBoundaryBadge="OpenShift Lightspeed"
        onCitationClick={noop}
        onRelatedLinkClick={noop}
        onToggleFavoriteLink={noop}
        onCheckSectionLink={noop}
        isFavoriteLink={() => false}
        isCheckedSectionLink={() => false}
      />,
    );

    expect(html).toContain('related-link-card--source-line');
    expect(html).toContain('2026-06-09');
    expect(html).toContain('스토리지');
    expect(html).not.toContain('로컬 스토리지를 사용하는 영구 스토리지');
    expect(html).not.toContain('OpenShift Lightspeed가 반환한 OpenShift 공식 기준 답변');
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

  it('renders step bullet command answers without raw asterisks and promotes CLI lines to code blocks', () => {
    const html = renderToStaticMarkup(
      <AssistantAnswer
        content={[
          '답변: 문제를 진단할 때는 먼저 이벤트를 확인하고 그 다음 로그를 확인합니다.',
          '',
          '1. **이벤트 확인 (상태 변화 및 오류 파악)**',
          '* 특정 네임스페이스의 이벤트를 확인하려면:',
          '`oc get events -n <namespace>`',
          '* 특정 Pod의 상세 상태와 이벤트를 함께 보려면:',
          '`oc describe pod <pod-name> -n <namespace>`',
          '',
          '2. **로그 확인 (상세 오류 메시지 분석)**',
          '* 현재 실행 중인 컨테이너의 로그를 실시간으로 확인하려면:',
          '`oc logs -f <pod-name> -n <namespace>`',
          '* 이전에 종료된 컨테이너의 로그를 확인하려면:',
          '`oc logs --previous <pod-name> -n <namespace>`',
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

    expect(html).toContain('answer-code-block');
    expect(html).toContain('answer-code-lang');
    expect(html).toContain('BASH');
    expect((html.match(/answer-code-block/g) || []).length).toBe(4);
    expect(html).toContain('oc get events -n &lt;namespace&gt;');
    expect(html).toContain('oc logs --previous &lt;pod-name&gt; -n &lt;namespace&gt;');
    expect(html).not.toContain('* 특정 네임스페이스');
  });

  it('copies only executable command lines from annotated command blocks', () => {
    expect(copyableCommandTextFromCodeBlock([
      '# 특정 네임스페이스의 모든 이벤트 확인',
      'oc get events -n <namespace>',
      '',
      '# 특정 Pod와 관련된 이벤트 확인',
      'oc describe pod <pod-name> -n <namespace>',
    ].join('\n'))).toBe([
      'oc get events -n <namespace>',
      'oc describe pod <pod-name> -n <namespace>',
    ].join('\n'));
  });

  it('splits annotated command fences into one copyable command card per command', () => {
    expect(splitAnnotatedCommandCards([
      '# 특정 네임스페이스의 모든 이벤트 확인',
      'oc get events -n <namespace>',
      '',
      '# 특정 Pod와 관련된 이벤트 확인',
      'oc describe pod <pod-name> -n <namespace>',
    ].join('\n'))).toEqual([
      {
        note: '특정 네임스페이스의 모든 이벤트 확인',
        code: 'oc get events -n <namespace>',
      },
      {
        note: '특정 Pod와 관련된 이벤트 확인',
        code: 'oc describe pod <pod-name> -n <namespace>',
      },
    ]);
  });
});
