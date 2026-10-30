import { useCallback, useEffect, useMemo, useState } from "react";
import axios from "axios";
import { AnimatePresence, motion } from "framer-motion";
import {
  Activity, AlertOctagon, AlertTriangle, ArrowRight, ArrowUpRight, BarChart3,
  Bell, Check, CheckCircle2, ChevronDown, CircleHelp, Clock3, Command, Cpu, Database,
  Download, ExternalLink, Filter, Gauge, Layers3, ListFilter, LockKeyhole, MoreHorizontal,
  Network, Package, Pause, Play, Plus, Radio, Search,
  Settings2, Shield, ShieldAlert, ShieldCheck, Sparkles, Terminal, Truck, X,
} from "lucide-react";
import {
  Area, AreaChart, CartesianGrid, Cell, Line, LineChart, Pie, PieChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";

const api = axios.create({ baseURL: "/api", timeout: 10000 });

type Metric = { total_orders: number; completed_orders: number; failed_orders: number; delayed_orders: number; rejected_orders: number; api_error_rate: number; auto_recovered: number; pending_approvals: number; success_rate: number };
type Incident = { incident_id: string; order_id: string; category: string; service: string; severity: string; status: string; cause: string; recommendation: string; evidence: string[]; confidence: number; created_at: string };
type Order = { order_id: string; customer_id: string; order_type: string; status: string; stage: string; priority: string; failure_reason?: string; resolution_status: string; created_at: string; value: number; correlation_id: string };
type Health = { name: string; status: string; latency?: number; uptime?: number };
type Dashboard = { metrics: Metric; processing_overview: { label: string; success: number; failed: number; delayed: number }[]; failure_distribution: { name: string; value: number; color: string }[]; service_health: Health[]; recent_incidents: Incident[] };
type NavItem = { label: string; icon: typeof Activity; section?: string };

const nav: NavItem[] = [
  { section: "WORKSPACE", label: "Overview", icon: Gauge },
  { label: "Order monitoring", icon: Package },
  { label: "API monitoring", icon: Network },
  { label: "Failure detection", icon: ShieldAlert },
  { section: "INTELLIGENCE", label: "Root cause analysis", icon: Sparkles },
  { label: "Resolution center", icon: ShieldCheck },
  { label: "Service health", icon: Activity },
  { label: "Analytics & reports", icon: BarChart3 },
  { section: "SYSTEM", label: "Audit logs", icon: Terminal },
  { label: "Settings", icon: Settings2 },
];

const fmtTime = (date: string) => new Date(date).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const human = (value: string) => value.toLowerCase().replace(/_/g, " ").replace(/\b\w/g, (c: string) => c.toUpperCase());
const errorMessage = (error: unknown) => axios.isAxiosError(error) ? (error.response?.data?.detail ?? error.message) : "Something went wrong";

function App() {
  const [page, setPage] = useState("Overview");
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [orders, setOrders] = useState<Order[]>([]);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [logs, setLogs] = useState<Record<string, unknown>[]>([]);
  const [auditLogs, setAuditLogs] = useState<Record<string, unknown>[]>([]);
  const [simulationRunning, setSimulationRunning] = useState(false);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("All statuses");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [selectedIncident, setSelectedIncident] = useState<Incident | null>(null);
  const [selectedOrder, setSelectedOrder] = useState<Order | null>(null);
  const [timeline, setTimeline] = useState<Record<string, string>[]>([]);
  const [analytics, setAnalytics] = useState<Record<string, unknown>>({});

  const refresh = useCallback(async () => {
    try {
      const [overview, orderData, incidentData, logData, auditData, simStatus, analyticsData] = await Promise.all([
        api.get<Dashboard>("/dashboard/overview"), api.get("/orders?limit=100"),
        api.get<Incident[]>("/monitoring/incidents"), api.get("/monitoring/api-logs?limit=100"),
        api.get("/audit-logs?limit=100"), api.get("/simulation/status"), api.get("/analytics/overview"),
      ]);
      setDashboard(overview.data);
      setOrders(orderData.data.items);
      setIncidents(incidentData.data);
      setLogs(logData.data);
      setAuditLogs(auditData.data);
      setSimulationRunning(simStatus.data.running);
      setAnalytics(analyticsData.data);
    } catch (error) {
      setNotice(`API unavailable: ${errorMessage(error)}. Start the backend to connect.`);
    }
  }, []);

  useEffect(() => { void refresh(); const timer = window.setInterval(() => void refresh(), 12000); return () => window.clearInterval(timer); }, [refresh]);
  useEffect(() => {
    const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${scheme}//${window.location.host}/ws`);
    socket.onmessage = () => void refresh();
    return () => socket.close();
  }, [refresh]);
  useEffect(() => { if (!notice) return; const timer = window.setTimeout(() => setNotice(""), 5000); return () => window.clearTimeout(timer); }, [notice]);

  const action = async (label: string, operation: () => Promise<unknown>) => {
    setBusy(true);
    try { await operation(); setNotice(label); await refresh(); }
    catch (error) { setNotice(errorMessage(error)); }
    finally { setBusy(false); }
  };

  const toggleSimulation = () => action(simulationRunning ? "Simulation paused" : "Simulation running — new orders arrive every 7 seconds", () =>
    api.post(simulationRunning ? "/simulation/pause" : "/simulation/start"));

  const generate = (count: number) => action(`${count} synthetic orders generated`, () => api.post("/simulation/generate", { count }));
  const inject = (category: string) => action(`${human(category)} injected into the simulation`, () =>
    api.post("/simulation/inject-failure", { category, service: category === "API_ERROR" ? "Provisioning" : category === "ORDER_DELAY" ? "Logistics" : "Inventory" }));

  const openOrder = async (order: Order) => {
    setSelectedOrder(order);
    try { const result = await api.get(`/orders/${order.order_id}/timeline`); setTimeline(result.data); }
    catch (error) { setNotice(errorMessage(error)); }
  };

  const performResolution = (incident: Incident, actionName: string) => action(
    actionName === "approve" ? "Resolution approved and executed" : `Incident ${actionName}d`,
    () => api.post(`/resolutions/${incident.incident_id}/${actionName}`),
  );

  const filteredOrders = useMemo(() => orders.filter((order) => {
    const matchesText = `${order.order_id} ${order.customer_id}`.toLowerCase().includes(search.toLowerCase());
    const matchesStatus = statusFilter === "All statuses" || order.status === statusFilter;
    return matchesText && matchesStatus;
  }), [orders, search, statusFilter]);

  const currentTitle = page;
  const metric = dashboard?.metrics;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><Activity size={21} strokeWidth={2.5} /></div>
          <div><div className="brand-name">Astra<span>X</span></div><div className="brand-caption">INTELLIGENT OPERATIONS</div></div>
          <button className="icon-btn sidebar-collapse" aria-label="Collapse sidebar"><Command size={15} /></button>
        </div>
        <div className="workspace-switch"><div className="workspace-avatar">N</div><div className="workspace-copy"><strong>Northstar Telecom</strong><small>Enterprise workspace</small></div><ChevronDown size={15} /></div>
        <nav className="main-nav">
          {nav.map((item) => <div key={item.label}>
            {item.section && <div className="nav-section">{item.section}</div>}
            <button className={`nav-item ${page === item.label ? "active" : ""}`} onClick={() => setPage(item.label)}>
              <item.icon size={17} strokeWidth={1.8} /><span>{item.label}</span>
              {item.label === "Resolution center" && (metric?.pending_approvals ?? 0) > 0 && <span className="nav-count">{metric?.pending_approvals}</span>}
              {item.label === "Overview" && <span className="nav-indicator" />}
            </button>
          </div>)}
        </nav>
        <div className="sidebar-bottom">
          <div className="plan-card">
            <div className="plan-icon"><Sparkles size={16} /></div>
            <div className="plan-title">AstraX intelligence <span>ACTIVE</span></div>
            <p>Self-healing systems are monitoring your order flow.</p>
            <div className="plan-meter"><i /></div><div className="plan-meta"><span>Monthly events</span><strong>{(metric?.total_orders ?? 0).toLocaleString()} / 10k</strong></div>
          </div>
          <button className="profile-row"><div className="profile-avatar">SK</div><div className="profile-copy"><strong>Selva Kumar</strong><small>Platform admin</small></div><MoreHorizontal size={17} /></button>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div className="breadcrumbs"><span>Workspace</span><span className="crumb-slash">/</span><strong>{currentTitle}</strong></div>
          <div className="topbar-right">
            <div className="live-pill"><span /> LIVE SYSTEM</div>
            <button className="icon-btn notification-btn" aria-label="Notifications"><Bell size={17} /><i /></button>
            <div className="top-divider" />
            <div className="top-profile">SK</div>
            <button className="top-chevron" aria-label="Profile menu"><ChevronDown size={14} /></button>
          </div>
        </header>
        <div className="content">
          <AnimatePresence mode="wait">
            <motion.div key={page} initial={{ opacity: 0, y: 7 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={{ duration: 0.18 }}>
              {page === "Overview" && <Overview dashboard={dashboard} orders={orders} incidents={incidents} onNavigate={setPage} onOpenIncident={setSelectedIncident} onOpenOrder={openOrder} simulationRunning={simulationRunning} onToggleSimulation={toggleSimulation} onGenerate={generate} onInject={inject} busy={busy} />}
              {page === "Order monitoring" && <OrdersPage orders={filteredOrders} search={search} setSearch={setSearch} status={statusFilter} setStatus={setStatusFilter} onOpen={openOrder} onGenerate={generate} busy={busy} />}
              {page === "API monitoring" && <ApiMonitoring logs={logs} />}
              {page === "Failure detection" && <IncidentsPage incidents={incidents} onOpen={setSelectedIncident} />}
              {page === "Root cause analysis" && <RootCausePage incidents={incidents} onOpen={setSelectedIncident} />}
              {page === "Resolution center" && <ResolutionPage incidents={incidents} onResolve={performResolution} busy={busy} onOpen={setSelectedIncident} />}
              {page === "Service health" && <ServicePage services={dashboard?.service_health ?? []} />}
              {page === "Analytics & reports" && <AnalyticsPage analytics={analytics} dashboard={dashboard} />}
              {page === "Audit logs" && <AuditPage rows={auditLogs} />}
              {page === "Settings" && <SettingsPage simulationRunning={simulationRunning} onToggleSimulation={toggleSimulation} onGenerate={generate} onInject={inject} busy={busy} />}
            </motion.div>
          </AnimatePresence>
          <footer className="footer"><span><span className="footer-dot" /> All systems operational</span><span>AstraX <b>·</b> v1.0.0 <b>·</b> Local simulation</span></footer>
        </div>
      </main>

      {notice && <motion.div className="toast" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}><CheckCircle2 size={17} />{notice}<button onClick={() => setNotice("")}><X size={14} /></button></motion.div>}
      {selectedIncident && <IncidentModal incident={selectedIncident} onClose={() => setSelectedIncident(null)} onAction={(actionName) => { setSelectedIncident(null); void performResolution(selectedIncident, actionName); }} />}
      {selectedOrder && <OrderModal order={selectedOrder} timeline={timeline} onClose={() => setSelectedOrder(null)} />}
    </div>
  );
}

function PageHeading({ eyebrow, title, description, actions }: { eyebrow: string; title: string; description: string; actions?: React.ReactNode }) {
  return <div className="page-heading"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{description}</p></div>{actions && <div className="heading-actions">{actions}</div>}</div>;
}

function Overview({ dashboard, orders, incidents, onNavigate, onOpenIncident, onOpenOrder, simulationRunning, onToggleSimulation, onGenerate, onInject, busy }: {
  dashboard: Dashboard | null; orders: Order[]; incidents: Incident[]; onNavigate: (page: string) => void; onOpenIncident: (incident: Incident) => void; onOpenOrder: (order: Order) => void;
  simulationRunning: boolean; onToggleSimulation: () => void; onGenerate: (count: number) => void; onInject: (category: string) => void; busy: boolean;
}) {
  const m = dashboard?.metrics;
  const metrics = [
    { label: "Orders processed", value: m?.total_orders ?? "—", change: "all time", icon: Package, tone: "cyan", trend: "up" },
    { label: "Successful orders", value: m?.completed_orders ?? "—", change: `${m?.success_rate ?? 0}% completion`, icon: CheckCircle2, tone: "green", trend: "up" },
    { label: "Active incidents", value: incidents.filter((i) => i.status !== "resolved").length, change: `${m?.pending_approvals ?? 0} need approval`, icon: AlertTriangle, tone: "amber", trend: "down" },
    { label: "Auto-recovered", value: m?.auto_recovered ?? "—", change: "bounded retries", icon: ShieldCheck, tone: "purple", trend: "up" },
  ];
  return <>
    <PageHeading eyebrow="MONITORING OVERVIEW" title="Good evening, Selva" description="Here’s what’s happening across your order ecosystem." actions={<><button className={`button ${simulationRunning ? "button-stop" : "button-primary"}`} onClick={onToggleSimulation}><span className="button-icon">{simulationRunning ? <Pause size={15} /> : <Play size={15} />}</span>{simulationRunning ? "Pause simulation" : "Start simulation"}</button><button className="button button-outline" onClick={() => onGenerate(10)} disabled={busy}><Plus size={16} /> Generate orders</button></>} />
    <div className="welcome-strip"><div className="welcome-icon"><Sparkles size={19} /></div><div><strong>Intelligent Monitoring. Autonomous Recovery.</strong><span>AstraX is watching your services and safely recovering transient failures.</span></div><div className="welcome-live"><span /> {simulationRunning ? "SIMULATION ACTIVE" : "MONITORING READY"}</div><button onClick={() => onNavigate("Resolution center")}>View resolution queue <ArrowRight size={14} /></button></div>
    <div className="metrics-grid">
      {metrics.map((item, index) => <motion.div className="metric-card" key={item.label} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.05 }}>
        <div className="metric-top"><span>{item.label}</span><div className={`metric-icon ${item.tone}`}><item.icon size={16} /></div></div>
        <div className="metric-value">{typeof item.value === "number" ? item.value.toLocaleString() : item.value}</div>
        <div className="metric-bottom"><span className="metric-change"><ArrowUpRight size={13} /> {item.change}</span><span className="metric-period">vs. all time</span></div>
      </motion.div>)}
    </div>
    <div className="dashboard-grid">
      <section className="panel chart-panel processing-panel">
        <div className="panel-heading"><div><div className="panel-title">Order processing</div><div className="panel-subtitle">Volume and outcomes over the last 7 days</div></div><button className="select-button">Last 7 days <ChevronDown size={13} /></button></div>
        <div className="chart-legend"><span><i className="legend-dot green-dot" /> Successful</span><span><i className="legend-dot purple-dot" /> Failed</span><span><i className="legend-dot orange-dot" /> Delayed</span></div>
        <div className="line-chart"><ResponsiveContainer width="100%" height="100%"><AreaChart data={dashboard?.processing_overview ?? []} margin={{ top: 10, right: 12, left: -24, bottom: 0 }}>
          <defs><linearGradient id="successFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#46d9ad" stopOpacity={0.17} /><stop offset="100%" stopColor="#46d9ad" stopOpacity={0} /></linearGradient></defs>
          <CartesianGrid stroke="#e8ebf3" strokeDasharray="3 5" vertical={false} /><XAxis dataKey="label" axisLine={false} tickLine={false} tick={{ fill: "#778196", fontSize: 11 }} dy={10} /><YAxis axisLine={false} tickLine={false} tick={{ fill: "#778196", fontSize: 11 }} /><Tooltip contentStyle={{ background: "#ffffff", border: "1px solid #e3e7f0", borderRadius: 9, color: "#202944", boxShadow: "0 8px 24px #29345a1a" }} />
          <Area type="monotone" dataKey="success" stroke="#46d9ad" strokeWidth={2} fill="url(#successFill)" /><Line type="monotone" dataKey="failed" stroke="#9b8cff" strokeWidth={2} dot={false} /><Line type="monotone" dataKey="delayed" stroke="#f4a261" strokeWidth={2} dot={false} />
        </AreaChart></ResponsiveContainer></div>
        <div className="chart-footnote"><span><i className="tiny-pulse" /> Data refreshes every 12 seconds</span><span>{m?.total_orders.toLocaleString() ?? 0} total orders</span></div>
      </section>
      <section className="panel distribution-panel">
        <div className="panel-heading"><div><div className="panel-title">Failure distribution</div><div className="panel-subtitle">Detected incidents by category</div></div><button className="icon-btn small-icon" onClick={() => onNavigate("Failure detection")} aria-label="View incidents"><MoreHorizontal size={17} /></button></div>
        <div className="donut-wrap"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={dashboard?.failure_distribution ?? []} dataKey="value" nameKey="name" innerRadius={66} outerRadius={87} paddingAngle={4} stroke="none"><Cell fill="#27abc0" /><Cell fill="#7869e8" /><Cell fill="#d95a91" /></Pie><Tooltip contentStyle={{ background: "#ffffff", border: "1px solid #e3e7f0", borderRadius: 8, color: "#202944", boxShadow: "0 8px 24px #29345a1a" }} /></PieChart></ResponsiveContainer><div className="donut-label"><strong>{incidents.length}</strong><span>incidents</span></div></div>
        <div className="distribution-legend">{(dashboard?.failure_distribution ?? []).map((item) => <div key={item.name}><span><i style={{ background: item.color }} />{item.name}</span><strong>{item.value}</strong></div>)}</div>
        <button className="text-link" onClick={() => onNavigate("Failure detection")}>Explore all failures <ArrowRight size={14} /></button>
      </section>
    </div>
    <div className="dashboard-grid second-row">
      <section className="panel service-panel">
        <div className="panel-heading"><div><div className="panel-title">Service health</div><div className="panel-subtitle">Live status across your infrastructure</div></div><button className="text-link" onClick={() => onNavigate("Service health")}>View all <ArrowRight size={13} /></button></div>
        <div className="service-list">{(dashboard?.service_health ?? []).slice(0, 5).map((service) => <div className="service-row" key={service.name}><div className={`service-avatar ${service.name.split(" ")[0].toLowerCase()}`}>{serviceIcon(service.name)}</div><div className="service-name">{service.name}<small>{service.latency} ms avg latency</small></div><span className={`status-tag ${service.status}`}>{service.status}</span><span className="service-uptime">{service.uptime}%</span><MoreHorizontal className="service-more" size={16} /></div>)}</div>
      </section>
      <section className="panel incident-panel">
        <div className="panel-heading"><div><div className="panel-title">Recent incidents</div><div className="panel-subtitle">Latest events requiring attention</div></div><button className="icon-btn small-icon" onClick={() => onNavigate("Failure detection")} aria-label="More incidents"><MoreHorizontal size={17} /></button></div>
        <div className="incident-list">{incidents.slice(0, 5).map((incident) => <button className="incident-row" key={incident.incident_id} onClick={() => onOpenIncident(incident)}><span className={`incident-symbol ${incident.category.toLowerCase()}`}>{incident.category === "API_ERROR" ? <Network size={14} /> : incident.category === "ORDER_DELAY" ? <Clock3 size={14} /> : <Package size={14} />}</span><span className="incident-summary"><strong>{incident.order_id}</strong><small>{human(incident.category)} · {incident.service}</small></span><span className={`severity ${incident.severity}`}>{incident.severity}</span><span className={`resolution-status ${incident.status}`}>{human(incident.status)}</span><span className="incident-time">{fmtTime(incident.created_at)}</span></button>)}</div>
        {incidents.length === 0 && <div className="empty-mini"><ShieldCheck size={18} /> No incidents detected. Your order flow is clear.</div>}
        <button className="text-link incident-link" onClick={() => onNavigate("Resolution center")}>Open resolution center <ArrowRight size={14} /></button>
      </section>
    </div>
    <section className="panel simulation-panel">
      <div className="sim-intro"><div className="sim-symbol"><Radio size={18} /></div><div><div className="panel-title">Simulation controls</div><div className="panel-subtitle">Safely test failure detection and recovery with synthetic orders</div></div></div>
      <div className="sim-buttons"><button className="button button-subtle" onClick={() => onGenerate(10)} disabled={busy}><Plus size={15} /> 10 orders</button><button className="button button-subtle" onClick={() => onGenerate(50)} disabled={busy}><Layers3 size={15} /> 50 orders</button><span className="sim-separator" /><button className="button button-fault" onClick={() => onInject("API_ERROR")} disabled={busy}><Network size={14} /> Inject API failure</button><button className="button button-fault" onClick={() => onInject("ORDER_DELAY")} disabled={busy}><Clock3 size={14} /> Inject delay</button><button className="button button-fault" onClick={() => onInject("ORDER_REJECTION")} disabled={busy}><AlertOctagon size={14} /> Inject rejection</button></div>
    </section>
    <section className="panel orders-preview">
      <div className="panel-heading"><div><div className="panel-title">Latest orders</div><div className="panel-subtitle">The most recent activity in your order pipeline</div></div><button className="text-link" onClick={() => onNavigate("Order monitoring")}>All orders <ArrowRight size={13} /></button></div>
      <OrderTable orders={orders.slice(0, 5)} onOpen={onOpenOrder} />
    </section>
  </>;
}

