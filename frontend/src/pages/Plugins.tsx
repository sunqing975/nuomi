import { useCallback, useEffect, useState } from 'react';
import { Button, Table, Switch, Tag, message, Typography } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { get, post, patch, type Plugin } from '../api';

export default function PluginsPage() {
  const [plugins, setPlugins] = useState<Plugin[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setPlugins(await get<Plugin[]>('/plugins'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const sync = async () => {
    const rows = await post<Plugin[]>('/plugins/sync');
    message.success(`扫描完成：${rows.length} 个插件`);
    load();
  };

  const toggle = async (p: Plugin, enabled: boolean) => {
    await patch(`/plugins/${p.plugin_id}`, { enabled });
    message.success(enabled ? '已启用（重启专家实例生效）' : '已停用');
    load();
  };

  const columns = [
    { title: '插件', dataIndex: 'name', render: (_: unknown, p: Plugin) => (
        <span><b>{p.name}</b><br /><small style={{ color: '#9ca3af' }}>{p.plugin_id}</small></span>) },
    { title: '类型', dataIndex: 'kind', width: 90, render: (k: string) => <Tag>{k || 'tool'}</Tag> },
    { title: '版本', dataIndex: 'version', width: 90, render: (v: string) => v || '—' },
    { title: '工具数', dataIndex: 'tool_count', width: 90 },
    { title: '启用', width: 90, render: (_: unknown, p: Plugin) => (
        <Switch checked={p.enabled} onChange={v => toggle(p, v)} />) },
  ];

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
        <Button icon={<ReloadOutlined />} onClick={sync} loading={loading}>重新扫描</Button>
      </div>
      <Table<Plugin>
        rowKey="plugin_id"
        columns={columns}
        dataSource={plugins}
        loading={loading}
        pagination={false}
      />
      <Typography.Paragraph type="secondary" style={{ marginTop: 10, fontSize: 12 }}>
        插件目录：<Typography.Text code>工作区/plugins/</Typography.Text>（plugin.yaml + main.py，ctx.tool 注册工具）。
        全局启停对所有专家生效；专家级绑定在「专家」页配置。
      </Typography.Paragraph>
    </>
  );
}
