/**
 * ApprovalCard：HITL 人工审批卡片（对话被写工具暂停时出现）。
 *
 * 展示待审批的工具与参数（后端来自 ToolGuard interrupt 的 action_requests），
 * 用户点「批准」放行执行 / 「拒绝」不执行并返回拒绝信息；pending 期间按钮禁用。
 * 拒绝理由可选填写（会随审批提交给后端，harness 把它作为 ToolMessage 回给模型）。
 */

import { useState } from 'react';
import { Button, Input } from 'antd';
import { CheckOutlined, CloseOutlined, SafetyCertificateOutlined } from '@ant-design/icons';

import type { ApprovalState } from './useChatStream';

interface Props {
  approval: ApprovalState;
  onApprove: () => void;
  onReject: (reason?: string) => void;
}

export default function ApprovalCard({ approval, onApprove, onReject }: Props) {
  const [reason, setReason] = useState('');
  const [showReason, setShowReason] = useState(false);
  const action = approval.request?.action_requests?.[0];
  const toolName = action?.name || '';
  const args = action?.args || {};
  const argsText = Object.keys(args).length
    ? JSON.stringify(args, null, 2)
    : '';
  const busy = approval.pending;

  return (
    <div
      style={{
        border: '1px solid #f59e0b',
        borderRadius: 10,
        background: '#fff8f0',
        padding: '10px 14px',
        margin: '8px 12px 0',
        maxWidth: 560,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <SafetyCertificateOutlined style={{ color: '#d97706' }} />
        <span style={{ fontSize: 13, fontWeight: 600, color: '#874d00' }}>
          需要人工审批{approval.pending ? '（提交中…）' : ''}
        </span>
      </div>
      <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 4 }}>
        {toolName || '（工具名未知）'}
      </div>
      {argsText && (
        <pre
          style={{
            fontSize: 12,
            color: 'var(--label-2)',
            background: 'rgba(255,255,255,0.7)',
            border: '1px solid #fcd9a8',
            borderRadius: 6,
            padding: '6px 10px',
            margin: '6px 0 8px',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            maxHeight: 160,
            overflow: 'auto',
          }}
        >
          {argsText}
        </pre>
      )}
      {showReason && (
        <Input.TextArea
          value={reason}
          onChange={e => setReason(e.target.value)}
          placeholder="拒绝理由（可选，会告知模型为什么拒绝）"
          autoSize={{ minRows: 2, maxRows: 4 }}
          style={{ marginBottom: 8, fontSize: 13 }}
        />
      )}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <Button
          size="small"
          type="primary"
          icon={<CheckOutlined />}
          loading={busy}
          disabled={busy}
          style={{ background: '#16a34a' }}
          onClick={onApprove}
        >
          批准执行
        </Button>
        <Button
          size="small"
          danger
          icon={<CloseOutlined />}
          loading={busy}
          disabled={busy}
          onClick={() => (showReason ? onReject(reason.trim() || undefined) : onReject())}
        >
          拒绝
        </Button>
        <Button size="small" type="text" onClick={() => setShowReason(v => !v)} disabled={busy}>
          {showReason ? '收起理由' : '填拒绝理由'}
        </Button>
      </div>
    </div>
  );
}