function serviceIcon(name: string) {
  if (name.includes("Inventory")) return <Database size={16} />;
  if (name.includes("Payment")) return <LockKeyhole size={16} />;
  if (name.includes("Logistics")) return <Truck size={16} />;
  if (name.includes("Provision")) return <Cpu size={16} />;
  if (name.includes("Notification")) return <Bell size={16} />;
  return <Package size={16} />;
}

function OrdersPage({ orders, search, setSearch, status, setStatus, onOpen, onGenerate, busy }: { orders: Order[]; search: string; setSearch: (v: string) => void; status: string; setStatus: (v: string) => void; onOpen: (order: Order) => void; onGenerate: (count: number) => void; busy: boolean }) {
  return <><PageHeading eyebrow="ORDER OPERATIONS" title="Order monitoring" description="Track every order from creation through delivery and recovery." actions={<button className="button button-primary" onClick={() => onGenerate(10)} disabled={busy}><Plus size={16} /> Generate orders</button>} />
    <div className="table-toolbar"><div className="searchbox"><Search size={16} /><input placeholder="Search order or customer ID..." value={search} onChange={(e) => setSearch(e.target.value)} /><kbd>⌘ K</kbd></div><div className="toolbar-right"><div className="filter-select"><Filter size={15} /><select value={status} onChange={(e) => setStatus(e.target.value)}><option>All statuses</option>{["Completed", "Processing", "Failed", "Delayed", "Rejected"].map((item) => <option key={item}>{item}</option>)}</select><ChevronDown size={13} /></div><button className="button button-outline" onClick={() => window.open("/api/orders.csv", "_blank")}><Download size={15} /> Export CSV</button></div></div>
    <div className="panel data-panel"><OrderTable orders={orders} onOpen={onOpen} /></div><div className="results-note">Showing {orders.length} orders · Synthetic customer data only</div></>;
}

