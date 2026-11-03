import type {
  FabricationReport,
  OperationReadiness,
  ToolCheck,
} from "./generated/api-contracts";

export const fabricationStatusText: Record<
  FabricationReport["status"],
  string
> = {
  ready: "A step can be attempted now.",
  blocked: "No step can be attempted yet.",
  complete: "Every planned step is recorded as done.",
  history_conflict:
    "Recorded history conflicts with this plan, so no step can be scheduled until it is reviewed.",
};

const toolNames: Record<ToolCheck["tool"], string> = {
  cutting_tool: "Cutting tool",
  ruler: "Ruler",
  marker: "Marker",
  scale: "Scale",
  protractor: "Protractor",
};

export function toolText(tool: ToolCheck): string {
  const name = toolNames[tool.tool];
  if (tool.status === "declared")
    return `${name}: your saved ${tool.declared_name}`;
  if (tool.status === "not_declared") return `${name}: not in your saved tools`;
  return `${name}: no tools saved`;
}

export type ReadinessGroups = {
  next: OperationReadiness | null;
  ready: OperationReadiness[];
  waiting: OperationReadiness[];
  blocked: OperationReadiness[];
  completed: number;
};

export function readinessGroups(report: FabricationReport): ReadinessGroups {
  const groups: ReadinessGroups = {
    next: null,
    ready: [],
    waiting: [],
    blocked: [],
    completed: 0,
  };
  for (const operation of report.operations) {
    if (operation.operation_id === report.next_operation_id)
      groups.next = operation;
    else if (operation.status === "ready") groups.ready.push(operation);
    else if (operation.status === "waiting") groups.waiting.push(operation);
    else if (operation.status === "blocked") groups.blocked.push(operation);
    else groups.completed += 1;
  }
  return groups;
}

export function orderText(report: FabricationReport): string {
  const steps = report.supported_order.length;
  const moved = report.supported_order.filter((step) => step.reordered).length;
  if (report.order_status === "cycle")
    return "Some remaining steps wait on each other, so no order can finish them.";
  if (report.order_status === "blocked")
    return steps === 0
      ? "No remaining order is supported yet."
      : `Only the first ${steps} remaining ${steps === 1 ? "step has" : "steps have"} a supported order.`;
  if (steps === 0) return "No steps remain.";
  return moved === 0
    ? `All ${steps} remaining ${steps === 1 ? "step follows" : "steps follow"} the manual order.`
    : `${moved} of ${steps} remaining steps move earlier than the manual lists them, so shaping comes before joining.`;
}
