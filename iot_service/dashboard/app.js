// Industrial Dashboard State & Logic (Phase 4A & 4B Read-Only Agent Visibility)
let state = {
  theme: localStorage.getItem('denso_theme') || 'dark',
  kiosk: new URLSearchParams(window.location.search).get('kiosk') === '1',
  token: new URLSearchParams(window.location.search).get('token') || localStorage.getItem('denso_token') || '',
  mode: 'sse', // 'sse' or 'poll'
  activeTab: 'events', // 'events' or 'agent'
  eventSource: null,
  pollTimer: null,
  activeMachineId: null,
  overviewData: null,
  agentStatusData: null,
  events: [],
  selectedMinutes: 15,
  charts: {},
  lastServerMessageTime: Date.now(),
};

// Apply initial theme & kiosk
document.documentElement.setAttribute('data-theme', state.theme);
if (state.kiosk) {
  document.body.classList.add('kiosk');
}

// Helpers
function getAuthHeaders() {
  const h = { 'Accept': 'application/json' };
  if (state.token) {
    h['X-Dashboard-Token'] = state.token;
  }
  return h;
}

function formatTime(isoStr) {
  if (!isoStr) return '--:--:--';
  const d = new Date(isoStr);
  return isNaN(d.getTime()) ? isoStr : d.toLocaleTimeString();
}

