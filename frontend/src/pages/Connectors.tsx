import { useCallback, useEffect, useState } from 'react';
import {
  Avatar, Button, Card, Empty, Form, Input, List, Modal, Popconfirm, Select, Space,
  Tag, Typography, message,
} from 'antd';
import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons';
import { del, get, post, put, type ConnectorServer } from '../api';

interface McpFormValues {
  name?: string;
  transport: string;
  command: string;
  args?: string[];
}

const AVATAR_COLORS = ['#f59e0b', '#3b82f6', '#10b981', '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316'];
const TRANSPORT_COLOR: Record<string, string> = { stdio: 'blue', sse: 'green', http: 'purple' };

export default function McpPage() {
  const [servers, setServers] = useState<ConnectorServer[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<ConnectorServer | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<McpFormValues>();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setServers(await get<ConnectorServer[]>('/connectors'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ transport: 'stdio' });
    setModalOpen(true);
  };

  const openEdit = (s: ConnectorServer) => {
    setEditing(s);
    form.resetFields();
    form.setFieldsValue({
      name: s.name, transport: s.transport, command: s.command, args: s.args,
    });
    setModalOpen(true);
  };

  const save = async () => {
    const v = await form.validateFields();
    setSaving(true);
    try {
      const payload = { transport: v.transport, command: v.command, args: v.args || [] };
      if (editing) {
        await put(`/connectors/${editing.name}`, payload);
        message.success(`连接器 ${editing.name} 已更新（下次对话生效）`);
      } else {
        await post('/connectors', { ...payload, name: v.name });
        message.success(`连接器 ${v.name} 已添加（下次对话生效）`);
      }
      setModalOpen(false);
      load();
    } catch (e) {
      message.error(`保存失败：${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  const remove = async (name: string) => {
    try {
      await del(`/connectors/${name}`);
      message.success(`连接器 ${name} 已删除`);
      load();
    } catch (e) {
      message.error(`删除失败：${(e as Error).message}`);
    }
  };

  const renderConnector = (s: ConnectorServer) => {
    const t = s.transport || 'stdio';
    const color = AVATAR_COLORS[(s.name.charCodeAt(0) || 0) % AVATAR_COLORS.length];
    const cmd = s.command || '—';
    const args = (s.args || []).join(' ');
    return (
      <List.Item>
        <Card size="small" style={{ height: '100%', display: 'flex', flexDirection: 'column', position: 'relative' }}>
          <Tag color={TRANSPORT_COLOR[t] || 'default'} style={{ position: 'absolute', top: 8, right: 8, margin: 0, fontSize: 11 }}>
            {t}
          </Tag>
          <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start', paddingRight: 44 }}>
            <Avatar size={40} style={{ backgroundColor: color, flexShrink: 0 }}>
              {(s.name[0] || '?').toUpperCase()}
            </Avatar>
            <div style={{ flex: 1, minWidth: 0 }}>
              <Typography.Text strong ellipsis style={{ display: 'block' }} title={s.name}>
                {s.name}
              </Typography.Text>
              <Typography.Text type="secondary" style={{ fontSize: 12 }} ellipsis title={cmd}>
                {cmd}
              </Typography.Text>
              {args && (
                <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block' }} ellipsis title={args}>
                  {args}
                </Typography.Text>
              )}
            </div>
          </div>
          <div style={{ flex: 1 }} />
          <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ color: '#9ca3af', fontSize: 12 }}>工具名带 {s.name}_ 前缀</span>
            <Space size={4}>
              <Button size="small" type="text" icon={<EditOutlined />} onClick={() => openEdit(s)} />
              <Popconfirm
                title="删除连接器？"
                description="将移除该服务器及其工具，下次对话生效"
                okText="删除" cancelText="取消"
                onConfirm={() => remove(s.name)}
              >
                <Button size="small" type="text" danger icon={<DeleteOutlined />} />
              </Popconfirm>
            </Space>
          </div>
        </Card>
      </List.Item>
    );
  };

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增连接器</Button>
      </div>
      <List
        grid={{ gutter: 12, xs: 1, sm: 2, md: 3, lg: 3, xl: 4, xxl: 5 }}
          className="nuomi-grid"
        dataSource={servers} loading={loading} size="small"
        locale={{ emptyText: <Empty description="还没有配置连接器" /> }}
        renderItem={renderConnector}
      />
      <Card style={{ marginTop: 16 }} size="small">
        <Typography.Text strong>如何接入连接器</Typography.Text>
        <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0, fontSize: 13, lineHeight: 1.8 }}>
          在本页直接新增/编辑/删除（MCP 协议，langchain-mcp-adapters 格式，stdio 需 command）。
          配置持久化在 <Typography.Text code>data_root/connectors.json</Typography.Text>（重启不丢）；
          仓库根 <Typography.Text code>.env</Typography.Text> 的{' '}
          <Typography.Text code>NUOMI_CONNECTORS</Typography.Text> 仅作首次播种（无 json 时生效）。
          对话时工具名带 <Typography.Text code>{'{连接器名}_'}</Typography.Text> 前缀，自动对专家可用；
          增删改后下次对话生效。
        </Typography.Paragraph>
      </Card>

      <Modal
        title={editing ? `编辑连接器：${editing.name}` : '新增连接器'}
        open={modalOpen}
        onOk={save}
        onCancel={() => setModalOpen(false)}
        okText="保存"
        cancelText="取消"
        confirmLoading={saving}
        destroyOnClose
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="name" label="连接器名"
            rules={[
              { required: true, message: '请输入连接器名' },
              { pattern: /^[a-zA-Z0-9_-]+$/, message: '仅限字母/数字/_/-' },
            ]}
          >
            <Input placeholder="如 pet_mood" disabled={!!editing} />
          </Form.Item>
          <Form.Item name="transport" label="传输" rules={[{ required: true }]}>
            <Select
              options={[
                { value: 'stdio', label: 'stdio（本地子进程）' },
                { value: 'sse', label: 'sse（HTTP 流）' },
                { value: 'http', label: 'http' },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="command" label="命令"
            rules={[({ getFieldValue }) => ({
              validator: (_, v) => (
                getFieldValue('transport') === 'stdio' && !(v || '').trim()
                  ? Promise.reject(new Error('stdio 传输需要 command'))
                  : Promise.resolve()
              ),
            })]}
          >
            <Input placeholder="可执行文件路径，如 /path/to/python" />
          </Form.Item>
          <Form.Item name="args" label="参数">
            <Select mode="tags" placeholder="回车添加参数（可选）" open={false} suffixIcon={null} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
