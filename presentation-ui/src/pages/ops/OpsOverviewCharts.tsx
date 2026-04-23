import {
  Bar,
  BarChart,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { OcpMetricsResponse, OcpOverview } from '../../lib/opsConsoleApi';

function clampPercent(value: number): number {
  return Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0));
}

function formatMetricNumber(value: number | undefined, unit: string): string {
  if (!Number.isFinite(value ?? NaN)) {
    return `0 ${unit}`;
  }
  return `${Number(value).toFixed(1)} ${unit}`;
}

function MiniDonutMetric({
  label,
  value,
  subtitle,
  percent,
  tooltipLabel,
}: {
  label: string;
  value: string;
  subtitle?: string;
  percent: number;
  tooltipLabel: string;
}) {
  const normalized = clampPercent(percent);
  const chartData = [
    { name: 'active', value: normalized, fill: '#1167ac' },
    { name: 'rest', value: Math.max(100 - normalized, 0), fill: 'rgba(17, 103, 172, 0.08)' },
  ];
  return (
    <article className="ops-metric-card ops-metric-card-chart">
      <div className="ops-chart-wrap">
        <ResponsiveContainer width="100%" height={110}>
          <PieChart>
            <Pie
              data={chartData}
              innerRadius={30}
              outerRadius={44}
              startAngle={90}
              endAngle={-270}
              dataKey="value"
              stroke="none"
            >
              {chartData.map((entry) => (
                <Cell key={`${label}-${entry.name}`} fill={entry.fill} />
              ))}
            </Pie>
            <Tooltip
              formatter={(entryValue) => [`${Number(entryValue).toFixed(1)}%`, tooltipLabel]}
              contentStyle={{ borderRadius: 12, border: '1px solid rgba(16,36,62,0.08)' }}
            />
          </PieChart>
        </ResponsiveContainer>
        <div className="ops-chart-center-copy">
          <strong>{Math.round(normalized)}%</strong>
        </div>
      </div>
      <div className="ops-metric-copy" title={value}>
        <span>{label}</span>
        <strong className="ops-metric-title-truncate">{value}</strong>
        {subtitle ? <p>{subtitle}</p> : null}
      </div>
    </article>
  );
}