function OrderTable({ orders, onOpen }: { orders: Order[]; onOpen: (order: Order) => void }) {
  if (!orders.length) return <div className="empty-state"><Package size={22} /><strong>No orders found</strong><span>Generate synthetic orders or adjust your filters.</span></div>;
  return <div className="table-scroll"><table className="data-table"><thead><tr><th>ORDER ID</th><th>CUSTOMER</th><th>TYPE</th><th>STAGE</th><th>STATUS</th><th>PRIORITY</th><th>CREATED</th><th>VALUE</th><th /></tr></thead><tbody>{orders.map((order) => <tr key={order.order_id} onClick={() => onOpen(order)} className="click-row"><td><strong className="mono">{order.order_id}</strong></td><td>{order.customer_id}</td><td>{order.order_type}</td><td>{order.stage}</td><td><span className={`order-status ${order.status.toLowerCase()}`}><i />{order.status}</span></td><td><span className={`priority ${order.priority.toLowerCase()}`}>{order.priority}</span></td><td>{fmtTime(order.created_at)}</td><td>${order.value.toFixed(2)}</td><td><MoreHorizontal size={17} /></td></tr>)}</tbody></table></div>;
}

function ApiMonitoring({ logs }: { logs: Record<string, unknown>[] }) {
  const good = logs.filter((log) => Number(log.status_code) < 400).length;
  const avg = Math.round(logs.reduce((sum, log) => sum + Number(log.response_ms), 0) / Math.max(logs.length, 1));
  return <><PageHeading eyebrow="TELEMETRY" title="API monitoring" description="Inspect request health, latency, and service-to-service communication." actions={<div className="live-pill"><span /> STREAMING</div>} />
    <div className="stat-strip"><SmallStat label="Requests captured" value={logs.length} icon={Network} /><SmallStat label="Healthy responses" value={`${Math.round(good / Math.max(logs.length, 1) * 100)}%`} icon={CheckCircle2} /><SmallStat label="Avg. response time" value={`${avg} ms`} icon={Clock3} /><SmallStat label="Error responses" value={logs.length - good} icon={AlertTriangle} /></div>
    <div className="panel data-panel"><div className="panel-heading in-panel"><div><div className="panel-title">Recent API requests</div><div className="panel-subtitle">Live telemetry from simulated microservices</div></div><button className="select-button"><ListFilter size={14} /> All responses <ChevronDown size={13} /></button></div>
      {!logs.length ? <EmptyState label="API requests appear as synthetic orders are processed." /> : <div className="table-scroll"><table className="data-table"><thead><tr><th>REQUEST</th><th>ORDER ID</th><th>SOURCE → DESTINATION</th><th>ENDPOINT</th><th>STATUS</th><th>LATENCY</th><th>RETRIES</th><th>TIME</th></tr></thead><tbody>{logs.map((row) => <tr key={String(row.request_id)}><td className="mono">{String(row.request_id)}</td><td className="mono">{String(row.order_id)}</td><td>{String(row.source)} <ArrowRight size={12} /> {String(row.destination)}</td><td className="mono">{String(row.endpoint)}</td><td><span className={`http-code ${Number(row.status_code) < 400 ? "good" : "bad"}`}>{String(row.status_code)}</span></td><td>{String(row.response_ms)} ms</td><td>{String(row.retry_count)}</td><td>{fmtTime(String(row.timestamp))}</td></tr>)}</tbody></table></div>}</div>
  </>;
}

