import { useCallback, useEffect, useState } from 'react';
import { Button, Popconfirm, Table, Switch, Tag, message, Typography } from 'antd';
import { DeleteOutlined, ReloadOutlined } from '@ant-design/icons';
import { del, get, post, patch, type Plugin } from '../api';

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

  const remove = async (p: Plugin) => {
    try {
      await del(`/plugins/${p.plugin_id}`);
      message.success(`插件 ${p.plugin_id} 已删除`);
      load();
    } catch (e) {
      message.error(`删除失败：${(e as Error).message}`);
    }
  };

  const columns = [
    { title: '插件', dataIndex: 'name', render: (_: unknown, p: Plugin) => (
        <span><b>{p.name}</b><br /><small style={{ color: '#9ca3af' }}>{p.plugin_id}</small></span>) },
    { title: '类型', dataIndex: 'kind', width: 90, render: (k: string) => <Tag>{k || 'tool'}</Tag> },
    { title: '版本', dataIndex: 'version', width: 90, render: (v: string) => v || '—' },
    { title: '工具数', dataIndex: 'tool_count', width: 90 },
    { title: '启用', width: 130, render: (_: unknown, p: Plugin) => (
        p.model_plugin ? (
          <span>
            <Tag color={p.enabled ? 'orange' : 'default'} style={{ marginRight: 4 }}>
              {p.enabled ? '启用中' : '已停用'}
            </Tag>
            <small style={{ color: '#9ca3af' }}>桌宠页控制</small>
          </span>
        ) : (
          <Switch checked={p.enabled} onChange={v => toggle(p, v)} />
        )) },
    { title: '操作', width: 70, render: (_: unknown, p: Plugin) => (
        p.model_plugin ? (
          <small style={{ color: '#d1d5db' }}>随模型删除</small>
        ) : (
          <Popconfirm
            title="删除插件？"
            description="将删除插件目录与全部绑定，不可恢复"
            okText="删除" cancelText="取消"
            onConfirm={() => remove(p)}
          >
            <Button size="small" type="text" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        )) },
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
