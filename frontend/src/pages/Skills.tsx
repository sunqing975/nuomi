import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Avatar, Button, Card, Empty, Input, List, Modal, Popconfirm, Select, Space, Switch, Tabs,
  Tag, Typography, Upload, message,
} from 'antd';
import { CloudUploadOutlined, DeleteOutlined, DownloadOutlined, GithubOutlined, ReloadOutlined } from '@ant-design/icons';
import {
  del, get, patch, post, upload, type Skill, type SkillHubItem, type SkillPackage,
} from '../api';
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
  const KIND_META = {
    builtin: { color: 'blue', label: '内置' },
    skill: { color: 'geekblue', label: '技能' },
    package: { color: 'purple', label: '技能包' },
  } as const;

  type InstalledKind = keyof typeof KIND_META;

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
    const meta = KIND_META[it.kind];
    const desc = it.description || '—';
    const miss = (it.requires_env || []).filter(v => !envVars[v] && !(v in envVars));
    const isSkill = it.kind === 'skill' && it.ref;
    const isPackage = it.kind === 'package' && it.ref;
    return (
      <List.Item>
        <Card size="small" style={{ height: '100%', display: 'flex', flexDirection: 'column', position: 'relative' }}>
          <Tag color={meta.color} style={{ position: 'absolute', top: 8, right: 8, margin: 0, fontSize: 11 }}>
            {meta.label}
          </Tag>
          <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start', paddingRight: 44 }}>
            {it.icon_url ? (
              <img src={it.icon_url} alt="" width={40} height={40}
                style={{ borderRadius: 8, objectFit: 'cover', flexShrink: 0 }} />
            ) : initialAvatarOf(it.name)}
            <div style={{ flex: 1, minWidth: 0 }}>
              <Typography.Text strong ellipsis style={{ display: 'block' }} title={it.name}>
                {it.name}
              </Typography.Text>
              <Space size={4} wrap style={{ marginTop: 2 }}>
                {it.kind === 'package' && it.skill_count != null && (
                  <Tag style={{ marginInlineEnd: 0 }}>{it.skill_count} 技能</Tag>)}
                {isSkill && miss.length > 0 && (
                  <Tag color="orange" style={{ marginInlineEnd: 0 }} title={`缺少：${miss.join(', ')}`}>
                    需配置 {miss.join(', ')}
                  </Tag>
                )}
              </Space>
            </div>
          </div>
          <Typography.Paragraph
            type="secondary" style={{ fontSize: 12, marginTop: 8, marginBottom: 0, flex: 1 }}
            ellipsis={{ rows: 3, tooltip: desc }}
          >
            {desc}
          </Typography.Paragraph>
          <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            {it.kind === 'builtin' ? (
              <span style={{ color: 'var(--label-3)', fontSize: 12 }}>随 harness 注入 · 只读</span>
            ) : isSkill ? (
              <span style={{ color: 'var(--label-3)', fontSize: 12 }}>
                {it.requires_env?.length ? (miss.length ? '密钥待配置' : '密钥已配置') : '无需密钥'}
              </span>
            ) : (
              <span style={{ color: 'var(--label-3)', fontSize: 12 }}>包级整体启停</span>
            )}
            {it.kind === 'builtin' ? (
              <Typography.Text style={{ fontSize: 11, color: 'var(--label-3)' }}>
                lang: {it.lang || '—'}
              </Typography.Text>
            ) : isSkill ? (
              <Space size={4}>
                <Switch size="small" checked={it.enabled}
                  onChange={v => toggleSkill(it.ref as Skill, v)} />
                <Popconfirm
                  title="删除技能？" description="将删除技能目录，不可恢复"
                  okText="删除" cancelText="取消"
                  onConfirm={() => removeSkill(it.ref as Skill)}
                >
                  <Button size="small" type="text" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              </Space>
            ) : isPackage ? (
              <Space size={4}>
                <Switch size="small" checked={it.enabled}
                  onChange={v => togglePackage(it.ref as SkillPackage, v)} />
                <Popconfirm
                  title="删除技能包？" description="将删除包目录及全部技能，不可恢复"
                  okText="删除" cancelText="取消"
                  onConfirm={() => removePackage(it.ref as SkillPackage)}
                >
                  <Button size="small" type="text" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              </Space>
            ) : null}
          </div>
        </Card>
      </List.Item>
    );
  };

  const AVATAR_COLORS = ['#f59e0b', '#3b82f6', '#10b981', '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316'];

  const initialAvatarOf = (name: string) => {
    const ch = (name[0] || '?').toUpperCase();
    const color = AVATAR_COLORS[(name.charCodeAt(0) || 0) % AVATAR_COLORS.length];
    return <Avatar size={40} style={{ backgroundColor: color, flexShrink: 0 }}>{ch}</Avatar>;
  };

  const renderHubItem = (item: SkillHubItem) => {
    const installingNow = installing === item.slug;
    const name = item.display_name || item.slug;
    const desc = item.summary || item.description || '—';
    return (
      <List.Item>
        <Card size="small" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
            {item.icon_url ? (
              <img src={item.icon_url} alt="" width={40} height={40}
                style={{ borderRadius: 8, objectFit: 'cover', flexShrink: 0 }} />
            ) : initialAvatarOf(name)}
            <div style={{ flex: 1, minWidth: 0 }}>
              <Typography.Text strong ellipsis style={{ display: 'block' }} title={name}>
                {name}
              </Typography.Text>
              <Space size={4} wrap style={{ marginTop: 2 }}>
                <Typography.Text code style={{ fontSize: 11 }}>{item.slug}</Typography.Text>
                {item.requires_api_key && (
                  <Tag color="orange" style={{ marginInlineEnd: 0 }}
                    title="该技能需要 API Key，安装后在「设置 → 环境变量」配置">
                    需 API Key
                  </Tag>
                )}
                {hubTab === 'skillsets' && item.skill_count != null && (
                  <Tag color="blue" style={{ marginInlineEnd: 0 }}>{item.skill_count} 技能</Tag>)}
              </Space>
            </div>
          </div>
          <Typography.Paragraph
            type="secondary" style={{ fontSize: 12, marginTop: 8, marginBottom: 0, flex: 1 }}
            ellipsis={{ rows: 3, tooltip: desc }}
          >
            {desc}
          </Typography.Paragraph>
          <div style={{ marginTop: 10 }}>
            <Button size="small" type="primary" block loading={installingNow}
              icon={<DownloadOutlined />}
              onClick={() => (hubTab === 'skills' ? installSkill(item) : installPackage(item))}>
              {hubTab === 'skills' ? '安装技能' : '安装技能包'}
            </Button>
          </div>
        </Card>
      </List.Item>
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
                <List
                  grid={{ gutter: 12, xs: 1, sm: 2, md: 3, lg: 3, xl: 4, xxl: 5 }}
          className="nuomi-grid"
                  dataSource={installedItems} loading={loading} size="small"
                  locale={{ emptyText: <Empty description="没有匹配的已安装项" /> }}
                  renderItem={renderInstalledItem}
                />
              </>
            ),
          },
          {
            key: 'hub', label: 'SkillHub 市场',
            children: (
              <Card size="small" title={null}>
                <Space style={{ marginBottom: 12 }}>
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
                </Space>
                <Tabs
                  size="small" activeKey={hubTab}
                  onChange={k => setHubTab(k as 'skills' | 'skillsets')}
                  items={[
                    { key: 'skills', label: '技能' },
                    { key: 'skillsets', label: '技能包（技能集）' },
                  ]}
                />
                <List
                  grid={{ gutter: 12, xs: 1, sm: 2, md: 3, lg: 3, xl: 4, xxl: 5 }}
          className="nuomi-grid"
                  dataSource={hubItems} loading={hubLoading} size="small"
                  locale={{ emptyText: <Empty description="暂无结果，换个关键词试试" /> }}
                  renderItem={renderHubItem}
                />
              </Card>
            ),
          },
        ]}
      />
      <Typography.Paragraph type="secondary" style={{ marginTop: 10, fontSize: 12 }}>
        技能目录：<Typography.Text code>工作区/skills/&lt;技能名&gt;/SKILL.md</Typography.Text>；
        技能包目录：<Typography.Text code>工作区/skill_packages/&lt;包名&gt;/skills/&lt;技能名&gt;/</Typography.Text>。
        内置技能（apple-notes / plan / 提醒 等）随 harness 注入专家。
      </Typography.Paragraph>
    </PageLayout>
  );
}