function SmallStat({ label, value, icon: Icon }: { label: string; value: string | number; icon: typeof Activity }) { return <div className="small-stat"><div className="small-stat-icon"><Icon size={16} /></div><span>{label}</span><strong>{value}</strong></div>; }
function EmptyState({ label }: { label: string }) { return <div className="empty-state"><Activity size={22} /><strong>Nothing to show yet</strong><span>{label}</span></div>; }

function IncidentsPage({ incidents, onOpen }: { incidents: Incident[]; onOpen: (incident: Incident) => void }) {
  return <><PageHeading eyebrow="DETECTION ENGINE" title="Failure detection" description="Every anomaly is classified, correlated, and recorded with evidence." actions={<div className="live-pill"><span /> RULE ENGINE ACTIVE</div>} />
    <div className="stat-strip"><SmallStat label="Detected incidents" value={incidents.length} icon={ShieldAlert} /><SmallStat label="API errors" value={incidents.filter((i) => i.category === "API_ERROR").length} icon={Network} /><SmallStat label="Order delays" value={incidents.filter((i) => i.category === "ORDER_DELAY").length} icon={Clock3} /><SmallStat label="Rejections" value={incidents.filter((i) => i.category === "ORDER_REJECTION").length} icon={Package} /></div>
    <IncidentTable incidents={incidents} onOpen={onOpen} /></>;
}

