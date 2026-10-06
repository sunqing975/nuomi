import { useCallback, useEffect, useState } from 'react';
import {
  Alert, Button, Card, Collapse, Descriptions, Empty, Input, List, Modal, Popconfirm,
  Row, Col, Space, Statistic, Switch, Tag, Tooltip, Typography, message,
} from 'antd';
import { DeleteOutlined, EditOutlined, ReloadOutlined } from '@ant-design/icons';
import { memoryApi, type MemoryAtom, type MemoryOverview } from '../../api';

/**
 * 记忆视图 —— 回答"你到底记住了我什么"（对话伴生，随当前专家走）。
 *
 * 由 MemoryPage（平级菜单壳）与 ChatPage 的记忆抽屉共用（P0-6，2026-10-06）：
 * 记忆不再是平级菜单项，而是对话的伴生视图 —— 聊天里随时看"我记住了你什么"。
 *
 * 两处来源：
 * 1. 结构化记忆（atoms）：记忆引擎从对话里提炼的断言，带原话与来源会话；可以「忘记」它。
 * 2. 人设 / 长期记忆文件（MEMORY.md / USER.md / SOUL.md / AGENTS.md 等）：由 harness
 *    每轮注入，改完下一轮生效。这里允许直接修正。
 *
 * 「忘记」走后端软遗忘（引擎 API），所以之后不会再被想起来，但仍可在「显示已遗忘」里审计到。
 */
