import { useCallback, useEffect, useState } from 'react';
import {
  Button, Card, Modal, Form, Input, Space, Switch, Tag, Typography, message, Popconfirm,
} from 'antd';
import { PlusOutlined, RobotOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons';
import { get, post, patch, del, type Agent } from '../api';
import EntityGrid from '../components/EntityGrid';
import PageLayout from '../components/PageLayout';

const { TextArea } = Input;

export default function ExpertsPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(false);
  const [form] = Form.useForm();
  const [editing, setEditing] = useState<Agent | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const a = await get<Agent[]>('/agents');
      setAgents(a);
    } catch {
      // 后端状态由 App 层全局健康探测负责，页面只负责展示自己的数据
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const toggleEnabled = async (a: Agent) => {
    await patch(`/agents/${a.agent_id}`, { enabled: !a.enabled });
    message.success(!a.enabled ? '已启用' : '已停用');
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

  return (
    <PageLayout
      title="专家"
      description="管理专家角色、人设与运行实例"
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); form.resetFields(); setCreateOpen(true); }}>
          新建专家
        </Button>
      }
    >
      <EntityGrid
        items={agents}
        loading={loading}
        minWidth={300}
        emptyText="还没有专家，点「新建专家」创建第一个"
        renderItem={a => (
          <Card
            size="small"
            hoverable
            style={a.enabled ? { height: '100%' } : { opacity: 0.75, height: '100%' }}
            title={
              <Space>
                <div style={{
                  width: 24, height: 24, borderRadius: '50%',
                  background: a.color || 'var(--accent)', color: 'var(--surface)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14,
                }}>
                  {a.icon_name === 'cat' ? '🐱' : <RobotOutlined />}
                </div>
                <span>{a.name}</span>
                {a.runtime === 'running' ? (
                  <Tag color="green">运行中</Tag>
                ) : (
                  // 「已停止」不是异常：运行实例是后端进程内的对象，改插件/技能/连接器/模型
                  // 会把它释放掉，下一轮对话自动重建。原来只在 running 时显示徽标，
                  // 非 running 整块消失 —— 用户看到的就是"我改完设置专家没了/坏了"。
                  <Tag color="default">{a.enabled ? '未运行' : '已停用'}</Tag>
                )}
              </Space>
            }
            extra={
              <Space size={4}>
                <Button size="small" type="text" icon={<EditOutlined />} onClick={() => { setEditing(a); form.setFieldsValue(a); setCreateOpen(true); }} />
                <Popconfirm title={`删除「${a.name}」？`} onConfirm={async () => { await del(`/agents/${a.agent_id}`); message.success('已删除'); load(); }}>
                  <Button size="small" type="text" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              </Space>
            }
          >
            <Typography.Paragraph type="secondary" ellipsis={{ rows: 2 }} style={{ fontSize: 13, minHeight: 40, marginBottom: 8 }}>
              {a.description || '（暂无描述）'}
            </Typography.Paragraph>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {a.persona_mbti ? `MBTI · ${a.persona_mbti}` : '—'}
              </Typography.Text>
              <span>
                <Switch size="small" checked={a.enabled} onChange={() => toggleEnabled(a)} />
                <Typography.Text type="secondary" style={{ fontSize: 12, marginLeft: 6 }}>
                  {a.enabled ? '已启用' : '已停用'}
                </Typography.Text>
              </span>
            </div>
          </Card>
        )}
      />

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
    </PageLayout>
  );
}