function formatRelativeTime(isoStr) {
  if (!isoStr) return 'chưa có dữ liệu';
  const d = new Date(isoStr);
  const diffSec = Math.floor((Date.now() - d.getTime()) / 1000);
  if (diffSec < 2) return 'vừa xong';
  if (diffSec < 60) return `${diffSec} giây trước`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin} phút trước`;
  return `${Math.floor(diffMin / 60)} giờ trước`;
}

function getStatusBadge(st, isMitigated) {
  if (isMitigated) {
    return `<span class="machine-badge badge-mitigated" title="Đã hạ tốc độ thành công, đang mở phiếu sửa chữa">🛡 Đã giảm nhẹ</span>`;
  }
  switch (st) {
    case 'normal':
      return `<span class="machine-badge badge-normal">✓ Bình thường</span>`;
    case 'warn':
      return `<span class="machine-badge badge-warn">▲ Cảnh báo</span>`;
    case 'critical':
      return `<span class="machine-badge badge-critical">✖ Nguy hiểm</span>`;
    case 'offline':
    default:
      return `<span class="machine-badge badge-offline">? Mất kết nối</span>`;
  }
}

function getTrendIcon(trend, slope) {
  if (trend === 'rising') return `<span style="color:#ef4444" title="${slope > 0 ? '+' : ''}${slope}/phút">▲</span>`;
  if (trend === 'falling') return `<span style="color:#3b82f6" title="${slope > 0 ? '+' : ''}${slope}/phút">▼</span>`;
  return `<span style="color:var(--text-muted)" title="Ổn định">▬</span>`;
}

// Zone Range Bar Calculation
function renderZoneBar(metric) {
  const min = metric.display_min !== null && metric.display_min !== undefined ? metric.display_min : 0;
  const max = metric.display_max !== null && metric.display_max !== undefined ? metric.display_max : 100;
  const span = Math.max(0.001, max - min);

  const val = metric.value !== null && metric.value !== undefined ? metric.value : min;
  const clampedVal = Math.max(min, Math.min(max, val));
  const pinPosPct = ((clampedVal - min) / span) * 100;

  let segmentsHtml = '';
  const dir = metric.direction;

  if (dir === 'above' && metric.warn !== null && metric.critical !== null) {
    const pWarn = Math.max(0, Math.min(100, ((metric.warn - min) / span) * 100));
    const pCrit = Math.max(0, Math.min(100, ((metric.critical - min) / span) * 100));
    segmentsHtml = `
      <div class="zone-segment normal" style="left:0%; width:${pWarn}%"></div>
      <div class="zone-segment warn" style="left:${pWarn}%; width:${pCrit - pWarn}%"></div>
      <div class="zone-segment critical" style="left:${pCrit}%; width:${100 - pCrit}%"></div>
    `;
  } else if (dir === 'below' && metric.warn !== null && metric.critical !== null) {
    const pCrit = Math.max(0, Math.min(100, ((metric.critical - min) / span) * 100));
    const pWarn = Math.max(0, Math.min(100, ((metric.warn - min) / span) * 100));
    segmentsHtml = `
      <div class="zone-segment critical" style="left:0%; width:${pCrit}%"></div>
      <div class="zone-segment warn" style="left:${pCrit}%; width:${pWarn - pCrit}%"></div>
      <div class="zone-segment normal" style="left:${pWarn}%; width:${100 - pWarn}%"></div>
    `;
  } else {
    segmentsHtml = `<div class="zone-segment normal" style="left:0%; width:100%"></div>`;
  }

  return `
    <div class="zone-bar-container" title="Thang: ${min} .. ${max} ${metric.unit}">
      ${segmentsHtml}
      <div class="zone-pin" style="left: ${pinPosPct}%"></div>
    </div>
  `;
}

// Render Overview UI
function renderOverview(data) {
  state.overviewData = data;
  state.lastServerMessageTime = Date.now();
  hideOfflineBanner();

  // 1. Header connection info
  const connPill = document.getElementById('connectionStatusPill');
  if (state.mode === 'sse') {
    connPill.innerHTML = `<span class="dot-live"></span> TRỰC TIẾP (SSE)`;
  } else {
    connPill.innerHTML = `<span class="dot-poll"></span> ĐANG POLL (3s)`;
  }

  const sys = data.system;
  
  // Degraded warning check (in-memory mode)
  const degBanner = document.getElementById('degradedBanner');
  if (degBanner) {
    if (!sys.db_connected) {
      degBanner.style.display = 'block';
    } else {
      degBanner.style.display = 'none';
    }
  }

  const dbStatusText = sys.db_connected 
    ? '✓ TimescaleDB' 
    : '<span style="color:var(--status-warn); font-weight:700;">⚠ In-Memory (Bộ nhớ tạm)</span>';

  document.getElementById('sysInfoText').innerHTML = `
    MQTT: <strong>${sys.mqtt_connected ? '✓ Kết nối' : '✗ Ngắt'}</strong> | 
    DB: <strong>${dbStatusText}</strong> | 
    Cập nhật: <strong>${sys.seconds_since_last_data !== null ? `${sys.seconds_since_last_data}s trước` : '--'}</strong>
  `;

  // 2. Render Agent Header Status Bar
  if (data.agent_summary) {
    const as = data.agent_summary;
    const modeDesc = {
      'advisory': 'Chỉ cảnh báo và gợi ý, không gửi lệnh PLC',
      'hitl': 'Chờ kỹ sư phê duyệt trước khi hạ tốc độ (Human-in-the-loop)',
      'auto_safe': 'Tự động hạ tốc độ trong giới hạn an toàn tối đa 2 lần'
    };
    const curMode = as.autonomy_mode || 'hitl';
    const autonomyPill = document.getElementById('agentAutonomyPill');
    autonomyPill.title = `${curMode.toUpperCase()}: ${modeDesc[curMode] || ''}`;
    document.getElementById('agentAutonomyText').innerText = curMode.toUpperCase();

    const modeText = as.agent_mode === 'llm' ? 'LLM ReAct' : 'Playbook Luật';
    document.getElementById('agentModeText').innerText = modeText;

    const ind = autonomyPill.querySelector('.agent-indicator');
    if (as.agent_enabled) {
      document.getElementById('agentStatusText').innerText = 'Bật';
      ind.classList.remove('disabled');
      document.getElementById('agentStatusPill').title = 'Agent đang kích hoạt giám sát';
    } else {
      document.getElementById('agentStatusText').innerText = 'Tắt khẩn cấp';
      ind.classList.add('disabled');
      document.getElementById('agentStatusPill').title = 'Agent đã bị tắt khẩn cấp: không tạo lệnh tự động';
    }

    const openCount = as.open_incidents_count || 0;
    const countBadge = document.getElementById('agentOpenIncidentsBadge');
    if (countBadge) countBadge.innerText = openCount;

    // WebUI Link setup
    const webuiLink = document.getElementById('webuiLink');
    if (as.webui_url) {
      webuiLink.href = as.webui_url;
      webuiLink.style.display = 'inline-block';
    } else {
      webuiLink.style.display = 'none';
    }
  }

  // 3. Status Counters Bar
  const counts = sys.counts_by_status;
  document.getElementById('countersBar').innerHTML = `
    <div class="counter-pill">Tổng: <strong>${sys.total_machines}</strong></div>
    <div class="counter-pill normal">Bình thường: <strong>${counts.normal || 0}</strong></div>
    <div class="counter-pill warn">Cảnh báo: <strong>${counts.warn || 0}</strong></div>
    <div class="counter-pill critical">Nguy hiểm: <strong>${counts.critical || 0}</strong></div>
    <div class="counter-pill offline">Mất kết nối: <strong>${counts.offline || 0}</strong></div>
  `;

  // 4. Machines Grid
  const grid = document.getElementById('machinesGrid');
  grid.innerHTML = data.machines.map(m => {
    const isOffline = m.overall_status === 'offline';
    const relativeTime = formatRelativeTime(m.last_seen);
    const cardStatusClass = m.is_mitigated ? 'st-mitigated' : `st-${m.overall_status}`;

    // Agent banner in machine card
    let agentBannerHtml = '';
    if (m.pending_action) {
      const expDate = new Date(m.pending_action.expires_at);
      const remainingSec = Math.max(0, Math.floor((expDate.getTime() - Date.now()) / 1000));
      agentBannerHtml = `
        <div class="card-agent-banner has-pending">
          <div class="agent-banner-title">
            <span>⚡ Đang chờ kỹ sư duyệt lệnh (${m.pending_action.command})</span>
            <span class="agent-countdown" id="cd_${m.pending_action.id}">còn ${remainingSec}s</span>
          </div>
          <div class="agent-banner-action">${m.pending_action.rationale || ''}</div>
        </div>
      `;
    } else if (m.latest_mitigation) {
      agentBannerHtml = `
        <div class="card-agent-banner is-mitigated">
          <div class="agent-banner-title">
            <span>🛡 Đã thực thi can thiệp</span>
            <span style="font-size:0.7rem; color:var(--text-muted);">${m.latest_mitigation.status.toUpperCase()}</span>
          </div>
          <div class="agent-banner-action">${m.latest_mitigation.summary}</div>
        </div>
      `;
    } else if (m.open_incident) {
      agentBannerHtml = `
        <div class="card-agent-banner has-incident">
          <div class="agent-banner-title">
            <span>⚠ Sự cố: ${m.open_incident.id}</span>
            <span style="color:var(--status-warn); font-size:0.7rem;">${m.open_incident.severity.toUpperCase()}</span>
          </div>
          <div class="agent-banner-action">${m.open_incident.root_cause || m.open_incident.title} (tin cậy ${Math.round((m.open_incident.confidence || 0) * 100)}%)</div>
        </div>
      `;
    }

    const metricsHtml = Object.keys(m.metrics).map(k => {
      const metric = m.metrics[k];
      const valStr = metric.value !== null ? metric.value.toFixed(metric.decimals) : '--';
      const trendHtml = getTrendIcon(metric.trend, metric.slope_per_min);
      const zoneBarHtml = renderZoneBar(metric);

      let etaHtml = '';
      if (metric.eta_to_critical_s && metric.eta_to_critical_s > 0 && metric.eta_to_critical_s < 600) {
        const minVal = Math.round(metric.eta_to_critical_s / 60);
        etaHtml = `<div class="eta-alert">⚠ Dự kiến chạm mức nguy hiểm sau ~${minVal || 1} phút</div>`;
      }

      return `
        <div class="metric-row">
          <div class="metric-header">
            <span class="metric-label">${metric.label}</span>
            <div class="metric-value-box st-${metric.status} tabular-nums">
              <span>${valStr} <small style="font-size:0.75rem; color:var(--text-muted)">${metric.unit}</small></span>
              <span class="metric-trend">${trendHtml}</span>
            </div>
          </div>
          ${zoneBarHtml}
          ${etaHtml}
        </div>
      `;
    }).join('');

    return `
      <div class="machine-card ${cardStatusClass}" onclick="openMachineDetail('${m.machine_id}')">
        <div class="card-header">
          <div class="machine-title">
            <span>${m.machine_id}</span>
          </div>
          ${getStatusBadge(m.overall_status, m.is_mitigated)}
        </div>
        <div class="card-meta">
          <span>${m.description}</span>
          <span class="tabular-nums">${isOffline ? '⚠ Quá hạn dữ liệu' : relativeTime}</span>
        </div>
        ${agentBannerHtml}
        <div class="card-metrics-list">
          ${metricsHtml}
        </div>
      </div>
    `;
  }).join('');
}

// Render Events Stream
function renderEvents(events) {
  state.events = events;
  const list = document.getElementById('eventsList');
  if (!events || events.length === 0) {
    list.innerHTML = `<div style="padding:16px; color:var(--text-muted); text-align:center;">Chưa có sự kiện nào</div>`;
    return;
  }

  list.innerHTML = events.map(e => `
    <div class="event-row ${e.severity}">
      <div class="event-top">
        <span><strong>${e.machine_id}</strong> · ${formatTime(e.timestamp)}</span>
        ${e.repeat_count > 1 ? `<span class="event-repeat">×${e.repeat_count}</span>` : ''}
      </div>
      <div class="event-code">${e.error_code} (${e.severity})</div>
      <div class="event-msg">${e.message || ''}</div>
    </div>
  `).join('');
}

function prependLiveEvent(ev) {
  const list = document.getElementById('eventsList');
  if (!list) return;
  const div = document.createElement('div');
  div.className = `event-row ${ev.severity} highlight`;
  div.innerHTML = `
    <div class="event-top">
      <span><strong>${ev.machine_id}</strong> · ${formatTime(ev.timestamp)}</span>
      ${ev.repeat_count > 1 ? `<span class="event-repeat">×${ev.repeat_count}</span>` : ''}
    </div>
    <div class="event-code">${ev.error_code} (${ev.severity})</div>
    <div class="event-msg">${ev.message || ''}</div>
  `;
  list.insertBefore(div, list.firstChild);
}

// Render Agent Activity Tab
function renderAgentActivity(agentData) {
  state.agentStatusData = agentData;
  const list = document.getElementById('agentActivityList');
  if (!list) return;

  const incidents = agentData.open_incidents || [];
  const actions = agentData.recent_actions || [];

  if (incidents.length === 0 && actions.length === 0) {
    list.innerHTML = `<div style="padding:16px; color:var(--text-muted); text-align:center;">Chưa có sự cố hoặc hành động nào từ Agent.</div>`;
    return;
  }

  let html = '';
  if (incidents.length > 0) {
    html += `<div style="font-weight:700; font-size:0.75rem; color:var(--text-muted); margin:6px 0 4px;">SỰ CỐ ĐANG MỞ (${incidents.length})</div>`;
    html += incidents.map(inc => `
      <div class="agent-row proposed">
        <div class="agent-top">
          <span><strong>${inc.machine_id}</strong> · ${inc.id}</span>
          <span style="color:var(--status-warn); font-weight:700;">${inc.severity.toUpperCase()}</span>
        </div>
        <div class="agent-title">${inc.root_cause || inc.title}</div>
        <div class="agent-desc">Độ tin cậy: ${Math.round((inc.confidence || 0) * 100)}% · Trạng thái: ${inc.status}</div>
      </div>
    `).join('');
  }

  if (actions.length > 0) {
    html += `<div style="font-weight:700; font-size:0.75rem; color:var(--text-muted); margin:10px 0 4px;">LỊCH SỬ HÀNH ĐỘNG GẦN ĐÂY</div>`;
    html += actions.map(act => {
      let rowClass = 'proposed';
      let statusVi = 'Đang chờ duyệt';
      if (act.status === 'acked') { rowClass = 'acked'; statusVi = 'Đã thực thi & ACK'; }
      else if (act.status === 'approved' || act.status === 'executing') { rowClass = 'approved'; statusVi = 'Đang thực thi'; }
      else if (act.status === 'expired') { rowClass = 'expired'; statusVi = 'Hết hạn, không thực thi'; }
      else if (act.status === 'rejected') { rowClass = 'rejected'; statusVi = 'Bị từ chối'; }

      const who = act.auto_executed ? 'Agent tự động' : (act.decided_by || 'Agent đề xuất');
      const rpmStr = act.params && act.params.rpm ? `(rpm=${act.params.rpm})` : '';

      return `
        <div class="agent-row ${rowClass}">
          <div class="agent-top">
            <span><strong>${act.machine_id}</strong> · ${who}</span>
            <span style="font-weight:700;">${statusVi}</span>
          </div>
          <div class="agent-title">${act.command} ${rpmStr}</div>
          <div class="agent-desc">${act.rationale || ''}</div>
          ${act.ack ? `<div style="color:var(--status-mitigated); font-size:0.7rem; margin-top:2px;">ACK: ${act.ack.message || JSON.stringify(act.ack)}</div>` : ''}
        </div>
      `;
    }).join('');
  }

  list.innerHTML = html;
}

function switchRightTab(tab) {
  state.activeTab = tab;
  const tabEventsBtn = document.getElementById('tabEventsBtn');
  const tabAgentBtn = document.getElementById('tabAgentBtn');
  const viewEventsTab = document.getElementById('viewEventsTab');
  const viewAgentTab = document.getElementById('viewAgentTab');

  if (tab === 'events') {
    tabEventsBtn.classList.add('active');
    tabAgentBtn.classList.remove('active');
    viewEventsTab.style.display = 'block';
    viewAgentTab.style.display = 'none';
  } else {
    tabAgentBtn.classList.add('active');
    tabEventsBtn.classList.remove('active');
    viewEventsTab.style.display = 'none';
    viewAgentTab.style.display = 'block';
    fetchAgentStatus();
  }
}

// SSE and Polling Connections
function connectSSE() {
  if (state.eventSource) {
    state.eventSource.close();
  }

  const sseUrl = `/api/v1/stream${state.token ? `?token=${encodeURIComponent(state.token)}` : ''}`;
  console.log('Connecting SSE to:', sseUrl);
  const es = new EventSource(sseUrl);
  state.eventSource = es;

  es.addEventListener('snapshot', e => {
    try {
      const data = JSON.parse(e.data);
      renderOverview(data);
      fetchAgentStatus();
    } catch (err) {
      console.error('Failed to parse snapshot:', err);
    }
  });

  es.addEventListener('metrics', e => {
    try {
      state.lastServerMessageTime = Date.now();
      hideOfflineBanner();
      fetchOverview();
    } catch (err) {
      console.error('Failed to parse metrics event:', err);
    }
  });

  es.addEventListener('event', e => {
    try {
      const ev = JSON.parse(e.data);
      prependLiveEvent(ev);
    } catch (err) {
      console.error('Failed to parse SSE event:', err);
    }
  });

  es.addEventListener('incident', e => {
    fetchOverview();
    fetchAgentStatus();
  });

  es.addEventListener('action', e => {
    fetchOverview();
    fetchAgentStatus();
  });

  es.addEventListener('machine_status', e => {
    fetchOverview();
  });

  es.addEventListener('heartbeat', e => {
    state.lastServerMessageTime = Date.now();
    hideOfflineBanner();
  });

  es.onerror = () => {
    console.warn('SSE connection failed or disconnected. Switching to polling fallback...');
    es.close();
    state.mode = 'poll';
    startPolling();
  };
}

function startPolling() {
  if (state.pollTimer) clearInterval(state.pollTimer);
  fetchOverview();
  fetchAgentStatus();
  state.pollTimer = setInterval(() => {
    fetchOverview();
    fetchAgentStatus();
  }, 3000);
}

async function fetchOverview() {
  try {
    const res = await fetch('/api/v1/dashboard/overview', { headers: getAuthHeaders() });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderOverview(data);
  } catch (err) {
    console.error('Failed to fetch overview:', err);
    showOfflineBanner();
  }
}

async function fetchAgentStatus() {
  try {
    const res = await fetch('/api/v1/dashboard/agent', { headers: getAuthHeaders() });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderAgentActivity(data);
  } catch (err) {
    console.error('Failed to fetch agent status:', err);
  }
}

async function fetchEvents() {
  const machine = document.getElementById('filterMachine').value;
  const severity = document.getElementById('filterSeverity').value;
  let q = `/api/v1/dashboard/events?limit=50`;
  if (machine) q += `&machine=${encodeURIComponent(machine)}`;
  if (severity) q += `&severity=${encodeURIComponent(severity)}`;

  try {
    const res = await fetch(q, { headers: getAuthHeaders() });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderEvents(data.events);
  } catch (err) {
    console.error('Failed to fetch events:', err);
  }
}

// Machine Detail Charts (Chart.js)
async function openMachineDetail(mId) {
  state.activeMachineId = mId;
  window.location.hash = `#/machine/${mId}`;
  document.getElementById('modalTitle').innerText = `Chi tiết Bệ thử: ${mId}`;
  document.getElementById('machineDetailModal').style.display = 'flex';
  await loadMachineCharts(mId, state.selectedMinutes);
}