export default function MemoryView({ agentId }: { agentId: string | null }) {
  const [overview, setOverview] = useState<MemoryOverview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [includeDeprecated, setIncludeDeprecated] = useState(false);

  const [editing, setEditing] = useState<{ name: string; content: string } | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async (id: string, showDeprecated: boolean) => {
    setLoading(true);
    setError(null);
    try {
      setOverview(await memoryApi.overview(id, { limit: 100, includeDeprecated: showDeprecated }));
    } catch (e) {
      setError(`加载记忆失败：${(e as Error).message}`);
      setOverview(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setOverview(null);
    if (agentId) load(agentId, includeDeprecated);
  }, [agentId, includeDeprecated, load]);

  const forget = async (atom: MemoryAtom) => {
    if (!agentId) return;
    try {
      await memoryApi.forgetAtom(agentId, atom.id, '用户在控制台遗忘');
      message.success('已忘记这条记忆');
      load(agentId, includeDeprecated);
    } catch (e) {
      message.error(`取消失败：${(e as Error).message}`);
    }
  };

  const openFile = async (name: string) => {
    if (!agentId) return;
    try {
      const r = await memoryApi.readFile(agentId, name);
      setEditing({ name, content: r.content });
    } catch (e) {
      message.error(`读取失败：${(e as Error).message}`);
    }
  };

  const saveFile = async () => {
    if (!agentId || !editing) return;
    setSaving(true);
    try {
      await memoryApi.writeFile(agentId, editing.name, editing.content);
      message.success(`${editing.name} 已保存（下一轮对话生效）`);
      setEditing(null);
      load(agentId, includeDeprecated);
    } catch (e) {
      message.error(`保存失败：${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  const stats = overview?.stats;
  const atoms = overview?.atoms ?? [];

  return (
    <>
      <Row gutter={[14, 14]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="记住了" value={stats?.atoms ?? 0} suffix="条" />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="记忆对象" value={stats?.entities ?? 0} suffix="个" />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="原始对话事件" value={stats?.raw_events ?? 0} suffix="条" />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="已遗忘" value={stats?.deprecated ?? 0} suffix="条" />
          </Card>
        </Col>
      </Row>

      <Space size={6} style={{ marginBottom: 12 }}>
        <Switch size="small" checked={includeDeprecated} onChange={setIncludeDeprecated} />
        <Typography.Text style={{ fontSize: 13 }}>显示已遗忘</Typography.Text>
        <Button size="small" icon={<ReloadOutlined />} loading={loading} onClick={() => agentId && load(agentId, includeDeprecated)}>
          刷新
        </Button>
      </Space>

      {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />}

      {overview?.exists === false && (
        <Alert
          style={{ marginBottom: 16 }}
          type="info"
          showIcon
          message="这个专家还没有结构化记忆"
          description="记忆由对话累积：聊过之后，引擎会把其中的事实提炼成断言，出现在这里。"
        />
      )}

      <Row gutter={[14, 14]}>
        <Col xs={24} lg={15}>
          <Card
            size="small"
            title="我记住了什么"
            extra={<Typography.Text type="secondary" style={{ fontSize: 12 }}>共 {overview?.total ?? 0} 条</Typography.Text>}
          >
            {atoms.length === 0 ? (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={loading ? '加载中…' : '还没有记忆'}
              />
            ) : (
              <List
                dataSource={atoms}
                renderItem={(atom: MemoryAtom) => (
                  <List.Item
                    key={atom.id}
                    actions={[
                      <Popconfirm
                        key="forget"
                        title="忘记这条记忆？"
                        description="之后不会再被想起来，但仍可在「显示已遗忘」里看到。"
                        okText="忘记"
                        cancelText="算了"
                        onConfirm={() => forget(atom)}
                      >
                        <Tooltip title="忘记它">
                          <Button size="small" danger type="text" icon={<DeleteOutlined />} />
                        </Tooltip>
                      </Popconfirm>,
                    ]}
                  >
                    <List.Item.Meta
                      title={
                        <Space size={6} wrap>
                          <Typography.Text strong>{atom.assertion}</Typography.Text>
                          {atom.deprecated_at && <Tag color="default">已遗忘</Tag>}
                        </Space>
                      }
                      description={
                        <>
                          <div style={{ marginBottom: 4 }}>
                            <Space size={4} wrap>
                              <Tag color={atom.importance === 'high' ? 'gold' : 'default'}>
                                重要度 {atom.importance}
                              </Tag>
                              <Tag>置信度 {atom.confidence}</Tag>
                              {atom.entity_name && <Tag color="blue">关于 {atom.entity_name}</Tag>}
                              {(atom.occurred_at || '').slice(0, 10) && (
                                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                                  {atom.occurred_at.slice(0, 10)}
                                </Typography.Text>
                              )}
                            </Space>
                          </div>
                          <Collapse
                            size="small"
                            ghost
                            items={[
                              {
                                key: 'src',
                                label: (
                                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                                    我是因为哪句话记住的
                                    {atom.source_thread_id ? `（会话 ${atom.source_thread_id}）` : ''}
                                  </Typography.Text>
                                ),
                                children: (
                                  <Typography.Paragraph
                                    style={{ marginBottom: 0, fontSize: 12, whiteSpace: 'pre-wrap' }}
                                    type="secondary"
                                  >
                                    {atom.verbatim_quote || '（无原话记录）'}
                                  </Typography.Paragraph>
                                ),
                              },
                            ]}
                          />
                        </>
                      }
                    />
                  </List.Item>
                )}
              />
            )}
          </Card>
        </Col>

        <Col xs={24} lg={9}>
          <Card title="记忆文件（下一轮生效）" size="small" style={{ marginBottom: 14 }}>
            {overview?.files?.length ? (
              <List
                size="small"
                dataSource={overview.files}
                renderItem={f => (
                  <List.Item
                    key={f.name}
                    actions={[
                      <Button
                        key="edit"
                        size="small"
                        type="text"
                        icon={<EditOutlined />}
                        onClick={() => openFile(f.name)}
                      />,
                    ]}
                  >
                    <List.Item.Meta
                      title={
                        <Space size={6}>
                          <Typography.Text code>{f.name}</Typography.Text>
                          {f.standard && <Tag color="blue">标准</Tag>}
                        </Space>
                      }
                      description={
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          {f.bytes} 字节 · {new Date(f.updated_at * 1000).toLocaleString()}
                        </Typography.Text>
                      }
                    />
                  </List.Item>
                )}
              />
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有 .md 记忆文件" />
            )}
          </Card>

          <Card title="记忆对象" size="small">
            {overview?.entities?.length ? (
              <Space size={4} wrap>
                {overview.entities.map(e => (
                  <Tag key={e.id} color={e.atom_count > 0 ? 'blue' : 'default'}>
                    {e.canonical_name} · {e.atom_count}
                  </Tag>
                ))}
              </Space>
            ) : (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                还没有提炼出记忆对象
              </Typography.Text>
            )}
          </Card>
        </Col>
      </Row>

      <Modal
        open={!!editing}
        title={editing ? `编辑 ${editing.name}` : ''}
        width={760}
        onCancel={() => setEditing(null)}
        onOk={saveFile}
        okText="保存"
        confirmLoading={saving}
        destroyOnHidden
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          这些文件由程序每轮对话注入，保存后<strong>下一轮</strong>生效，无需重启。
        </Typography.Paragraph>
        {editing && overview && editing.content.length > overview.max_file_bytes && (
          <Alert type="warning" showIcon style={{ marginBottom: 8 }} message="内容超过上限，保存会被拒绝" />
        )}
        <Input.TextArea
          value={editing?.content ?? ''}
          onChange={e => setEditing(prev => (prev ? { ...prev, content: e.target.value } : prev))}
          autoSize={{ minRows: 14, maxRows: 26 }}
        />
        <Descriptions size="small" column={1} style={{ marginTop: 8 }}>
          <Descriptions.Item label="字节数">
            {new TextEncoder().encode(editing?.content ?? '').length}
            {overview ? ` / ${overview.max_file_bytes}` : ''}
          </Descriptions.Item>
        </Descriptions>
      </Modal>
    </>
  );
}
