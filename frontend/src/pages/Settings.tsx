import { useCallback, useEffect, useState } from 'react';
import {
  Button, Card, Checkbox, Form, Input, Modal, Select, Space, Table, Tabs, Tag, Typography, message,
} from 'antd';
import {
  PlusOutlined, SaveOutlined, DeleteOutlined, EyeOutlined, EyeInvisibleOutlined, ApiOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { get, post, put, type Provider } from '../api';

interface EnvRow {
  key: string;
  name: string;
  value: string;
}

function EnvTab() {
  const [rows, setRows] = useState<EnvRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const env = await get<Record<string, string>>('/settings/env');
      setRows(Object.entries(env).map(([name, value], i) => ({ key: String(i), name, value })));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const updateRow = (key: string, patch: Partial<EnvRow>) => {
    setRows(rs => rs.map(r => (r.key === key ? { ...r, ...patch } : r)));
  };

  const removeRow = (key: string) => setRows(rs => rs.filter(r => r.key !== key));

  const addRow = () => {
    setRows(rs => [...rs, { key: `new-${Date.now()}`, name: '', value: '' }]);
  };

  const save = async () => {
    const clean: Record<string, string> = {};
    for (const r of rows) {
      const name = r.name.trim();
      if (!name) continue;
      clean[name] = r.value;
    }
    setSaving(true);
    try {
      const saved = await put<Record<string, string>>('/settings/env', { values: clean });
      message.success(`已保存 ${Object.keys(saved).length} 个环境变量（下次对话生效）`);
      load();
    } catch (e) {
      message.error(`保存失败：${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  const columns = [
    {
      title: '变量名', dataIndex: 'name', width: '40%',
      render: (_: unknown, r: EnvRow) => (
        <Input
          placeholder="如 OPENAI_API_KEY"
          value={r.name}
          onChange={e => updateRow(r.key, { name: e.target.value })}
        />
      ),
    },
    {
      title: '值', dataIndex: 'value',
      render: (_: unknown, r: EnvRow) => (
        <Input.Password
          placeholder="密钥值"
          value={r.value}
          iconRender={p => (p ? <EyeOutlined /> : <EyeInvisibleOutlined />)}
          onChange={e => updateRow(r.key, { value: e.target.value })}
          visibilityToggle
        />
      ),
    },
    {
      title: '', width: 50,
      render: (_: unknown, r: EnvRow) => (
        <Button size="small" type="text" danger icon={<DeleteOutlined />}
          onClick={() => removeRow(r.key)} />
      ),
    },
  ];

  return (
    <>
      <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 0 }}>
        需要 API Key 的技能/连接器在此配置密钥（如 <Typography.Text code>OPENAI_API_KEY</Typography.Text>）。
        持久化于 <Typography.Text code>工作区/env.json</Typography.Text>，修改后下次对话生效；
        删除某行并保存即从运行环境移除该变量。
      </Typography.Paragraph>
      <Table<EnvRow>
        rowKey="key" columns={columns} dataSource={rows} size="small"
        loading={loading} pagination={false}
        locale={{ emptyText: '还没有环境变量，点击「新增变量」添加' }}
      />
      <Space style={{ marginTop: 12 }}>
        <Button icon={<PlusOutlined />} onClick={addRow}>新增变量</Button>
        <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={save}>
          保存环境变量
        </Button>
      </Space>
    </>
  );
}

/** 大模型 Provider 配置（对齐 octop providers 管理；整体保存，下次对话生效） */
function ProvidersTab() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Provider | null>(null);
  const [probing, setProbing] = useState(false);
  const [candidates, setCandidates] = useState<string[]>([]);
  const [form] = Form.useForm();
  const modelValues = Form.useWatch('models', form) as string[] | undefined;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await get<{ providers: Provider[] }>('/settings/providers');
      setProviders(r.providers);
    } catch (e) {
      message.error(`加载大模型配置失败：${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const openEdit = (p?: Provider) => {
    setEditing(p ?? null);
    setCandidates([]);
    form.resetFields();
    if (p) {
      // 编辑回显：models 存的是 {id,name}[]，Select tags 需要 string[]
      form.setFieldsValue({
        ...p,
        api_key: '',
        models: (p.models || []).map(m => m.id),
      });
    } else {
      form.setFieldsValue({
        id: '', name: '', base_url: '', api_key: '', protocol: 'openai', models: [],
      });
    }
    setModalOpen(true);
  };

  /** 探测 Provider /models，拉取模型列表；默认勾选第一个作为默认模型 */
  const probe = async () => {
    const base_url = String(form.getFieldValue('base_url') || '').trim();
    const api_key = String(form.getFieldValue('api_key') || '').trim();
    if (!base_url) {
      message.warning('先填 Base URL 再探测');
      return;
    }
    setProbing(true);
    try {
      const r = await post<{ models: string[] }>('/settings/providers/probe', { base_url, api_key });
      setCandidates(r.models);
      form.setFieldsValue({ models: r.models.slice(0, 1) }); // 默认勾选第一个
      message.success(`探测到 ${r.models.length} 个模型，已默认勾选第一个`);
    } catch (e) {
      setCandidates([]);
      message.error(`探测失败：${(e as Error).message}`);
    } finally {
      setProbing(false);
    }
  };

  const save = async () => {
    setSaving(true);
    try {
      const r = await put<{ ok: boolean }>('/settings/providers', { providers });
      message.success(`已保存 ${providers.length} 个 Provider（下次对话生效）`);
      if (r.ok) load();
    } catch (e) {
      message.error(`保存失败：${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  const columns = [
    {
      title: '名称', dataIndex: 'name', width: 160,
      render: (_: unknown, p: Provider) => (
        <Space size={4}>
          <ApiOutlined style={{ color: '#1677ff' }} />
          <span>{p.name}</span>
          <Typography.Text type="secondary" style={{ fontSize: 12 }} code>{p.id}</Typography.Text>
        </Space>
      ),
    },
    {
      title: 'Base URL', dataIndex: 'base_url',
      render: (v: string) => <Typography.Text code style={{ fontSize: 12 }}>{v}</Typography.Text>,
    },
    {
      title: '模型', dataIndex: 'models',
      render: (models: { id: string }[]) => (
        <Space size={4} wrap>
          {(models || []).map(m => <Tag key={m.id} color="blue" style={{ margin: 0 }}>{m.id}</Tag>)}
        </Space>
      ),
    },
    {
      title: 'API Key', dataIndex: 'api_key', width: 140,
      render: (v: string) => v ? <Typography.Text code style={{ fontSize: 12 }}>{v}</Typography.Text>
        : <Typography.Text type="secondary" style={{ fontSize: 12 }}>未配置</Typography.Text>,
    },
    {
      title: '', width: 90,
      render: (_: unknown, p: Provider) => (
        <Space size={0}>
          <Button size="small" type="link" onClick={() => openEdit(p)}>编辑</Button>
          <Button size="small" type="link" danger
            disabled={providers.length <= 1}
            onClick={() => setProviders(ps => ps.filter(x => x.id !== p.id))}>
            删除
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <>
      <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 0 }}>
        配置对话用的大模型服务（OpenAI 兼容协议，默认 DeepSeek）。API Key 明文存于
        <Typography.Text code>工作区/providers.json</Typography.Text>（仓库外），列表展示脱敏。
        修改后下次对话生效；模型在对话框工具条 per-turn 选择（不绑专家）。
      </Typography.Paragraph>
      <Table<Provider>
        rowKey="id" columns={columns} dataSource={providers} size="small"
        loading={loading} pagination={false}
        locale={{ emptyText: '还没有 Provider，点击「新增 Provider」配置' }}
      />
      <Space style={{ marginTop: 12 }}>
        <Button icon={<PlusOutlined />} onClick={() => openEdit()}>新增 Provider</Button>
        <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={save} disabled={providers.length === 0}>
          保存大模型配置
        </Button>
      </Space>

      <Modal
        open={modalOpen}
        title={editing ? `编辑 Provider · ${editing.name}` : '新增 Provider'}
        onCancel={() => setModalOpen(false)}
        onOk={async () => {
          const values = await form.validateFields();
          const pid = String(values.id || '').trim();
          const name = String(values.name || '').trim() || pid;
          const models = (values.models || []).filter(Boolean).map((mid: string) => ({ id: mid, name: mid }));
          const item: Provider = {
            id: pid, name, base_url: String(values.base_url || '').trim(),
            api_key: String(values.api_key || '').trim(), protocol: values.protocol || 'openai',
            models,
          };
          if (editing) {
            // 编辑：api_key 留空 = 保持原值（GET 返回的是脱敏串，不能回写）
            if (!item.api_key) item.api_key = '';
            setProviders(ps => ps.map(x => (x.id === editing.id ? item : x)));
          } else {
            setProviders(ps => [...ps, item]);
          }
          setModalOpen(false);
        }}
        destroyOnClose
      >
        <Form form={form} layout="vertical" style={{ marginTop: 8 }}>
          <Form.Item name="id" label="ID" rules={[{ required: true, message: 'Provider ID 必填' }]}>
            <Input placeholder="如 llm" disabled={!!editing} />
          </Form.Item>
          <Form.Item name="name" label="名称"><Input placeholder="如 DeepSeek 主服务" /></Form.Item>
          <Form.Item name="base_url" label="Base URL" rules={[{ required: true, message: 'Base URL 必填' }]}>
            <Input placeholder="https://api.deepseek.com" />
          </Form.Item>
          <Form.Item name="api_key" label="API Key"
            extra={editing ? '留空 = 保持原值' : undefined}>
            <Input.Password placeholder={editing ? '留空保持原值' : 'sk-…'} autoComplete="off" />
          </Form.Item>
          <Form.Item name="protocol" label="协议" initialValue="openai">
            <Select options={[{ value: 'openai', label: 'OpenAI 兼容' }]} />
          </Form.Item>
          <Space style={{ marginBottom: 4 }}>
            <Button size="small" icon={<ThunderboltOutlined />} loading={probing} onClick={probe}>
              探测模型
            </Button>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {candidates.length > 0
                ? `探测到 ${candidates.length} 个模型，勾选后作为本 Provider 可用模型`
                : editing
                  ? '可手动输入模型，或重新探测'
                  : '填 Base URL / API Key 后点「探测模型」，默认勾选第一个'}
            </Typography.Text>
          </Space>
          {candidates.length > 0 && (
            <Checkbox.Group
              style={{ display: 'flex', flexWrap: 'wrap', gap: 4, maxHeight: 160, overflow: 'auto', marginBottom: 4 }}
              options={candidates.map(c => ({ label: c, value: c }))}
              value={modelValues ?? []}
              onChange={vals => form.setFieldsValue({ models: vals })}
            />
          )}
          <Form.Item name="models" label="模型" rules={[{ required: true, message: '至少勾选/填写一个模型' }]}>
            <Select mode="tags" placeholder="输入模型名后回车，如 deepseek-chat" open={false} suffixIcon={null} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

export default function SettingsPage() {
  return (
    <Card size="small" title={<b style={{ fontSize: 14 }}>设置</b>}>
      <Tabs
        defaultActiveKey="models"
        items={[
          { key: 'models', label: '大模型', children: <ProvidersTab /> },
          { key: 'env', label: '环境变量', children: <EnvTab /> },
        ]}
      />
    </Card>
  );
}