function closeMachineDetail() {
  state.activeMachineId = null;
  window.location.hash = '';
  document.getElementById('machineDetailModal').style.display = 'none';
  Object.values(state.charts).forEach(c => c.destroy());
  state.charts = {};
}

async function loadMachineCharts(mId, minutes) {
  state.selectedMinutes = minutes;
  document.querySelectorAll('.time-range-bar button').forEach(b => {
    if (parseInt(b.getAttribute('data-min')) === minutes) {
      b.style.borderColor = 'var(--border-focus)';
      b.style.fontWeight = '700';
    } else {
      b.style.borderColor = 'var(--border-subtle)';
      b.style.fontWeight = 'normal';
    }
  });

  const url = `/api/v1/dashboard/machine/${mId}/series?minutes=${minutes}&step=${minutes > 15 ? 10 : 5}`;
  try {
    const res = await fetch(url, { headers: getAuthHeaders() });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderChartsGrid(data);
  } catch (err) {
    console.error('Failed to load machine series:', err);
  }
}

function renderChartsGrid(seriesData) {
  const container = document.getElementById('chartsGrid');
  Object.values(state.charts).forEach(c => c.destroy());
  state.charts = {};
  container.innerHTML = '';

  // Collect agent action markers
  const agentTimeline = seriesData.agent_timeline || [];

  const sKeys = Object.keys(seriesData.series);
  sKeys.forEach(key => {
    const s = seriesData.series[key];
    const card = document.createElement('div');
    card.className = 'chart-card';

    let markerInfoHtml = '';
    if (agentTimeline.length > 0) {
      markerInfoHtml = `<div style="font-size:0.7rem; color:var(--text-muted); margin-bottom:4px;">📍 Mốc can thiệp: ${agentTimeline.map(m => m.label).join(' | ')}</div>`;
    }

    card.innerHTML = `
      <div class="chart-title">${s.label} (${s.unit})</div>
      ${markerInfoHtml}
      <div style="position:relative; height:220px;">
        <canvas id="chart_${key}"></canvas>
      </div>
    `;
    container.appendChild(card);

    const labels = s.points.map(p => formatTime(p.time));
    const values = s.points.map(p => p.value);

    const ctx = document.getElementById(`chart_${key}`).getContext('2d');
    const datasets = [{
      label: s.label,
      data: values,
      borderColor: '#3b82f6',
      backgroundColor: 'rgba(59, 130, 246, 0.1)',
      borderWidth: 2,
      pointRadius: values.length > 50 ? 0 : 2,
      fill: true,
      tension: 0.2,
    }];

    if (s.warn !== null) {
      datasets.push({
        label: `Cảnh báo (${s.warn})`,
        data: Array(values.length).fill(s.warn),
        borderColor: '#f59e0b',
        borderWidth: 1.5,
        borderDash: [4, 4],
        pointRadius: 0,
        fill: false,
      });
    }

    if (s.critical !== null) {
      datasets.push({
        label: `Nguy hiểm (${s.critical})`,
        data: Array(values.length).fill(s.critical),
        borderColor: '#ef4444',
        borderWidth: 1.5,
        borderDash: [6, 4],
        pointRadius: 0,
        fill: false,
      });
    }

    state.charts[key] = new Chart(ctx, {
      type: 'line',
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        scales: {
          x: {
            grid: { color: 'rgba(255,255,255,0.05)' },
            ticks: { color: '#94a3b8', maxTicksLimit: 6 },
          },
          y: {
            grid: { color: 'rgba(255,255,255,0.05)' },
            ticks: { color: '#94a3b8' },
          },
        },
        plugins: {
          legend: {
            labels: { color: '#94a3b8', boxWidth: 12, font: { size: 10 } }
          },
          tooltip: {
            mode: 'index',
            intersect: false,
          }
        }
      }
    });
  });
}

