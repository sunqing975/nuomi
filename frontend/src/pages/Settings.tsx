import { useCallback, useEffect, useState } from 'react';
import { Button, Card, Input, Space, Table, Typography, message } from 'antd';
import { PlusOutlined, SaveOutlined, DeleteOutlined, EyeOutlined, EyeInvisibleOutlined } from '@ant-design/icons';
import { get, put } from '../api';

interface EnvRow {
  key: string;
  name: string;
  value: string;
}

export default function SettingsPage() {
  const [rows, setRows] = useState<EnvRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [visible, setVisible] = useState<Record<string, boolean>>({});

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
        <Space.Compact style={{ width: '100%' }}>
          <Input.Password
            placeholder="密钥值"
            value={r.value}
            iconRender={p => (p ? <EyeOutlined /> : <EyeInvisibleOutlined />)}
            onChange={e => updateRow(r.key, { value: e.target.value })}
            visibilityToggle
          />
        </Space.Compact>
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
    <Card
      size="small"
      title={<b style={{ fontSize: 14 }}>环境变量（应用设置）</b>}
      extra={<Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {Object.keys(rows.filter(r => r.name.trim())).length} 个已配置
      </Typography.Text>}
    >
      <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 0 }}>
        需要 API Key 的技能/连接器在此配置密钥（如 <Typography.Text code>OPENAI_API_KEY</Typography.Text>）。
        持久化于 <Typography.Text code>工作区/env.json</Typography.Text>，修改后下次对话生效；
        与 octop 应用设置的环境变量一致。删除某行并保存即从运行环境移除该变量。
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
    </Card>
  );
}