function IncidentTable({ incidents, onOpen }: { incidents: Incident[]; onOpen: (incident: Incident) => void }) {
  return <div className="panel data-panel">{incidents.length ? <div className="table-scroll"><table className="data-table"><thead><tr><th>INCIDENT</th><th>ORDER</th><th>CATEGORY</th><th>SERVICE</th><th>SEVERITY</th><th>CONFIDENCE</th><th>STATUS</th><th>DETECTED</th><th /></tr></thead><tbody>{incidents.map((i) => <tr key={i.incident_id} className="click-row" onClick={() => onOpen(i)}><td className="mono">{i.incident_id}</td><td className="mono">{i.order_id}</td><td>{human(i.category)}</td><td>{i.service}</td><td><span className={`severity ${i.severity}`}>{i.severity}</span></td><td><Confidence value={i.confidence} /></td><td><span className={`resolution-status ${i.status}`}>{human(i.status)}</span></td><td>{fmtTime(i.created_at)}</td><td><ArrowRight size={15} /></td></tr>)}</tbody></table></div> : <EmptyState label="Inject an API failure, delay, or rejection to exercise detection." />}</div>;
}

function Confidence({ value }: { value: number }) { return <span className="confidence"><span><i style={{ width: `${Math.min(value * 100, 100)}%` }} /></span>{Math.round(value * 100)}%</span>; }

