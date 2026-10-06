import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Avatar, Button, Card, Input, Modal, Popconfirm, Select, Space, Switch, Tabs,
  Tag, Typography, Upload, message,
} from 'antd';
import { CloudUploadOutlined, DeleteOutlined, DownloadOutlined, GithubOutlined, ReloadOutlined } from '@ant-design/icons';
import {
  del, get, patch, post, upload, type Skill, type SkillHubItem, type SkillPackage,
} from '../api';
import EntityGrid from '../components/EntityGrid';
import PageLayout from '../components/PageLayout';

export default function SkillsPage() {
  // —— 已安装 ——
  const [skills, setSkills] = useState<Skill[]>([]);
  const [builtins, setBuiltins] = useState<Skill[]>([]);
  const [packages, setPackages] = useState<SkillPackage[]>([]);
  const [envVars, setEnvVars] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  // —— 市场 ——
  const [hubTab, setHubTab] = useState<'skills' | 'skillsets'>('skills');
  const [query, setQuery] = useState('');
  const [hubItems, setHubItems] = useState<SkillHubItem[]>([]);
  const [hubLoading, setHubLoading] = useState(false);
  const [installing, setInstalling] = useState<string | null>(null);
  const [gitOpen, setGitOpen] = useState(false);
  const [gitUrl, setGitUrl] = useState('');
  const [gitLoading, setGitLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [s, p, b, e] = await Promise.all([
        get<Skill[]>('/skills'),
        get<SkillPackage[]>('/skill-packages'),
        get<Skill[]>('/skills/builtin'),
        get<Record<string, string>>('/settings/env'),
      ]);
      setSkills(s);
      setPackages(p);
      setBuiltins(b);
      setEnvVars(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const importSkillZip = async (file: File) => {
    try {
      const r = await upload<{ ok: boolean; skill: Skill }>('/skills/import', file);
      message.success(`技能「${r.skill.name}」导入成功`);
      load();
    } catch (e) {
      message.error(`导入失败：${(e as Error).message}`);
    }
  };

  const importSkillGit = async () => {
    const url = gitUrl.trim();
    if (!url) { message.warning('请输入 git 仓库地址'); return; }
    setGitLoading(true);
    try {
      const r = await post<{ ok: boolean; skill: Skill }>('/skills/import-git', { url });
      message.success(`技能「${r.skill.name}」导入成功`);
      setGitOpen(false);
      setGitUrl('');
      load();
    } catch (e) {
      message.error(`导入失败：${(e as Error).message}`);
    } finally {
      setGitLoading(false);
    }
  };

  const searchHub = useCallback(async (q: string, tab: 'skills' | 'skillsets') => {
    setHubLoading(true);
    try {
      if (tab === 'skills') {
        setHubItems(await get<SkillHubItem[]>(`/skillhub/search?q=${encodeURIComponent(q)}&page_size=50`));
      } else {
        setHubItems(await get<SkillHubItem[]>(`/skillhub/skillsets?q=${encodeURIComponent(q)}&page_size=50`));
      }
    } finally {
      setHubLoading(false);
    }
  }, []);

  useEffect(() => {
    searchHub('', hubTab);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hubTab]);

  const toggleSkill = async (s: Skill, enabled: boolean) => {
    await patch(`/skills/${s.name}`, { enabled });
    message.success(enabled ? '已启用（重启专家实例生效）' : '已停用');
    load();
  };

  const removeSkill = async (s: Skill) => {
    try {
      await del(`/skills/${s.name}`);
      message.success(`技能 ${s.name} 已删除`);
      load();
    } catch (e) {
      message.error(`删除失败：${(e as Error).message}`);
    }
  };

  const togglePackage = async (p: SkillPackage, enabled: boolean) => {
    await patch(`/skill-packages/${p.id}`, { enabled });
    message.success(enabled ? '包已启用（重启专家实例生效）' : '包已停用');
    load();
  };

  const removePackage = async (p: SkillPackage) => {
    try {
      await del(`/skill-packages/${p.id}`);
      message.success(`技能包 ${p.name} 已删除`);
      load();
    } catch (e) {
      message.error(`删除失败：${(e as Error).message}`);
    }
  };

  const installSkill = async (item: SkillHubItem) => {
    setInstalling(item.slug);
    try {
      await post('/skills/install', { slug: item.slug });
      message.success(`技能 ${item.display_name} 已安装`);
      if (item.requires_api_key) {
        message.warning('该技能需要 API Key，请到「设置 → 环境变量」配置后重启对话生效', 5);
      }
      load();
    } catch (e) {
      message.error(`安装失败：${(e as Error).message}`);
    } finally {
      setInstalling(null);
    }
  };

  const installPackage = async (item: SkillHubItem) => {
    setInstalling(item.slug);
    try {
      const p = await post<SkillPackage>('/skill-packages/from-skillhub', { slug: item.slug });
      message.success(`技能包 ${p.name} 已安装（${p.skill_count} 个技能）`);
      load();
    } catch (e) {
      message.error(`安装失败：${(e as Error).message}`);
    } finally {
      setInstalling(null);
    }
  };

  const missingEnv = (s: Skill) => (s.requires_env || []).filter(v => !envVars[v] && !(v in envVars));

  // —— 已安装卡片（内置/技能/技能包 统一平铺） ——
  type InstalledKind = 'builtin' | 'skill' | 'package';

  interface InstalledItem {
    key: string;
    kind: InstalledKind;
    name: string;
    description: string;
    lang?: string;
    enabled?: boolean;
    skill_count?: number | null;
    icon_url?: string;
    requires_env?: string[];
    ref: Skill | SkillPackage | null;
  }

  const [kindFilter, setKindFilter] = useState<'all' | InstalledKind>('all');
  const [installedQuery, setInstalledQuery] = useState('');

  const installedItems = useMemo(() => {
    const items: InstalledItem[] = [
      ...builtins.map(s => ({
        key: `b:${s.name}`, kind: 'builtin' as const, name: s.name, description: s.description,
        lang: s.lang, ref: null,
      })),
      ...skills.map(s => ({
        key: `s:${s.name}`, kind: 'skill' as const, name: s.name, description: s.description,
        enabled: s.enabled, requires_env: s.requires_env, ref: s,
      })),
      ...packages.map(p => ({
        key: `p:${p.id}`, kind: 'package' as const, name: p.name, description: p.description,
        enabled: p.enabled, skill_count: p.skill_count, icon_url: p.icon_url, ref: p,
      })),
    ];
    const q = installedQuery.trim().toLowerCase();
    return items.filter(it =>
      (kindFilter === 'all' || it.kind === kindFilter) &&
      (!q || it.name.toLowerCase().includes(q) || (it.description || '').toLowerCase().includes(q)));
  }, [builtins, skills, packages, kindFilter, installedQuery]);

  const renderInstalledItem = (it: InstalledItem) => {
    const desc = it.description || '—';
    const miss = (it.requires_env || []).filter(v => !envVars[v] && !(v in envVars));
    const isSkill = it.kind === 'skill' && it.ref;
    const isPackage = it.kind === 'package' && it.ref;
    const enabled = it.enabled ?? true;
    const attr =
      it.kind === 'builtin'
        ? '内置 · 随 harness 注入'
        : it.kind === 'package'
          ? `技能包 · ${it.skill_count ?? 0} 个技能`
          : miss.length > 0
            ? `技能 · 密钥待配置：${miss.join(', ')}`
            : it.requires_env?.length
              ? '技能 · 密钥已配置'
              : '技能 · 无需密钥';
    return (
      <Card
        size="small"
        hoverable
        style={enabled ? { height: '100%' } : { opacity: 0.75, height: '100%' }}
        title={
          <Space>
            {it.icon_url ? (
              <img src={it.icon_url} alt="" width={24} height={24}
                style={{ borderRadius: 4, objectFit: 'cover', flexShrink: 0 }} />
            ) : (
              <span style={{ fontSize: 16, flexShrink: 0 }}>{initialAvatarOf(it.name, 24)}</span>
            )}
            <span>{it.name}</span>
            {!enabled && <Tag color="default">已停用</Tag>}
          </Space>
        }
        extra={
          it.kind === 'builtin' ? null : (
            <Popconfirm
              title={isSkill ? '删除技能？' : '删除技能包？'}
              description={isSkill ? '将删除技能目录，不可恢复' : '将删除包目录及全部技能，不可恢复'}
              okText="删除" cancelText="取消"
              onConfirm={() => (isSkill ? removeSkill(it.ref as Skill) : removePackage(it.ref as SkillPackage))}
            >
              <Button size="small" type="text" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          )
        }
      >
        <Typography.Paragraph type="secondary" ellipsis={{ rows: 2 }} style={{ fontSize: 13, minHeight: 40, marginBottom: 8 }}>
          {desc}
        </Typography.Paragraph>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>{attr}</Typography.Text>
          {it.kind === 'builtin' ? null : (
            <span>
              <Switch size="small" checked={enabled}
                onChange={v => (isSkill ? toggleSkill(it.ref as Skill, v) : togglePackage(it.ref as SkillPackage, v))} />
              <Typography.Text type="secondary" style={{ fontSize: 12, marginLeft: 6 }}>
                {enabled ? '已启用' : '已停用'}
              </Typography.Text>
            </span>
          )}
        </div>
      </Card>
    );
  };

  const AVATAR_COLORS = ['#f59e0b', '#3b82f6', '#10b981', '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316'];

  const initialAvatarOf = (name: string, size = 40) => {
    const ch = (name[0] || '?').toUpperCase();
    const color = AVATAR_COLORS[(name.charCodeAt(0) || 0) % AVATAR_COLORS.length];
    return <Avatar size={size} style={{ backgroundColor: color, flexShrink: 0 }}>{ch}</Avatar>;
  };

  const renderHubItem = (item: SkillHubItem) => {
    const installingNow = installing === item.slug;
    const name = item.display_name || item.slug;
    const desc = item.summary || item.description || '—';
    return (
      <Card
        size="small"
        hoverable
        style={{ height: '100%' }}
        title={<Space>{item.icon_url ? (
          <img src={item.icon_url} alt="" width={24} height={24}
            style={{ borderRadius: 4, objectFit: 'cover', flexShrink: 0 }} />
        ) : initialAvatarOf(name, 24)}<span>{name}</span></Space>}
        extra={
          item.requires_api_key && (
            <Tag color="orange" style={{ marginInlineEnd: 0 }}
              title="该技能需要 API Key，安装后在「设置 → 环境变量」配置">
              需 API Key
            </Tag>
          )
        }
      >
        <Typography.Paragraph type="secondary" ellipsis={{ rows: 2 }} style={{ fontSize: 13, minHeight: 40, marginBottom: 8 }}>
          {desc}
        </Typography.Paragraph>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {hubTab === 'skills' ? '技能' : '技能包'}
            {hubTab === 'skillsets' && item.skill_count != null ? ` · ${item.skill_count} 个技能` : ''}
          </Typography.Text>
          <Button size="small" type="primary" loading={installingNow}
            icon={<DownloadOutlined />}
            onClick={() => (hubTab === 'skills' ? installSkill(item) : installPackage(item))}>
            {hubTab === 'skills' ? '安装技能' : '安装技能包'}
          </Button>
        </div>
      </Card>
    );
  };

  return (
    <PageLayout
      title="技能"
      description="技能 / 技能包管理：可导入本地包，或从 SkillHub 市场安装"
    >
      <Tabs
        items={[
          {
            key: 'installed', label: '已安装',
            children: (
              <>
                <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
                  <Select
                    value={kindFilter}
                    onChange={setKindFilter}
                    style={{ width: 120 }}
                    options={[
                      { value: 'all', label: '全部类型' },
                      { value: 'builtin', label: '内置' },
                      { value: 'skill', label: '技能' },
                      { value: 'package', label: '技能包' },
                    ]}
                  />
                  <Input.Search
                    placeholder="搜索名称 / 描述"
                    allowClear style={{ width: 240 }}
                    value={installedQuery}
                    onChange={e => setInstalledQuery(e.target.value)}
                  />
                  <div style={{ flex: 1 }} />
                  <Button icon={<GithubOutlined />} onClick={() => setGitOpen(true)}>从 Git 导入</Button>
                  <Upload
                    accept=".zip"
                    showUploadList={false}
                    beforeUpload={(file) => {
                      importSkillZip(file);
                      return false; // 手动上传，阻止 antd 自动提交
                    }}
                  >
                    <Button icon={<CloudUploadOutlined />}>导入技能 zip</Button>
                  </Upload>
                </div>
                <Modal
                  title="从 Git 仓库导入技能"
                  open={gitOpen}
                  onOk={importSkillGit}
                  confirmLoading={gitLoading}
                  onCancel={() => { setGitOpen(false); setGitUrl(''); }}
                  okText="导入" cancelText="取消"
                >
                  <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 4 }}>
                    浅克隆仓库并导入工作区 <Typography.Text code>skills/</Typography.Text>（需根目录含 SKILL.md）。
                    支持 https:// / ssh:// / git@ 地址，体积上限 50MB。
                  </Typography.Paragraph>
                  <Input
                    placeholder="https://github.com/user/skill-repo.git"
                    value={gitUrl}
                    onChange={e => setGitUrl(e.target.value)}
                    onPressEnter={importSkillGit}
                    autoFocus
                  />
                </Modal>
                <EntityGrid
                  items={installedItems}
                  loading={loading}
                  emptyText="没有匹配的已安装项"
                  renderItem={renderInstalledItem}
                />
              </>
            ),
          },
          {
            key: 'hub', label: 'SkillHub 市场',
            children: (
              <>
                <div style={{ display: 'flex', gap: 12, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
                  <Input.Search
                    placeholder={hubTab === 'skills'
                      ? '搜索技能（如：翻译、编程）' : '搜索技能包（技能集）'}
                    allowClear style={{ width: 320 }} defaultValue=""
                    onSearch={q => searchHub(q, hubTab)}
                  />
                  <Button icon={<ReloadOutlined />} onClick={() => searchHub('', hubTab)} />
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    来源：腾讯 SkillHub 市场（api.skillhub.cn）
                  </Typography.Text>
                </div>
                <Tabs
                  size="small" activeKey={hubTab}
                  onChange={k => setHubTab(k as 'skills' | 'skillsets')}
                  items={[
                    { key: 'skills', label: '技能' },
                    { key: 'skillsets', label: '技能包（技能集）' },
                  ]}
                />
                <EntityGrid
                  items={hubItems}
                  loading={hubLoading}
                  emptyText="暂无结果，换个关键词试试"
                  renderItem={renderHubItem}
                />
              </>
            ),
          },
        ]}
      />
    </PageLayout>
  );
}