function showOfflineBanner() {
  document.getElementById('offlineBanner').style.display = 'block';
  document.getElementById('connectionStatusPill').innerHTML = `<span class="dot-offline"></span> MẤT KẾT NỐI (Thử lại...)`;
}

function hideOfflineBanner() {
  document.getElementById('offlineBanner').style.display = 'none';
}

// Heartbeat watchdog: check if last server message > 30s
setInterval(() => {
  if (Date.now() - state.lastServerMessageTime > 30000) {
    showOfflineBanner();
  }
}, 5000);

// Hash Route Watcher
window.addEventListener('hashchange', () => {
  const hash = window.location.hash;
  if (hash.startsWith('#/machine/')) {
    const mId = hash.replace('#/machine/', '');
    if (mId && state.activeMachineId !== mId) {
      openMachineDetail(mId);
    }
  } else if (!hash && state.activeMachineId) {
    closeMachineDetail();
  }
});

// Theme Toggle
function toggleTheme() {
  state.theme = state.theme === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', state.theme);
  localStorage.setItem('denso_theme', state.theme);
}

// Initial Boot
window.addEventListener('DOMContentLoaded', () => {
  connectSSE();
  fetchEvents();
  fetchAgentStatus();

  // Check initial hash
  if (window.location.hash.startsWith('#/machine/')) {
    const mId = window.location.hash.replace('#/machine/', '');
    openMachineDetail(mId);
  }
});
