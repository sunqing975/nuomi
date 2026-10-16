import { useCallback, useEffect, useState } from 'react';
import {
  Avatar, Button, Card, Form, Input, Modal, Popconfirm, Select, Space,
  Tag, Typography, message,
} from 'antd';
import { DeleteOutlined, EditOutlined, MinusCircleOutlined, PlusOutlined } from '@ant-design/icons';
import { del, get, post, put, type ConnectorServer } from '../api';
import EntityGrid from '../components/EntityGrid';
import ErrorState from '../components/ErrorState';
import PageLayout from '../components/PageLayout';
import { pickAvatarColor } from '../utils/palette';

interface EnvItem {
  key?: string;
  value?: string;
}

interface McpFormValues {
  name?: string;
  transport: string;
  command: string;
  args?: string[];
  env?: EnvItem[];
}

const TRANSPORT_COLOR: Record<string, string> = { stdio: 'blue', sse: 'green', http: 'purple' };
/** 传输方式的中文展示名（值仍是协议层字段，仅用户可见文案中文化） */
const TRANSPORT_LABEL: Record<string, string> = { stdio: '本地进程', sse: 'HTTP 流', http: 'HTTP' };

export default function McpPage() {
  const [servers, setServers] = useState<ConnectorServer[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<ConnectorServer | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<McpFormValues>();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setServers(await get<ConnectorServer[]>('/connectors'));
      setLoadError(null);
    } catch (e) {
      // 读连接器列表失败（后端启动中 / mcp 配置文件损坏）必须给重试出口：
      // 原来只有 finally，失败后页面显示「还没有配置连接器」，看起来像配置被清空了。
      setLoadError((e as Error).message);
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
      env: Object.entries(s.env || {}).map(([key, value]) => ({ key, value })),
    });
    setModalOpen(true);
  };

  const save = async () => {
    const v = await form.validateFields();
    setSaving(true);
    try {
      const env: Record<string, string> = {};
      (v.env || []).forEach(({ key, value }) => {
        if (key && key.trim()) env[key.trim()] = value ?? '';
      });
      const payload = { transport: v.transport, command: v.command, args: v.args || [], env };
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
    const color = pickAvatarColor(s.name);
    const cmd = s.command || '—';
    const args = (s.args || []).join(' ');
    const envKeys = Object.keys(s.env || {});
    return (
        <Card size="small" hoverable style={{ height: '100%', display: 'flex', flexDirection: 'column', position: 'relative' }}>
          <Tag color={TRANSPORT_COLOR[t] || 'default'} style={{ position: 'absolute', top: 8, right: 8, margin: 0, fontSize: 11 }}>
            {TRANSPORT_LABEL[t] || t}
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
              {envKeys.length > 0 && (
                <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block' }} ellipsis title={envKeys.join(', ')}>
                  ENV: {envKeys.join(', ')}
                </Typography.Text>
              )}
            </div>
          </div>
          <div style={{ flex: 1 }} />
          <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ color: 'var(--label-3)', fontSize: 12 }}>工具名带 {s.name}_ 前缀</span>
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
    );
  };

  return (
    <PageLayout
      title="连接器"
      description="接入外部服务器能力：工具以「{连接器名}_」前缀自动对专家可用，增删改后下次对话生效"
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建连接器</Button>
      }
    >
      {loadError ? (
        <ErrorState description={loadError} onRetry={load} />
      ) : (
        <EntityGrid
          items={servers}
          loading={loading}
          emptyText="还没有配置连接器"
          renderItem={renderConnector}
        />
      )}

      <Modal
        title={editing ? `编辑连接器：${editing.name}` : '新建连接器'}
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
          <Form.Item name="transport" label="传输方式" rules={[{ required: true }]}>
            <Select
              options={[
                { value: 'stdio', label: '本地进程（本机运行）' },
                { value: 'sse', label: 'HTTP 流（实时推送）' },
                { value: 'http', label: 'HTTP' },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="command" label="命令"
            rules={[({ getFieldValue }) => ({
              validator: (_, v) => (
                getFieldValue('transport') === 'stdio' && !(v || '').trim()
                  ? Promise.reject(new Error('本地进程方式需要填写命令'))
                  : Promise.resolve()
              ),
            })]}
          >
            <Input placeholder="可执行文件路径，如 /path/to/python" />
          </Form.Item>
          <Form.Item name="args" label="参数">
            <Select mode="tags" placeholder="回车添加参数（可选）" open={false} suffixIcon={null} />
          </Form.Item>
          <Form.Item label="环境变量" style={{ marginBottom: 4 }}>
            <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 8 }}>
              注入到连接器进程（本地进程方式生效）；值仅存本机，不在卡片上显示。
            </Typography.Paragraph>
            <Form.List name="env">
              {(fields, { add, remove }) => (
                <>
                  {fields.map(({ key, name, ...restField }) => (
                    <div key={key} style={{ display: 'flex', gap: 8, marginBottom: 8, alignItems: 'flex-start' }}>
                      <Form.Item
                        {...restField}
                        name={[name, 'key']}
                        style={{ marginBottom: 0, flex: 1 }}
                        rules={[
                          { required: true, message: '键名' },
                          { pattern: /^[A-Za-z_][A-Za-z0-9_]*$/, message: '字母/数字/下划线' },
                        ]}
                      >
                        <Input placeholder="键名，如 GITHUB_TOKEN" />
                      </Form.Item>
                      <Form.Item {...restField} name={[name, 'value']} style={{ marginBottom: 0, flex: 2 }}>
                        <Input placeholder="值（可选）" />
                      </Form.Item>
                      <Button type="text" icon={<MinusCircleOutlined />} onClick={() => remove(name)} />
                    </div>
                  ))}
                  <Button type="dashed" onClick={() => add()} block icon={<PlusOutlined />}>
                    添加环境变量
                  </Button>
                </>
              )}
            </Form.List>
          </Form.Item>
        </Form>
      </Modal>
    </PageLayout>
  );
}
