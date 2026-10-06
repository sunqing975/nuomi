import { useCallback, useEffect, useState } from 'react';
import { Avatar, Button, Card, Input, Space, Tabs, Tag, Typography, message } from 'antd';
import { DownloadOutlined, ReloadOutlined } from '@ant-design/icons';
import { get, post, type SkillHubItem, type SkillPackage } from '../api';
import EntityGrid from '../components/EntityGrid';
import PageLayout from '../components/PageLayout';

const AVATAR_COLORS = ['#f59e0b', '#3b82f6', '#10b981', '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316'];

const initialAvatarOf = (name: string, size = 40) => {
  const ch = (name[0] || '?').toUpperCase();
  const color = AVATAR_COLORS[(name.charCodeAt(0) || 0) % AVATAR_COLORS.length];
  return <Avatar size={size} style={{ backgroundColor: color, flexShrink: 0 }}>{ch}</Avatar>;
};

/** 技能市场独立页：面包屑「能力 / 技能市场」（安装后到「技能」页管理） */
export default function SkillMarketPage() {
  const [hubTab, setHubTab] = useState<'skills' | 'skillsets'>('skills');
  const [hubItems, setHubItems] = useState<SkillHubItem[]>([]);
  const [hubLoading, setHubLoading] = useState(false);
  const [installing, setInstalling] = useState<string | null>(null);

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

  const installSkill = async (item: SkillHubItem) => {
    setInstalling(item.slug);
    try {
      await post('/skills/install', { slug: item.slug });
      message.success(`技能 ${item.display_name} 已安装`);
      if (item.requires_api_key) {
        message.warning('该技能需要 API Key，请到「设置 → 环境变量」配置后重启对话生效', 5);
      }
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
    } catch (e) {
      message.error(`安装失败：${(e as Error).message}`);
    } finally {
      setInstalling(null);
    }
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
      title="技能市场"
      description="从 SkillHub 市场安装技能 / 技能包：安装后出现在「技能」页"
    >
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
    </PageLayout>
  );
}
