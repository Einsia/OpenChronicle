import type { ApprovalStatus, SafetyApproval } from "../../types/rpa";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";

interface SafetyApprovalPanelProps {
  approvals: SafetyApproval[];
  onDecision: (approval: SafetyApproval, status: ApprovalStatus) => void;
}

export function SafetyApprovalPanel({ approvals, onDecision }: SafetyApprovalPanelProps) {
  return (
    <Card>
      <CardHeader className="min-w-0">
        <CardTitle className="min-w-0 truncate">安全审批（6）</CardTitle>
        <button className="shrink-0 text-xs font-medium text-blue-600">查看全部 ›</button>
      </CardHeader>
      <CardContent className="min-w-0 pt-0">
        <div className="overflow-x-auto">
          <table className="min-w-[560px] w-full text-left text-xs">
            <thead className="text-slate-500">
              <tr className="border-b border-slate-100">
                <th className="py-2 font-medium">动作</th>
                <th className="font-medium">风险等级</th>
                <th className="font-medium">发现时间</th>
                <th className="font-medium">状态 / 操作</th>
              </tr>
            </thead>
            <tbody>
              {approvals.map((approval) => (
                <tr key={approval.id} className="border-b border-slate-50 last:border-0">
                  <td className="py-2 font-medium text-slate-800">{approval.action}</td>
                  <td>
                    <Badge tone={approval.riskLevel === "L3" ? "red" : approval.riskLevel === "L2" ? "orange" : "green"}>{approval.riskLevel} 风险</Badge>
                  </td>
                  <td className="text-slate-500">{approval.createdAt}</td>
                  <td>
                    {approval.status === "pending" ? (
                      <div className="flex gap-1">
                        <Button size="sm" variant="success" onClick={() => onDecision(approval, "approved")}>批准</Button>
                        <Button size="sm" variant="danger" onClick={() => onDecision(approval, "rejected")}>拒绝</Button>
                      </div>
                    ) : (
                      <Badge tone={approval.status === "approved" ? "green" : "red"}>{approval.status === "approved" ? "已批准" : "已拒绝"}</Badge>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
