import { useCallback, useEffect, useState } from 'react';
import {
  Button, Card, Empty, Form, Input, Modal, Popconfirm, Select, Space, Table,
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

  const columns = [
    { title: '服务器', dataIndex: 'name', render: (n: string) => <b>{n}</b> },
    { title: '传输', dataIndex: 'transport', width: 90, render: (t: string) => <Tag color="blue">{t}</Tag> },
    { title: '命令', dataIndex: 'command', render: (c: string) => <span style={{ color: '#6b7280' }}>{c || '—'}</span> },
    { title: '参数', dataIndex: 'args', render: (a: string[]) => <span style={{ color: '#6b7280' }}>{(a || []).join(' ')}</span> },
    { title: '操作', width: 110, render: (_: unknown, s: ConnectorServer) => (
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
        </Space>) },
  ];

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增服务器</Button>
      </div>
      {servers.length === 0 && !loading ? (
        <Card><Empty description="还没有配置连接器" /></Card>
      ) : (
        <Table<ConnectorServer>
          rowKey="name"
          columns={columns}
          dataSource={servers}
          loading={loading}
          pagination={false}
        />
      )}
      <Card style={{ marginTop: 16 }} size="small">
        <Typography.Text strong>如何接入连接器</Typography.Text>
        <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0, fontSize: 13, lineHeight: 1.8 }}>
          在本页直接新增/编辑/删除（MCP 协议，langchain-mcp-adapters 格式，stdio 需 command）。
          配置持久化在 <Typography.Text code>data_root/connectors.json</Typography.Text>（重启不丢）；
          仓库根 <Typography.Text code>.env</Typography.Text> 的{' '}
          <Typography.Text code>NUOMI_CONNECTORS</Typography.Text> 仅作首次播种（无 json 时生效）。
          对话时工具名带 <Typography.Text code>{'{服务器名}_'}</Typography.Text> 前缀，自动对专家可用；
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
            name="name" label="服务器名"
            rules={[
              { required: true, message: '请输入服务器名' },
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