function RootCausePage({ incidents, onOpen }: { incidents: Incident[]; onOpen: (incident: Incident) => void }) {
  const latest = incidents[0];
  return <><PageHeading eyebrow="SENTINEL INTELLIGENCE" title="Root cause analysis" description="Evidence-first explanations correlated from synthetic service events." />
    {latest ? <div className="rca-layout"><div className="panel rca-main"><div className="rca-header"><div className="rca-icon"><Sparkles size={19} /></div><div><div className="eyebrow">LATEST ANALYSIS · {latest.incident_id}</div><h2>{latest.order_id}</h2></div><span className="analysis-badge"><span /> RULE-BASED ANALYSIS</span></div>
      <div className="rca-block"><div className="block-heading"><div className="block-icon cause"><AlertTriangle size={15} /></div><strong>Probable root cause</strong></div><p>{latest.cause}</p></div>
      <div className="rca-block"><div className="block-heading"><div className="block-icon evidence"><Search size={15} /></div><strong>Correlated evidence</strong><span className="evidence-count">{latest.evidence.length} signals</span></div><div className="evidence-list">{latest.evidence.map((e, n) => <div key={e}><span className="evidence-number">0{n + 1}</span><span>{e}</span><Check size={14} /></div>)}</div></div>
      <div className="recommendation"><div><Sparkles size={16} /><strong>Recommended resolution</strong></div><p>{latest.recommendation}</p></div>
      <div className="rca-footer"><span>Analysis method: deterministic service-event rules · not an ML prediction</span><button className="button button-outline" onClick={() => onOpen(latest)}>Inspect incident <ArrowRight size={14} /></button></div>
    </div><aside className="rca-aside"><div className="panel rca-score"><div className="panel-title">Analysis confidence</div><div className="score-gauge"><div><strong>{Math.round(latest.confidence * 100)}<small>%</small></strong><span>confidence</span></div></div><p>Confidence is derived from correlated deterministic signals. It is not a trained ML model output.</p><div className="score-meta"><span>Evidence matches</span><strong>{latest.evidence.length} / {latest.evidence.length}</strong></div><div className="score-meta"><span>Services correlated</span><strong>1 service</strong></div></div>
      <div className="panel affected-panel"><div className="panel-title">Affected service</div><div className="affected-service"><span className={`service-avatar ${latest.service.split(" ")[0].toLowerCase()}`}>{serviceIcon(latest.service)}</span><div><strong>{latest.service}</strong><span className="service-failing"><i /> Failure detected</span></div></div><div className="correlation-line"><span /> Order ID <strong>{latest.order_id}</strong></div></div></aside></div> : <div className="panel"><EmptyState label="No root cause records yet. Generate an order with an injected failure." /></div>}
    <div className="section-title-row"><div><h2>Analysis history</h2><p>Past detected failures with auditable evidence.</p></div></div><IncidentTable incidents={incidents} onOpen={onOpen} /></>;
}

function ResolutionPage({ incidents, onResolve, busy, onOpen }: { incidents: Incident[]; onResolve: (incident: Incident, action: string) => void; busy: boolean; onOpen: (incident: Incident) => void }) {
  const actionable = incidents.filter((i) => i.status !== "resolved" && i.status !== "rejected");
  return <><PageHeading eyebrow="HUMAN-IN-THE-LOOP" title="Resolution center" description="Review proposed recovery actions. High-risk business decisions stay with your operators." actions={<div className="approval-summary"><div className="approval-icon"><Shield size={17} /></div><div><strong>{actionable.length} open</strong><span>incidents to review</span></div></div>} />
    <div className="safety-banner"><ShieldCheck size={17} /><span><strong>Safety policy active.</strong> Financial, inventory, and irreversible actions require explicit operator approval.</span><button><CircleHelp size={15} /></button></div>
    {!actionable.length ? <div className="panel"><EmptyState label="No incidents need attention. Inject a failure to test the resolution workflow." /></div> : <div className="resolution-cards">{actionable.map((incident) => <article className="panel resolution-card" key={incident.incident_id}>
      <div className="resolution-card-top"><div className={`incident-symbol ${incident.category.toLowerCase()}`}>{incident.category === "API_ERROR" ? <Network size={15} /> : incident.category === "ORDER_DELAY" ? <Clock3 size={15} /> : <Package size={15} />}</div><div className="resolution-order"><strong>{incident.order_id}</strong><span>{incident.incident_id} · {human(incident.category)}</span></div><span className={`severity ${incident.severity}`}>{incident.severity} risk</span><button className="icon-btn small-icon" onClick={() => onOpen(incident)} aria-label="View incident"><ExternalLink size={15} /></button></div>
      <div className="resolution-reason"><span>ROOT CAUSE</span><p>{incident.cause}</p></div><div className="resolution-proposal"><div className="proposal-icon"><Sparkles size={15} /></div><div><span>SENTINEL RECOMMENDS</span><p>{incident.recommendation}</p></div></div>
      <div className="resolution-card-footer"><div className="resolution-meta"><span>{incident.service}</span><span>·</span><Confidence value={incident.confidence} /></div><div className="resolution-actions"><button className="button button-outline button-small" onClick={() => onOpen(incident)}>Evidence</button><button className="button button-outline button-small" onClick={() => onResolve(incident, "escalate")} disabled={busy}>Escalate</button><button className="button button-danger-outline button-small" onClick={() => onResolve(incident, "reject")} disabled={busy}>Reject</button><button className="button button-approve button-small" onClick={() => onResolve(incident, "approve")} disabled={busy}><Check size={14} /> Approve</button></div></div>
    </article>)}</div>}</>;
}

function ServicePage({ services }: { services: Health[] }) {
  return <><PageHeading eyebrow="INFRASTRUCTURE" title="Service health" description="Real-time status of the services in the simulated order-processing network." actions={<div className="live-pill"><span /> HEALTH CHECKS ACTIVE</div>} /><div className="service-cards">{services.map((service) => <div className="panel service-card" key={service.name}><div className={`service-avatar large ${service.name.split(" ")[0].toLowerCase()}`}>{serviceIcon(service.name)}</div><span className={`status-tag ${service.status}`}>{service.status}</span><h3>{service.name}</h3><p>Order workflow microservice</p><div className="service-card-stats"><div><span>Latency</span><strong>{service.latency} <small>ms</small></strong></div><div><span>Uptime</span><strong>{service.uptime}%</strong></div></div><div className="uptime-track"><i style={{ width: `${service.uptime}%` }} /></div><div className="service-card-foot"><span><span className="footer-dot" /> Healthy responses</span><span>Last checked just now</span></div></div>)}</div>
    <div className="panel service-architecture"><div><div className="panel-title">Order flow topology</div><div className="panel-subtitle">Synthetic service-to-service workflow</div></div><div className="flow-map">{["Order Management", "Inventory", "Payment", "Provisioning", "Logistics", "Notification"].map((s, i) => <div className="flow-node-wrap" key={s}><div className="flow-node"><span className={`service-avatar ${s.split(" ")[0].toLowerCase()}`}>{serviceIcon(s)}</span><strong>{s}</strong><span className="node-status"><i /> Connected</span></div>{i < 5 && <ArrowRight className="flow-arrow" size={16} />}</div>)}</div></div>
  </>;
}

