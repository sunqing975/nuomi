import { useCallback, useEffect, useState } from 'react';
import {
  Button, Card, Empty, Input, List, Modal, Popconfirm, Space, Switch, Table, Tabs,
  Tag, Typography, Upload, message,
} from 'antd';
import { CloudUploadOutlined, DeleteOutlined, DownloadOutlined, GithubOutlined, ReloadOutlined } from '@ant-design/icons';
import {
  del, get, patch, post, upload, type Skill, type SkillHubItem, type SkillPackage,
} from '../api';

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

  const skillColumns = [
    { title: '技能', dataIndex: 'name', render: (n: string) => <b>{n}</b> },
    { title: '描述', dataIndex: 'description', render: (d: string) => (
        <span style={{ color: '#6b7280' }}>{d || '—'}</span>),
    },
    { title: '密钥', width: 120, render: (_: unknown, s: Skill) => {
        const miss = missingEnv(s);
        if (!s.requires_env || s.requires_env.length === 0) return <span style={{ color: '#9ca3af' }}>—</span>;
        return miss.length > 0 ? (
          <Tag color="orange" title={`缺少：${miss.join(', ')}`}>需配置 {miss.join(', ')}</Tag>
        ) : (
          <Tag color="green">已配置</Tag>
        );
      },
    },
    { title: '启用', width: 90, render: (_: unknown, s: Skill) => (
        <Switch checked={s.enabled} onChange={v => toggleSkill(s, v)} />),
    },
    { title: '操作', width: 70, render: (_: unknown, s: Skill) => (
        <Popconfirm
          title="删除技能？"
          description="将删除技能目录，不可恢复"
          okText="删除" cancelText="取消"
          onConfirm={() => removeSkill(s)}
        >
          <Button size="small" type="text" danger icon={<DeleteOutlined />} />
        </Popconfirm>),
    },
  ];

  const builtinColumns = [
    { title: '内置技能', dataIndex: 'name', render: (n: string) => <span><b>{n}</b> <Tag color="blue">内置</Tag></span> },
    { title: '语言', dataIndex: 'lang', width: 80, render: (l: string) => l || '—' },
    { title: '描述', dataIndex: 'description', render: (d: string) => (
        <span style={{ color: '#6b7280' }}>{d || '—'}</span>),
    },
    { title: '说明', width: 220, render: () => (
        <span style={{ color: '#9ca3af', fontSize: 12 }}>随 harness 注入，只读</span>),
    },
  ];

  const packageColumns = [
    { title: '技能包', dataIndex: 'name', render: (n: string) => <b>{n}</b> },
    { title: '描述', dataIndex: 'description', render: (d: string) => (
        <span style={{ color: '#6b7280' }}>{d || '—'}</span>),
    },
    { title: '技能', width: 70, dataIndex: 'skill_count',
      render: (c: number) => <Tag color="blue">{c} 个</Tag> },
    { title: '启用（包级）', width: 110, render: (_: unknown, p: SkillPackage) => (
        <Switch checked={p.enabled} onChange={v => togglePackage(p, v)} />),
    },
    { title: '操作', width: 70, render: (_: unknown, p: SkillPackage) => (
        <Popconfirm
          title="删除技能包？"
          description="将删除包目录及全部技能，不可恢复"
          okText="删除" cancelText="取消"
          onConfirm={() => removePackage(p)}
        >
          <Button size="small" type="text" danger icon={<DeleteOutlined />} />
        </Popconfirm>),
    },
  ];

  const renderHubItem = (item: SkillHubItem) => {
    const installingNow = installing === item.slug;
    return (
      <List.Item
        actions={[
          hubTab === 'skills' ? (
            <Button key="s" size="small" type="primary" loading={installingNow}
              icon={<DownloadOutlined />} onClick={() => installSkill(item)}>
              安装技能
            </Button>
          ) : (
            <Button key="p" size="small" type="primary" loading={installingNow}
              icon={<DownloadOutlined />} onClick={() => installPackage(item)}>
              安装技能包
            </Button>
          ),
        ]}
      >
        <List.Item.Meta
          avatar={item.icon_url ? (
            <img src={item.icon_url} alt="" width={36} height={36}
              style={{ borderRadius: 8, objectFit: 'cover' }} />
          ) : null}
          title={<Space>{item.display_name}
            <Typography.Text code>{item.slug}</Typography.Text>
            {item.requires_api_key && (
              <Tag color="orange" title="该技能需要 API Key，安装后在「设置 → 环境变量」配置">
                需 API Key
              </Tag>
            )}
            {hubTab === 'skillsets' && item.skill_count != null && (
              <Tag color="blue">{item.skill_count} 技能</Tag>)}
          </Space>}
          description={(
            <Space direction="vertical" size={0}>
              <span>{item.summary || item.description || '—'}</span>
              <span style={{ color: '#9ca3af', fontSize: 12 }}>
                下载 {item.downloads || 0} · {item.publisher || '未知发布者'}
                {item.scene ? ` · ${item.scene}` : ''}
              </span>
            </Space>
          )}
        />
      </List.Item>
    );
  };

  return (
    <>
      <Tabs
        items={[
          {
            key: 'installed', label: '已安装',
            children: (
              <>
                <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}>
                  <Button size="small" icon={<GithubOutlined />} style={{ marginRight: 8 }}
                    onClick={() => setGitOpen(true)}>从 Git 导入</Button>
                  <Upload
                    accept=".zip"
                    showUploadList={false}
                    beforeUpload={(file) => {
                      importSkillZip(file);
                      return false; // 手动上传，阻止 antd 自动提交
                    }}
                  >
                    <Button size="small" icon={<CloudUploadOutlined />}>导入技能 zip</Button>
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
                <Table<Skill>
                  rowKey="name" columns={builtinColumns} dataSource={builtins}
                  loading={loading} pagination={false} size="small"
                  title={() => <b style={{ fontSize: 13 }}>内置技能（随 harness 分发，仅查看）</b>}
                />
                <Table<Skill>
                  rowKey="name" columns={skillColumns} dataSource={skills}
                  loading={loading} pagination={false} size="small"
                  style={{ marginTop: 16 }}
                  title={() => <b style={{ fontSize: 13 }}>技能（单技能，目录 工作区/skills/）</b>}
                />
                <Table<SkillPackage>
                  rowKey="id" columns={packageColumns} dataSource={packages}
                  loading={loading} pagination={false} size="small"
                  style={{ marginTop: 16 }}
                  title={() => <b style={{ fontSize: 13 }}>技能包（SkillHub 技能集，包级整体启停）</b>}
                  expandable={{
                    expandedRowRender: (p: SkillPackage) => (
                      <Space wrap>
                        {p.skills.map(s => (
                          <Tag key={s.slug}>{s.slug}</Tag>
                        ))}
                      </Space>
                    ),
                  }}
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
    </>
  );
}
