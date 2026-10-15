import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Avatar, Button, Card, Dropdown, Input, Modal, Popconfirm, Space, Switch, Tag,
  Typography, message,
} from 'antd';
import {
  CloudUploadOutlined, DeleteOutlined, DownOutlined, GithubOutlined, ReloadOutlined, ShopOutlined,
} from '@ant-design/icons';
import { del, get, post, patch, upload, type Plugin } from '../api';
import EntityGrid from '../components/EntityGrid';
import PageLayout from '../components/PageLayout';

/** 插件 kind 中文化（产品不暴露英文术语） */
const KIND_LABEL: Record<string, string> = { tool: '工具插件', model: '模型插件' };

const AVATAR_COLORS = ['#f59e0b', '#3b82f6', '#10b981', '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316'];

export default function PluginsPage() {
  const [plugins, setPlugins] = useState<Plugin[]>([]);
  const [loading, setLoading] = useState(false);
  const [gitOpen, setGitOpen] = useState(false);
  const [gitUrl, setGitUrl] = useState('');
  const [gitLoading, setGitLoading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

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

  const importZip = async (file: File) => {
    try {
      const r = await upload<{ ok: boolean; plugin: Plugin }>('/plugins/import', file);
      message.success(`插件「${r.plugin.name}」导入成功`);
      load();
    } catch (e) {
      message.error(`导入失败：${(e as Error).message}`);
    }
  };

  const importGit = async () => {
    const url = gitUrl.trim();
    if (!url) { message.warning('请输入 git 仓库地址'); return; }
    setGitLoading(true);
    try {
      const r = await post<{ ok: boolean; plugin: Plugin }>('/plugins/import-git', { url });
      message.success(`插件「${r.plugin.name}」导入成功`);
      setGitOpen(false);
      setGitUrl('');
      load();
    } catch (e) {
      message.error(`导入失败：${(e as Error).message}`);
    } finally {
      setGitLoading(false);
    }
  };

  const toggle = async (p: Plugin, enabled: boolean) => {
    await patch(`/plugins/${p.plugin_id}`, { enabled });
    // 后端在 PATCH 里已自动释放实例（manager.close），下一轮对话重建即挂上新工具——
    // 不要再写「重启专家实例生效」，那会让用户以为要手动重启软件
    message.success(enabled ? '已启用，下一轮对话即生效' : '已停用，下一轮对话即生效');
    load();
  };

  const remove = async (p: Plugin) => {
    try {
      await del(`/plugins/${p.plugin_id}`);
      message.success(`插件 ${p.name} 已删除`);
      load();
    } catch (e) {
      message.error(`删除失败：${(e as Error).message}`);
    }
  };

  const renderPlugin = (p: Plugin) => {
    const color = AVATAR_COLORS[(p.plugin_id.charCodeAt(0) || 0) % AVATAR_COLORS.length];
    return (
      <Card
        size="small"
        hoverable
        style={p.enabled ? { height: '100%' } : { opacity: 0.75, height: '100%' }}
        title={
          <Space>
            <Avatar size={24} style={{ backgroundColor: color, fontSize: 12, flexShrink: 0 }}>
              {(p.name[0] || '?').toUpperCase()}
            </Avatar>
            <span>{p.name}</span>
            {!p.enabled && <Tag color="default">已停用</Tag>}
          </Space>
        }
        extra={
          <Popconfirm
            title="删除插件？"
            description="将删除插件目录与全部绑定，不可恢复"
            okText="删除" cancelText="取消"
            onConfirm={() => remove(p)}
          >
            <Button size="small" type="text" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        }
      >
        <Typography.Paragraph type="secondary" ellipsis={{ rows: 2 }} style={{ fontSize: 13, minHeight: 40, marginBottom: 8 }}>
          {p.description || '（暂无描述）'}
        </Typography.Paragraph>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {KIND_LABEL[p.kind] ?? '插件'} · v{p.version || '—'} · {p.tool_count ?? 0} 个工具
          </Typography.Text>
          <span>
            <Switch size="small" checked={p.enabled} onChange={v => toggle(p, v)} />
            <Typography.Text type="secondary" style={{ fontSize: 12, marginLeft: 6 }}>
              {p.enabled ? '已启用' : '已停用'}
            </Typography.Text>
          </span>
        </div>
      </Card>
    );
  };

  const importMenu = {
    items: [
      { key: 'git', label: '从 Git 仓库导入' },
      { key: 'zip', label: '导入 zip 文件' },
    ],
    onClick: ({ key }: { key: string }) => {
      if (key === 'git') setGitOpen(true);
      else fileRef.current?.click();
    },
  };

  return (
    <PageLayout
      title="插件"
      description="给专家挂载工具能力：安装、启停与导入"
      extra={
        <>
          <Button type="primary" icon={<ShopOutlined />} onClick={() => { window.location.hash = '#pluginMarket'; }}>插件市场</Button>
          <Dropdown menu={importMenu}>
            <Button icon={<CloudUploadOutlined />}>导入<DownOutlined /></Button>
          </Dropdown>
          <input
            ref={fileRef} type="file" accept=".zip" style={{ display: 'none' }}
            onChange={e => {
              const f = e.target.files?.[0];
              if (f) importZip(f);
              e.target.value = '';
            }}
          />
          <Button icon={<ReloadOutlined />} onClick={sync} loading={loading}>重新扫描</Button>
        </>
      }
    >
      <Modal
        title="从 Git 仓库导入插件"
        open={gitOpen}
        onOk={importGit}
        confirmLoading={gitLoading}
        onCancel={() => { setGitOpen(false); setGitUrl(''); }}
        okText="导入" cancelText="取消"
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 4 }}>
          浅克隆仓库并导入工作区 <Typography.Text code>plugins/</Typography.Text>（需根目录含 plugin.yaml）。
          支持 https:// / ssh:// / git@ 地址，体积上限 50MB。
        </Typography.Paragraph>
        <Input
          placeholder="https://github.com/user/plugin-repo.git"
          value={gitUrl}
          onChange={e => setGitUrl(e.target.value)}
          onPressEnter={importGit}
          autoFocus
        />
      </Modal>
      <EntityGrid
        items={plugins}
        loading={loading}
        emptyText="还没有插件，可导入或重新扫描"
        renderItem={renderPlugin}
      />
    </PageLayout>
  );
}