function AnalyticsPage({ analytics, dashboard }: { analytics: Record<string, unknown>; dashboard: Dashboard | null }) {
  const stats = [
    ["Completion rate", `${analytics.completion_percentage ?? 0}%`, "of all orders completed"],
    ["SLA compliance", `${analytics.sla_compliance ?? 0}%`, "within configured target"],
    ["Mean detection time", `${analytics.mttd_seconds ?? 0}s`, "average time to detect"],
    ["Recovered order value", `$${Number(analytics.estimated_recovered_value ?? 0).toLocaleString()}`, "synthetic order value"],
  ];
  return <><PageHeading eyebrow="PERFORMANCE INSIGHTS" title="Analytics & reports" description="Operational outcomes calculated from persisted order and incident records." actions={<button className="button button-outline" onClick={() => window.open("/api/orders.csv", "_blank")}><Download size={15} /> Download CSV</button>} />
    <div className="analytics-kpis">{stats.map(([label, value, hint]) => <div className="panel analytics-kpi" key={label}><span>{label}</span><strong>{value}</strong><small>{hint}</small></div>)}</div>
    <div className="dashboard-grid"><div className="panel chart-panel"><div className="panel-heading"><div><div className="panel-title">Processing outcomes</div><div className="panel-subtitle">Order volume by outcome · 7 days</div></div></div><div className="line-chart"><ResponsiveContainer width="100%" height="100%"><LineChart data={dashboard?.processing_overview ?? []} margin={{ top: 10, right: 12, left: -24, bottom: 0 }}><CartesianGrid stroke="#e8ebf3" strokeDasharray="3 5" vertical={false} /><XAxis dataKey="label" axisLine={false} tickLine={false} tick={{ fill: "#778196", fontSize: 11 }} /><YAxis axisLine={false} tickLine={false} tick={{ fill: "#778196", fontSize: 11 }} /><Tooltip contentStyle={{ background: "#ffffff", border: "1px solid #e3e7f0", borderRadius: 9, color: "#202944", boxShadow: "0 8px 24px #29345a1a" }} /><Line type="monotone" dataKey="success" stroke="#21a67a" strokeWidth={2} /><Line type="monotone" dataKey="failed" stroke="#7868e8" strokeWidth={2} /><Line type="monotone" dataKey="delayed" stroke="#e78b45" strokeWidth={2} /></LineChart></ResponsiveContainer></div></div>
      <div className="panel analytics-summary"><div className="panel-title">Recovery outcomes</div><div className="recovery-stat"><strong>{String(analytics.auto_recovered ?? 0)}</strong><span>Auto-recovered orders</span><ShieldCheck size={18} /></div><div className="summary-rule" /><div className="summary-line"><span>Manual interventions</span><strong>{String(analytics.manual_interventions ?? 0)}</strong></div><div className="summary-line"><span>API failure rate</span><strong>{String(analytics.api_failure_percentage ?? 0)}%</strong></div><div className="summary-line"><span>Mean resolution time</span><strong>{String(analytics.mttr_seconds ?? 0)}s</strong></div><div className="summary-line"><span>Orders rejected</span><strong>{String(analytics.rejected_orders ?? 0)}</strong></div></div></div>
    <div className="notice-muted"><Activity size={15} /> Metrics reflect the persisted local simulation. Values are synthetic and are not production telemetry.</div>
  </>;
}

function AuditPage({ rows }: { rows: Record<string, unknown>[] }) {
  return <><PageHeading eyebrow="GOVERNANCE" title="Audit logs" description="Append-only application history for simulation, detection, and operator actions." actions={<span className="audit-seal"><LockKeyhole size={14} /> APPEND-ONLY RECORDS</span>} />
    <div className="panel data-panel"><div className="panel-heading in-panel"><div><div className="panel-title">Activity history</div><div className="panel-subtitle">{rows.length} recorded events · newest first</div></div><button className="select-button"><Filter size={14} /> All events <ChevronDown size={13} /></button></div>
      {!rows.length ? <EmptyState label="Audit entries are created as simulation and resolution actions occur." /> : <div className="table-scroll"><table className="data-table"><thead><tr><th>EVENT ID</th><th>ACTOR</th><th>ACTION</th><th>ORDER</th><th>STATE CHANGE</th><th>RESULT</th><th>TIMESTAMP</th></tr></thead><tbody>{rows.map((row) => <tr key={String(row.event_id)}><td className="mono">{String(row.event_id)}</td><td><span className="actor-label"><span />{String(row.actor)}</span></td><td>{human(String(row.action))}</td><td className="mono">{String(row.order_id ?? "—")}</td><td>{String(row.previous_state || "—")} <ArrowRight size={12} /> {String(row.new_state || "—")}</td><td><span className="result-ok"><CheckCircle2 size={13} />{String(row.result)}</span></td><td>{new Date(String(row.timestamp)).toLocaleString()}</td></tr>)}</tbody></table></div>}</div>
    <div className="notice-muted"><LockKeyhole size={15} /> Audit records are append-only through the application API. Direct database modification is outside this prototype's threat model.</div>
  </>;
}

