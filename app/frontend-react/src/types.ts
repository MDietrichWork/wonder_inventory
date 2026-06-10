// Shape of GET /api/bootstrap (mirrors the backend contract.build_bootstrap).
export interface Exception {
  pk: number;
  id: string;
  runDate: string;
  errorType: string;
  severity: "Urgent" | "High" | "Medium" | "Low";
  table: string;
  facility: string;
  system: string;
  entityKey: string;
  team: string;
  assignee: string;
  primaryOwner: string;
  currentHolder: string;
  heldSince: string;
  heldDays: number;
  jira: string;
  jiraStatus: string;
  created: string;
  detectedOn?: string;
  lastReceipt?: string | null;
  resolved: string | null;
  recurrence: number;
  snapshot: Record<string, any>;
  rule: string;
  timeline: { status: string; at: string; by: string }[];
  notes: { by: string; at: string; text: string }[];
  age: number;
  turnaround: number | null;
  slaTarget: number;
  withinSla: boolean;
  isOpen: boolean;
  autoClosed: boolean;
  subAssign?: { toTeam: string; toPerson: string; at: string; byPerson: string; slaRemainingDays: number; note: string };
}

export interface Bootstrap {
  meta: { today: string; runDate: string; jiraProject: string; jiraBaseUrl: string | null };
  facilities: { id: string; type: string }[];
  systems: string[];
  sourceTables: string[];
  movementTypes: string[];
  errorTypes: { type: string; rule: string; ruleType: string; owner: string; desc: string }[];
  teams: Record<string, string[]>;
  slaTargets: Record<string, number>;
  rules: { id: string; name: string; type: string; errorType: string; target: string; severity: string; expression: string; enabled: boolean }[];
  routing: { errorType: string; team: string; assignee: string; project: string; component: string }[];
  exceptions: Exception[];
  trend: { date: string; count: number; autoClosed: number }[];
  recurring: { fingerprint: string; errorType: string; facility: string; count30d: number; team: string; lastSeen: string; trend: string }[];
  wasteByLocation?: { facility: string; day: string; dollars: number; skus: number }[];
}

export type Drill = { label: string; test: (e: Exception) => boolean } | null;
