/**
 * ApprovalCard：HITL 人工审批卡片（对话被写工具暂停时出现）。
 *
 * 一条回复里**所有**命中门禁的工具调用会被打包成一次审批请求，逐条决策、
 * 且决策条数必须与动作条数严格相等（harness 少一条就 ValueError，会话卡死），
 * 所以这里按 action_requests 全量渲染 —— 原先只取 [0]，多动作时用户看不到
 * 还有第二、第三个写操作要批。
 *
 * 单动作保持旧的两键交互（批准即走，不逼用户多点一次）；多动作改为
 * 每条选一次再统一提交。按钮只摆该动作允许的取值（review_configs.allowed_decisions）。
 */

import { useEffect, useMemo, useState } from 'react';
import { Button, Input, Space, Tooltip } from 'antd';
import { CheckOutlined, CloseOutlined, SafetyCertificateOutlined } from '@ant-design/icons';

import type { ApprovalDecisionInput, ApprovalRequest } from '../../api';
import type { ApprovalState } from './useChatStream';

/** 一条待审动作 + 它允许的决策集合（前端据此决定摆哪几个按钮） */
export interface ApprovalAction {
  key: number;
  name: string;
  args: Record<string, unknown>;
  description?: string;
  allowed: string[];
}

export function toApprovalActions(request?: ApprovalRequest): ApprovalAction[] {
  const configs = request?.review_configs ?? [];
  const list = request?.action_requests ?? [];
  return list.map((a, i) => {
    const cfg = configs.find(c => c.action_name === a?.name);
    return {
      key: i,
      name: a?.name || '（工具名未知）',
      args: a?.args || {},
      description: a?.description,
      // 后端缺 review_configs 时按 tool_guard 口径（只允许 approve/reject）
      allowed: cfg?.allowed_decisions?.length ? cfg.allowed_decisions : ['approve', 'reject'],
    };
  });
}

interface Props {
  approval: ApprovalState;
  /** 提交逐条决策（长度必须等于动作数，由后端再校验一次） */
  onSubmit: (decisions: ApprovalDecisionInput[]) => void;
}

export default function ApprovalCard({ approval, onSubmit }: Props) {
  const actions = useMemo(() => toApprovalActions(approval.request), [approval.request]);
  const [choices, setChoices] = useState<string[]>(() => actions.map(a => (a.allowed.includes('approve') ? 'approve' : a.allowed[0])));
  const [reason, setReason] = useState('');
  const [showReason, setShowReason] = useState(false);
  const busy = approval.pending;

  // 卡片换了一批动作（同会话连续两次审批）时重算默认选择，否则长度对不上
  useEffect(() => {
    setChoices(actions.map(a => (a.allowed.includes('approve') ? 'approve' : a.allowed[0])));
  }, [actions]);

  const submit = (override?: string[]) => {
    const picks = override ?? choices;
    const msg = reason.trim() || undefined;
    onSubmit(picks.map(t => (t === 'approve' ? { type: t as ApprovalDecisionInput['type'] } : { type: t as ApprovalDecisionInput['type'], message: msg })));
  };

  const single = actions.length === 1 ? actions[0] : null;

  return (
    <div
      style={{
        border: '1px solid var(--warn-line)',
        borderRadius: 10,
        background: 'var(--accent-soft)',
        padding: '10px 14px',
        margin: '8px 12px 0',
        maxWidth: 620,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <SafetyCertificateOutlined style={{ color: 'var(--warn)' }} />
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--label-1)' }}>
          需要人工审批
          {actions.length > 1 ? `（本轮 ${actions.length} 个动作）` : ''}
          {busy ? '（提交中…）' : ''}
        </span>
      </div>

      {actions.map((a, i) => (
        <div
          key={a.key}
          style={{
            border: single ? undefined : '1px solid var(--line-2)',
            borderRadius: 8,
            padding: single ? 0 : '8px 10px',
            marginBottom: single ? 0 : 8,
            background: single ? undefined : 'var(--surface)',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center' }}>
            <span style={{ fontSize: 13, fontWeight: 500 }}>{a.name}</span>
            {!single && (
              <Space size={4}>
                {a.allowed.includes('approve') && (
                  <Button
                    size="small"
                    type={choices[i] === 'approve' ? 'primary' : 'text'}
                    icon={<CheckOutlined />}
                    disabled={busy}
                    aria-label={`批准 ${a.name}`}
                    onClick={() => setChoices(c => c.map((v, k) => (k === i ? 'approve' : v)))}
                  >
                    批准
                  </Button>
                )}
                {a.allowed.includes('reject') && (
                  <Button
                    size="small"
                    danger={choices[i] === 'reject'}
                    type={choices[i] === 'reject' ? 'primary' : 'text'}
                    icon={<CloseOutlined />}
                    disabled={busy}
                    aria-label={`拒绝 ${a.name}`}
                    onClick={() => setChoices(c => c.map((v, k) => (k === i ? 'reject' : v)))}
                  >
                    拒绝
                  </Button>
                )}
              </Space>
            )}
          </div>
          {a.description && <div style={{ fontSize: 12, color: 'var(--label-2)' }}>{a.description}</div>}
          {Object.keys(a.args).length > 0 && (
            <pre
              style={{
                fontSize: 12,
                color: 'var(--label-2)',
                background: 'var(--surface-2)',
                border: '1px solid var(--line-2)',
                borderRadius: 6,
                padding: '6px 10px',
                margin: '6px 0 0',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
                maxHeight: 160,
                overflow: 'auto',
              }}
            >
              {JSON.stringify(a.args, null, 2)}
            </pre>
          )}
        </div>
      ))}

      {actions.length === 0 && (
        <div style={{ fontSize: 13, color: 'var(--label-2)' }}>（审批请求缺少动作明细，只能拒绝后重试）</div>
      )}

      {showReason && (
        <Input.TextArea
          value={reason}
          onChange={e => setReason(e.target.value)}
          placeholder="拒绝理由（可选，会告知模型为什么拒绝）"
          autoSize={{ minRows: 2, maxRows: 4 }}
          style={{ marginTop: 8, marginBottom: 4, fontSize: 13 }}
        />
      )}

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 10 }}>
        {single ? (
          <>
            {single.allowed.includes('approve') && (
              <Button
                size="small"
                type="primary"
                icon={<CheckOutlined />}
                loading={busy}
                disabled={busy}
                onClick={() => submit(['approve'])}
              >
                批准执行
              </Button>
            )}
            {single.allowed.includes('reject') && (
              <Button
                size="small"
                danger
                icon={<CloseOutlined />}
                loading={busy}
                disabled={busy}
                onClick={() => submit(['reject'])}
              >
                拒绝
              </Button>
            )}
            <Button size="small" type="text" onClick={() => setShowReason(v => !v)} disabled={busy}>
              {showReason ? '收起理由' : '填拒绝理由'}
            </Button>
          </>
        ) : (
          <>
            <Tooltip title="按当前每条动作的选择提交；未改动的默认批准">
              <Button
                size="small"
                type="primary"
                loading={busy}
                disabled={busy || actions.length === 0}
                onClick={() => submit()}
              >
                提交 {actions.length} 条决策
              </Button>
            </Tooltip>
            <Button size="small" disabled={busy || actions.length === 0} onClick={() => submit(actions.map(() => 'reject'))}>
              全部拒绝
            </Button>
            <Button size="small" type="text" onClick={() => setShowReason(v => !v)} disabled={busy}>
              {showReason ? '收起理由' : '填拒绝理由'}
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