export default function OpsOverviewCharts({
  overview,
  overviewMetrics,
  activeConnectionId,
  selectedNamespace,
  onOpenResource,
}: {
  overview: OcpOverview | null;
  overviewMetrics: OcpMetricsResponse;
  activeConnectionId: string;
  selectedNamespace: string;
  onOpenResource: (args: { connection_id?: string; resource_type?: string; namespace?: string; name?: string }) => void | Promise<void>;
}) {
  const topCpuShare = overviewMetrics.pod_cpu_top.length
    ? (Number(overviewMetrics.summary.top_cpu_pod?.cpu_mcores || 0) / Math.max(
      overviewMetrics.pod_cpu_top.reduce((sum, item) => sum + Number(item.cpu_mcores || 0), 0),
      1,
    )) * 100
    : 0;
  const topMemoryShare = overviewMetrics.pod_memory_top.length
    ? (Number(overviewMetrics.summary.top_memory_pod?.memory_mib || 0) / Math.max(
      overviewMetrics.pod_memory_top.reduce((sum, item) => sum + Number(item.memory_mib || 0), 0),
      1,
    )) * 100
    : 0;
  const degradedRatio = (Number(overviewMetrics.summary.degraded_deployments || 0) / Math.max(Number(overview?.resource_counts?.deployments || 0), 1)) * 100;
  const warningRatio = (Number(overviewMetrics.summary.warning_events || 0) / Math.max(Number(overview?.resource_counts?.events || 0), 1)) * 100;

  return (
    <>
      <div className="ops-overview-grid">
        <MiniDonutMetric
          label="Top CPU Pod"
          value={overviewMetrics.summary.top_cpu_pod?.name || 'N/A'}
          subtitle={overviewMetrics.summary.top_cpu_pod ? formatMetricNumber(overviewMetrics.summary.top_cpu_pod.cpu_mcores, 'mcores') : 'No metric data'}
          percent={topCpuShare}
          tooltipLabel={overviewMetrics.summary.top_cpu_pod ? formatMetricNumber(overviewMetrics.summary.top_cpu_pod.cpu_mcores, 'mcores') : 'No metric data'}
        />
        <MiniDonutMetric
          label="Top Memory Pod"
          value={overviewMetrics.summary.top_memory_pod?.name || 'N/A'}
          subtitle={overviewMetrics.summary.top_memory_pod ? formatMetricNumber(overviewMetrics.summary.top_memory_pod.memory_mib, 'MiB') : 'No metric data'}
          percent={topMemoryShare}
          tooltipLabel={overviewMetrics.summary.top_memory_pod ? formatMetricNumber(overviewMetrics.summary.top_memory_pod.memory_mib, 'MiB') : 'No metric data'}
        />
        <MiniDonutMetric
          label="Degraded Deployments"
          value={String(overviewMetrics.summary.degraded_deployments)}
          subtitle=""
          percent={degradedRatio}
          tooltipLabel={`${overviewMetrics.summary.degraded_deployments} degraded / ${overview?.resource_counts?.deployments ?? 0} total`}
        />
        <MiniDonutMetric
          label="Warning Events"
          value={String(overviewMetrics.summary.warning_events)}
          subtitle=""
          percent={warningRatio}
          tooltipLabel={`${overviewMetrics.summary.warning_events} warnings / ${overview?.resource_counts?.events ?? 0} total`}
        />
      </div>

      <div className="ops-action-grid">
        <div className="ops-panel-subsection">
          <h3>Top CPU Pods</h3>
          <div className="ops-chart-panel">
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={overviewMetrics.pod_cpu_top} layout="vertical" margin={{ top: 0, right: 10, left: 10, bottom: 0 }}>
                <XAxis type="number" hide />
                <YAxis dataKey="name" type="category" width={180} tick={{ fontSize: 11, fill: '#607896' }} />
                <Tooltip cursor={{ fill: 'rgba(17, 103, 172, 0.06)' }} />
                <Bar dataKey="cpu_mcores" radius={[0, 10, 10, 0]}>
                  {overviewMetrics.pod_cpu_top.map((item) => (
                    <Cell key={`cpu-bar-${item.name}`} fill="#1167ac" />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          {overviewMetrics.pod_cpu_top.map((item) => (
            <div key={`cpu-${item.name}`} className="ops-table-row">
              <div>
                <strong>{item.name}</strong>
                <span>{item.cpu_mcores} mcores</span>
              </div>
              <div className="ops-inline-actions">
                <button type="button" onClick={() => { void onOpenResource({ connection_id: activeConnectionId, resource_type: 'pods', namespace: selectedNamespace, name: item.name }); }}>
                  Open Detail
                </button>
              </div>
            </div>
          ))}
        </div>

        <div className="ops-panel-subsection">
          <h3>Top Memory Pods</h3>
          <div className="ops-chart-panel">
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={overviewMetrics.pod_memory_top} layout="vertical" margin={{ top: 0, right: 10, left: 10, bottom: 0 }}>
                <XAxis type="number" hide />
                <YAxis dataKey="name" type="category" width={180} tick={{ fontSize: 11, fill: '#607896' }} />
                <Tooltip cursor={{ fill: 'rgba(15, 132, 121, 0.06)' }} />
                <Bar dataKey="memory_mib" radius={[0, 10, 10, 0]}>
                  {overviewMetrics.pod_memory_top.map((item) => (
                    <Cell key={`mem-bar-${item.name}`} fill="#0f8479" />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          {overviewMetrics.pod_memory_top.map((item) => (
            <div key={`mem-${item.name}`} className="ops-table-row">
              <div>
                <strong>{item.name}</strong>
                <span>{item.memory_mib} MiB</span>
              </div>
              <div className="ops-inline-actions">
                <button type="button" onClick={() => { void onOpenResource({ connection_id: activeConnectionId, resource_type: 'pods', namespace: selectedNamespace, name: item.name }); }}>
                  Open Detail
                </button>
              </div>
            </div>
          ))}
        </div>

        <div className="ops-panel-subsection">
          <h3>Degraded Deployments</h3>
          {overviewMetrics.workload_health.length > 0 ? overviewMetrics.workload_health.map((item) => (
            <div key={`workload-${item.name}`} className="ops-table-row">
              <div>
                <strong>{item.name}</strong>
                <span>{item.ready_replicas}/{item.replicas} ready</span>
              </div>
              <div className="ops-inline-actions">
                <button type="button" onClick={() => { void onOpenResource({ connection_id: activeConnectionId, resource_type: 'deployments', namespace: selectedNamespace, name: item.name }); }}>
                  Open YAML
                </button>
              </div>
            </div>
          )) : <p className="ops-muted">No degraded deployments.</p>}
        </div>

        <div className="ops-panel-subsection">
          <h3>Recent Warnings</h3>
          {overviewMetrics.event_summary.length > 0 ? overviewMetrics.event_summary.map((item, index) => (
            <div key={`event-${item.name}-${index}`} className="ops-table-row">
              <div>
                <strong>{item.name}</strong>
                <span>{item.phase}</span>
              </div>
            </div>
          )) : <p className="ops-muted">No warning events.</p>}
        </div>
      </div>
    </>
  );
}
