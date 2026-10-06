import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Avatar, Button, Card, Dropdown, Input, Modal, Popconfirm, Space, Switch,
  Tag, Typography, message,
} from 'antd';
import {
  CloudUploadOutlined, DeleteOutlined, DownOutlined, GithubOutlined, ShoppingOutlined,
} from '@ant-design/icons';
import {
  del, get, patch, post, upload, type Skill, type SkillPackage,
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
  const [gitOpen, setGitOpen] = useState(false);
  const [gitUrl, setGitUrl] = useState('');
  const [gitLoading, setGitLoading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

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
    return items;
  }, [builtins, skills, packages]);

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

  return (
    <PageLayout
      title="技能"
      description="技能 / 技能包管理：可导入本地包，安装市场的技能请到「技能市场」页"
    >
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
        <div style={{ flex: 1 }} />
        <Button type="primary" icon={<ShoppingOutlined />} onClick={() => { window.location.hash = '#skillMarket'; }}>技能市场</Button>
        <Dropdown menu={{
          items: [
            { key: 'git', label: '从 Git 仓库导入' },
            { key: 'zip', label: '导入技能 zip 文件' },
          ],
          onClick: ({ key }: { key: string }) => {
            if (key === 'git') setGitOpen(true);
            else fileRef.current?.click();
          },
        }}>
          <Button icon={<CloudUploadOutlined />}>导入<DownOutlined /></Button>
        </Dropdown>
        <input
          ref={fileRef} type="file" accept=".zip" style={{ display: 'none' }}
          onChange={e => {
            const f = e.target.files?.[0];
            if (f) importSkillZip(f);
            e.target.value = '';
          }}
        />
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
    </PageLayout>
  );
}
