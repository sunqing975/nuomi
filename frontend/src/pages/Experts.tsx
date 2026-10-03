import { useCallback, useEffect, useState } from 'react';
import {
  Button, Card, Col, Row, Modal, Form, Input, Space, Switch, Tag, message, Popconfirm,
} from 'antd';
import { PlusOutlined, RobotOutlined } from '@ant-design/icons';
import { get, post, patch, put, del, type Agent, type Plugin } from '../api';

const { TextArea } = Input;

export default function ExpertsPage({ onBackend }: { onBackend?: (ok: boolean) => void }) {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [plugins, setPlugins] = useState<Plugin[]>([]);
  const [loading, setLoading] = useState(false);
  const [form] = Form.useForm();
  const [editing, setEditing] = useState<Agent | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [pluginModal, setPluginModal] = useState<Agent | null>(null);
  const [bound, setBound] = useState<string[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [a, p] = await Promise.all([get<Agent[]>('/agents'), get<Plugin[]>('/plugins')]);
      setAgents(a);
      setPlugins(p);
      onBackend?.(true);
    } catch {
      onBackend?.(false);
    } finally {
      setLoading(false);
    }
  }, [onBackend]);

  useEffect(() => { load(); }, [load]);

  const toggleEnabled = async (a: Agent) => {
    await patch(`/agents/${a.agent_id}`, { enabled: !a.enabled });
    message.success(!a.enabled ? '已启用' : '已停用');
    load();
  };

  const startAgent = async (a: Agent) => {
    await post(`/agents/${a.agent_id}/start`);
    message.success('实例已启动');
    load();
  };

  const saveAgent = async (values: Partial<Agent>) => {
    if (editing) {
      await patch(`/agents/${editing.agent_id}`, values);
      message.success('已保存');
    } else {
      await post('/agents', { ...values, kind: 'expert' });
      message.success('已创建');
    }
    setCreateOpen(false);
    setEditing(null);
    load();
  };

  const openPlugins = async (a: Agent) => {
    const b = await get<{ plugin_id: string }[]>(`/agents/${a.agent_id}/plugins`);
    setBound(b.map(x => x.plugin_id));
    setPluginModal(a);
  };

  const savePlugins = async (a: Agent) => {
    await put(`/agents/${a.agent_id}/plugins`, { plugin_ids: bound });
    message.success('绑定已更新（重启实例生效）');
    setPluginModal(null);
    load();
  };

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); form.resetFields(); setCreateOpen(true); }}>
          新建专家
        </Button>
      </div>

      <Row gutter={[14, 14]}>
        {agents.map(a => (
          <Col xs={24} sm={12} lg={8} xl={6} key={a.agent_id}>
            <Card loading={loading} styles={{ body: { display: 'flex', flexDirection: 'column', gap: 10 } }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <div style={{
                  width: 40, height: 40, borderRadius: '50%',
                  background: a.color || '#f59e0b', color: '#fff',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 20,
                }}>
                  {a.icon_name === 'cat' ? '🐱' : <RobotOutlined />}
                </div>
                <div>
                  <div style={{ fontWeight: 600 }}>{a.name}</div>
                  <Space size={4}>
                    <Tag>{a.kind || 'expert'}</Tag>
                    {a.last_state === 'running' && <Tag color="green">运行中</Tag>}
                  </Space>
                </div>
              </div>
              <div style={{ color: '#6b7280', fontSize: 13, minHeight: 36 }}>
                {a.description || '暂无描述'}
              </div>
              <Space wrap>
                <Switch checked={a.enabled} onChange={() => toggleEnabled(a)} checkedChildren="启用" unCheckedChildren="停用" />
                <Button size="small" onClick={() => startAgent(a)}>{a.last_state === 'running' ? '重启实例' : '启动实例'}</Button>
                <Button size="small" onClick={() => openPlugins(a)}>绑插件</Button>
                <Button size="small" onClick={() => { setEditing(a); form.setFieldsValue(a); setCreateOpen(true); }}>编辑</Button>
                <Popconfirm title={`删除「${a.name}」？`} onConfirm={async () => { await del(`/agents/${a.id ?? a.agent_id}`); message.success('已删除'); load(); }}>
                  <Button size="small" danger>删除</Button>
                </Popconfirm>
              </Space>
            </Card>
          </Col>
        ))}
      </Row>
      {!loading && agents.length === 0 && (
        <div style={{ textAlign: 'center', color: '#9ca3af', padding: 48 }}>
          还没有专家，点「新建专家」创建第一个
        </div>
      )}

      {/* 创建 / 编辑 */}
      <Modal
        open={createOpen}
        title={editing ? '编辑专家' : '新建专家'}
        onCancel={() => setCreateOpen(false)}
        onOk={() => form.submit()}
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={saveAgent}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="description" label="描述"><TextArea rows={2} /></Form.Item>
          <Form.Item name="persona_mbti" label="人格（MBTI / 性格标签）"><Input /></Form.Item>
          <Form.Item name="system_prompt" label="系统提示词"><TextArea rows={3} /></Form.Item>
          <Form.Item name="welcome_message" label="欢迎语"><Input /></Form.Item>
          <Form.Item name="icon_name" label="图标"><Input placeholder="cat / robot / …" /></Form.Item>
          <Form.Item name="color" label="主题色"><Input placeholder="#f59e0b" /></Form.Item>
        </Form>
      </Modal>

      {/* 绑插件 */}
      <Modal
        open={!!pluginModal}
        title={`绑定插件 · ${pluginModal?.name ?? ''}`}
        onCancel={() => setPluginModal(null)}
        onOk={() => pluginModal && savePlugins(pluginModal)}
        destroyOnClose
      >
        {plugins.length === 0 ? (
          <div style={{ color: '#9ca3af', textAlign: 'center', padding: 24 }}>
            还没有插件，先到「插件」页扫描
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {plugins.map(p => (
              <label key={p.plugin_id} style={{
                display: 'flex', alignItems: 'center', gap: 10,
                padding: '8px 12px', border: '1px solid #e5e7eb', borderRadius: 8, cursor: 'pointer',
              }}>
                <input
                  type="checkbox"
                  style={{ accentColor: '#f59e0b' }}
                  checked={bound.includes(p.plugin_id)}
                  onChange={e => setBound(prev =>
                    e.target.checked ? [...prev, p.plugin_id] : prev.filter(x => x !== p.plugin_id))}
                />
                <span>{p.name} <small style={{ color: '#9ca3af' }}>({p.plugin_id})</small></span>
              </label>
            ))}
          </div>
        )}
      </Modal>
    </>
  );
}