function SettingsPage({ simulationRunning, onToggleSimulation, onGenerate, onInject, busy }: { simulationRunning: boolean; onToggleSimulation: () => void; onGenerate: (n: number) => void; onInject: (c: string) => void; busy: boolean }) {
  return <><PageHeading eyebrow="PLATFORM CONFIGURATION" title="Settings" description="Manage local simulation behavior and test safe recovery paths." />
    <div className="settings-layout"><div className="panel settings-card"><div className="settings-title"><div className="settings-icon"><Radio size={17} /></div><div><h3>Simulation environment</h3><p>Controls the synthetic order generation service.</p></div></div><div className="settings-row"><div><strong>Continuous order generation</strong><span>Creates synthetic traffic every 7 seconds while running.</span></div><button className={`toggle ${simulationRunning ? "on" : ""}`} onClick={onToggleSimulation} aria-label="Toggle order simulation"><i /></button></div><div className="settings-row"><div><strong>Generation interval</strong><span>Fixed interval for the local demo environment.</span></div><span className="setting-value">7 seconds</span></div><div className="settings-row"><div><strong>Customer data</strong><span>Random synthetic customer IDs; no real PII.</span></div><span className="setting-value setting-safe"><ShieldCheck size={14} /> Synthetic</span></div></div>
      <div className="panel settings-card"><div className="settings-title"><div className="settings-icon purple"><Shield size={17} /></div><div><h3>Recovery safety policies</h3><p>Protecting high-impact operations from automatic execution.</p></div></div>{[["Bounded retries", "Maximum 3 attempts with exponential backoff"], ["Idempotency", "Retry requests preserve the original order key"], ["Operator approval", "Required for inventory and business corrections"], ["Audit trail", "All simulation and resolution operations recorded"]].map(([label, text]) => <div className="policy-row" key={label}><ShieldCheck size={15} /><div><strong>{label}</strong><span>{text}</span></div><span className="policy-active">ACTIVE</span></div>)}</div>
      <div className="panel settings-card"><div className="settings-title"><div className="settings-icon orange"><AlertTriangle size={17} /></div><div><h3>Failure injection</h3><p>Trigger controlled test incidents against the simulator.</p></div></div><div className="inject-grid"><button className="button button-fault" onClick={() => onInject("API_ERROR")} disabled={busy}><Network size={15} /> API error</button><button className="button button-fault" onClick={() => onInject("ORDER_DELAY")} disabled={busy}><Clock3 size={15} /> Order delay</button><button className="button button-fault" onClick={() => onInject("ORDER_REJECTION")} disabled={busy}><Package size={15} /> Order rejection</button><button className="button button-subtle" onClick={() => onGenerate(50)} disabled={busy}><Layers3 size={15} /> Generate 50 orders</button></div></div></div>
  </>;
}

function IncidentModal({ incident, onClose, onAction }: { incident: Incident; onClose: () => void; onAction: (action: string) => void }) {
  return <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}><motion.div className="modal" initial={{ opacity: 0, scale: 0.97, y: 8 }} animate={{ opacity: 1, scale: 1, y: 0 }}><div className="modal-header"><div><div className="eyebrow">INCIDENT DETAILS</div><h2>{incident.incident_id}</h2></div><button className="icon-btn" onClick={onClose}><X size={17} /></button></div>
    <div className="modal-tags"><span className={`severity ${incident.severity}`}>{incident.severity}</span><span className={`resolution-status ${incident.status}`}>{human(incident.status)}</span><span className="confidence">Confidence <strong>{Math.round(incident.confidence * 100)}%</strong></span></div>
    <div className="modal-section"><label>Order and affected service</label><div className="modal-keyline"><strong>{incident.order_id}</strong><span>{incident.service}</span><span>{human(incident.category)}</span></div></div>
    <div className="modal-section"><label>Probable root cause</label><p>{incident.cause}</p></div><div className="modal-section"><label>Correlated evidence</label><div className="modal-evidence">{incident.evidence.map((e) => <div key={e}><CheckCircle2 size={14} />{e}</div>)}</div></div>
    <div className="modal-recommendation"><Sparkles size={15} /><div><label>Recommended action</label><p>{incident.recommendation}</p></div></div>
    <div className="modal-footer"><span>Rule-based analysis · Synthetic event data</span><div><button className="button button-outline button-small" onClick={() => onAction("escalate")}>Escalate</button><button className="button button-approve button-small" onClick={() => onAction("approve")}><Check size={14} /> Approve action</button></div></div>
  </motion.div></div>;
}

function OrderModal({ order, timeline, onClose }: { order: Order; timeline: Record<string, string>[]; onClose: () => void }) {
  return <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}><motion.div className="modal order-modal" initial={{ opacity: 0, scale: 0.97, y: 8 }} animate={{ opacity: 1, scale: 1, y: 0 }}><div className="modal-header"><div><div className="eyebrow">ORDER DETAILS</div><h2>{order.order_id}</h2></div><button className="icon-btn" onClick={onClose}><X size={17} /></button></div>
    <div className="order-detail-grid"><div><span>Customer</span><strong>{order.customer_id}</strong></div><div><span>Order type</span><strong>{order.order_type}</strong></div><div><span>Status</span><strong className="order-status"><i />{order.status}</strong></div><div><span>Priority</span><strong>{order.priority}</strong></div><div><span>Order value</span><strong>${order.value.toFixed(2)}</strong></div><div><span>Correlation ID</span><strong className="mono">{order.correlation_id}</strong></div></div>
    <div className="modal-section"><label>Order journey</label><div className="timeline">{timeline.map((item, index) => <div className={`timeline-item ${item.status}`} key={`${item.stage}-${index}`}><span className="timeline-dot">{item.status === "success" || item.status === "recovered" ? <Check size={12} /> : item.status === "failure" ? <X size={12} /> : index + 1}</span><div><strong>{item.stage}</strong><p>{item.message}</p><small>{item.service} · {new Date(item.timestamp).toLocaleTimeString()}</small></div></div>)}</div></div>
    {order.failure_reason && <div className="modal-alert"><AlertTriangle size={15} />{order.failure_reason}</div>}
  </motion.div></div>;
}

export default App;
