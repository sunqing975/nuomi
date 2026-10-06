import { useEffect, useState } from 'react';
import { Alert, Card, Select, Space } from 'antd';
import { get, type Agent } from '../api';
import MemoryView from './memory/MemoryView';

/**
 * 记忆页壳（P0-6，2026-10-06 起不再占平级导航）：
 * 平级菜单里记忆入口已移除，完整记忆管理迁移到 ChatPage 的「记忆」抽屉
 * （对话伴生视图，随当前专家走）。本页保留仅供 hash 直达旧入口时的兜底。
 */
export default function MemoryPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [agentId, setAgentId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const rows = await get<Agent[]>('/agents');
        setAgents(rows);
        if (rows.length && !agentId) setAgentId(rows[0].agent_id);
      } catch (e) {
        setError(`加载专家列表失败：${(e as Error).message}`);
      }
    })();
    // 只在挂载时拉一次；agentId 的默认选择不应触发重拉
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <>
      <Card style={{ marginBottom: 16 }} size="small">
        <Space wrap size={12}>
          <Select
            style={{ width: 220 }}
            placeholder="选择专家"
            value={agentId ?? undefined}
            onChange={setAgentId}
            options={agents.map(a => ({ value: a.agent_id, label: a.name }))}
          />
          <span style={{ fontSize: 12, color: 'var(--label-3)' }}>
            已迁入对话页「记忆」抽屉 —— 记忆是对话的伴生视图
          </span>
        </Space>
      </Card>
      {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />}
      <MemoryView agentId={agentId} />
    </>
  );
}
