import { useCallback, useEffect, useState } from 'react';
import { Card, Col, Row, Statistic, Typography } from 'antd';
import { get, type WorkspaceOverview } from '../api';

const LABELS: Record<string, string> = {
  experts: '专家', plugins: '插件', skills: '技能', connectors: '连接器',
};

export default function StoragePage() {
  const [ws, setWs] = useState<WorkspaceOverview | null>(null);

  const load = useCallback(async () => {
    setWs(await get<WorkspaceOverview>('/workspace'));
  }, []);

  useEffect(() => { load(); }, [load]);

  if (!ws) return null;

  return (
    <>
      <Row gutter={[14, 14]} style={{ marginBottom: 18 }}>
        {Object.entries(ws.counts).map(([k, v]) => (
          <Col xs={12} sm={6} key={k}>
            <Card>
              <Statistic title={LABELS[k] ?? k} value={v} />
            </Card>
          </Col>
        ))}
      </Row>

      <Card title="路径" style={{ marginBottom: 16 }}>
        <Row style={{ padding: '6px 0', borderBottom: '1px dashed #e5e7eb' }}>
          <Col span={12}>工作区（专家/会话/插件/技能）</Col>
          <Col span={12} style={{ textAlign: 'right', color: '#6b7280', wordBreak: 'break-all' }}>
            <Typography.Text code>{ws.workspace}</Typography.Text>
          </Col>
        </Row>
        <Row style={{ padding: '6px 0' }}>
          <Col span={12}>数据根（SQLite）</Col>
          <Col span={12} style={{ textAlign: 'right', color: '#6b7280', wordBreak: 'break-all' }}>
            <Typography.Text code>{ws.data_root}</Typography.Text>
          </Col>
        </Row>
      </Card>

      <Card title="表现层接入">
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0, fontSize: 13, lineHeight: 1.8 }}>
          任何表现层（桌宠壳、网页聊天、终端）只要消费{' '}
          <Typography.Text code>POST /api/agents/{'{id}'}/chat</Typography.Text> 的 SSE 事件流
          （<Typography.Text code>token / emotion / tool_call / tool_result / done</Typography.Text>）即可接入，
          协议见 <Typography.Text code>docs/pet-protocol.md</Typography.Text>。表现层可插拔，后端与协议不变。
        </Typography.Paragraph>
      </Card>
    </>
  );
}
