import { useCallback, useEffect, useState } from 'react';
import {
  Button, Card, Empty, Form, Input, Modal, Popconfirm, Select, Space, Table,
  Tag, Typography, message,
} from 'antd';
import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons';
import { del, get, post, put, type McpServer } from '../api';

interface McpFormValues {
  name?: string;
  transport: string;
  command: string;
  args?: string[];
}

export default function McpPage() {
  const [servers, setServers] = useState<McpServer[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<McpServer | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<McpFormValues>();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setServers(await get<McpServer[]>('/mcp'));
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

  const openEdit = (s: McpServer) => {
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
        await put(`/mcp/${editing.name}`, payload);
        message.success(`MCP 服务器 ${editing.name} 已更新（下次对话生效）`);
      } else {
        await post('/mcp', { ...payload, name: v.name });
        message.success(`MCP 服务器 ${v.name} 已添加（下次对话生效）`);
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
      await del(`/mcp/${name}`);
      message.success(`MCP 服务器 ${name} 已删除`);
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
    { title: '操作', width: 110, render: (_: unknown, s: McpServer) => (
        <Space size={4}>
          <Button size="small" type="text" icon={<EditOutlined />} onClick={() => openEdit(s)} />
          <Popconfirm
            title="删除 MCP 服务器？"
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
        <Card><Empty description="还没有配置 MCP 服务器" /></Card>
      ) : (
        <Table<McpServer>
          rowKey="name"
          columns={columns}
          dataSource={servers}
          loading={loading}
          pagination={false}
        />
      )}
      <Card style={{ marginTop: 16 }} size="small">
        <Typography.Text strong>如何接入 MCP</Typography.Text>
        <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0, fontSize: 13, lineHeight: 1.8 }}>
          在本页直接新增/编辑/删除（langchain-mcp-adapters 格式，stdio 需 command）。
          配置持久化在 <Typography.Text code>data_root/mcp_servers.json</Typography.Text>（重启不丢）；
          仓库根 <Typography.Text code>.env</Typography.Text> 的{' '}
          <Typography.Text code>NUOMI_MCP_SERVERS</Typography.Text> 仅作首次播种（无 json 时生效）。
          对话时工具名带 <Typography.Text code>{'{服务器名}_'}</Typography.Text> 前缀，自动对专家可用；
          增删改后下次对话生效。
        </Typography.Paragraph>
      </Card>

      <Modal
        title={editing ? `编辑 MCP 服务器：${editing.name}` : '新增 MCP 服务器'}
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
