import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import { Button, Layout, Menu, Space, Tag, Tooltip, Typography } from 'antd';
import type { ReactNode } from 'react';
import {
  RobotOutlined, ApiOutlined, ReadOutlined, GlobalOutlined,
  SmileOutlined, MessageOutlined, SettingOutlined, BookOutlined,
  ShopOutlined, ShoppingOutlined, MoonOutlined, SunOutlined,
} from '@ant-design/icons';
import { useThemeMode } from './themeStore';
import ChatPage from './pages/Chat';
import ExpertsPage from './pages/Experts';
import PluginsPage from './pages/Plugins';
import PluginMarketPage from './pages/PluginMarketPage';
import SkillsPage from './pages/Skills';
import SkillMarketPage from './pages/SkillMarketPage';
import ConnectorsPage from './pages/Connectors';
import AvatarModelsPage from './pages/AvatarModels';
import SettingsPage from './pages/Settings';
import KnowledgePage from './pages/Knowledge';
import KnowledgeDetailPage from './pages/KnowledgeDetail';

const { Sider, Content, Header } = Layout;

/**
 * 导航三分组（P0-6，2026-10-06）：对话 ｜ 能力 ｜ 系统。
 * 「记忆」不再占平级菜单 —— 它是对话的伴生视图（Chat 页「记忆」抽屉）。
 */
interface NavLeaf { key: string; icon: ReactNode; label: string; [k: `data-${string}`]: any; }
interface NavGroup { key: string; type: 'group'; label: string; children: NavLeaf[]; }
type NavEntry = NavLeaf | NavGroup;

const NAV: NavEntry[] = [
  { key: 'chat', icon: <MessageOutlined />, label: '对话' },
  {
    key: 'abilities',
    type: 'group',
    label: '能力',
    children: [
      { key: 'experts', icon: <RobotOutlined />, label: '专家' },
      { key: 'plugins', icon: <ApiOutlined />, label: '插件' },
      { key: 'skills', icon: <ReadOutlined />, label: '技能' },
      { key: 'connectors', icon: <GlobalOutlined />, label: '连接器' },
      { key: 'knowledge', icon: <BookOutlined />, label: '知识库' },
    ],
  },
  {
    key: 'system',
    type: 'group',
    label: '系统',
    children: [
      { key: 'avatarModels', icon: <SmileOutlined />, label: 'AI 数字人' },
      { key: 'settings', icon: <SettingOutlined />, label: '设置' },
    ],
  },
];

/** 市场页：支持 hash 直达与面包屑返回，但不在侧栏导航显示（入口在插件/技能页按钮） */
const MARKET_PAGES: NavLeaf[] = [
  { key: 'pluginMarket', icon: <ShopOutlined />, label: '插件市场' },
  { key: 'skillMarket', icon: <ShoppingOutlined />, label: '技能市场' },
];

/** 市场页的上级页面（面包屑可点击返回） */
const PAGE_PARENT: Record<string, string> = {
  pluginMarket: 'plugins',
  skillMarket: 'skills',
};

/** 扁平化导航（含 group children 与市场页），供 hash 路由与标题查找 */
const ALL_NAV: NavLeaf[] = [...NAV.flatMap(n => ('children' in n ? n.children : [n])), ...MARKET_PAGES];

export default function App() {
  const [page, setPage] = useState('chat');
  const [mode, setMode] = useThemeMode();
  const [kbDetailId, setKbDetailId] = useState<string | null>(null); // #knowledge/detail/<id> 独立详情页
  const [backendOk, setBackendOk] = useState<boolean | null>(null);

  /** 全局后端健康探测：App 启动、切页、以及每 15s 轮询（原挂在专家页 load，其他页面永不更新） */
  const probeBackend = useCallback(async () => {
    try {
      const res = await fetch('/api/health');
      setBackendOk(res.ok);
    } catch {
      setBackendOk(false);
    }
  }, []);

  useEffect(() => {
    probeBackend();
    const t = setInterval(probeBackend, 15000);
    return () => clearInterval(t);
  }, [probeBackend, page]);

  // 与 URL hash 同步（#plugins 直达 / #knowledge/detail/<id> 详情页 / 浏览器前进后退）
  useEffect(() => {
    const applyHash = () => {
      const h = location.hash.replace('#', '');
      const m = h.match(/^knowledge\/detail\/([^/]+)$/);
      if (m) { setPage('knowledge'); setKbDetailId(m[1]); return; }
      if (ALL_NAV.some(n => n.key === h)) {
        setPage(h);
        setKbDetailId(null); // 非详情路由一律清详情（detail 格式已在上方提前 return）
      }
    };
    applyHash();
    window.addEventListener('hashchange', applyHash);
    return () => window.removeEventListener('hashchange', applyHash);
  }, []);

  /** 面包屑 crumb 序列：分组(纯文本) / 上级(可点返回) / 当前页(粗体) */
  const crumbs = useMemo(() => {
    const pageKey = kbDetailId ? 'knowledge' : page;
    const parentKey = kbDetailId ? 'knowledge' : PAGE_PARENT[page];
    const group = NAV.find(
      g => 'children' in g && g.children.some(c => c.key === pageKey || c.key === parentKey),
    );
    const labelOf = (k: string) => ALL_NAV.find(n => n.key === k)?.label ?? k;
    const out: { label: string; key?: string }[] = [];
    if (group && 'label' in group) out.push({ label: group.label });
    if (parentKey) out.push({ label: labelOf(parentKey), key: parentKey });
    out.push({ label: kbDetailId ? '详情' : labelOf(page) });
    return out;
  }, [page, kbDetailId]);

  const switchPage = (key: string) => {
    setPage(key);
    setKbDetailId(null);
    history.replaceState(null, '', '#' + key);
  };

  return (
    <Layout style={{ height: '100vh' }}>
      <Sider
        width={200}
        theme={mode === 'dark' ? 'dark' : 'light'}
        style={{ borderRight: '1px solid var(--line-2)', position: 'relative', overflow: 'auto' }}
      >
        <div style={{ padding: '18px 20px 12px', fontSize: 16, fontWeight: 700 }}>
          <span style={{ color: 'var(--accent)' }}>●</span> Nuomi
        </div>
        <Menu
          mode="inline"
          selectedKeys={[page]}
          items={NAV}
          onClick={e => switchPage(e.key)}
          style={{ borderInlineEnd: 'none' }}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            background: 'var(--surface)', borderBottom: '1px solid var(--line-2)',
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '0 28px', height: 60,
          }}
        >
          <Space size={8}>
            {crumbs.map((c, i) => (
              <Fragment key={`${c.label}-${i}`}>
                {i > 0 && <Typography.Text type="secondary" style={{ fontSize: 14 }}>/</Typography.Text>}
                {c.key ? (
                  <Typography.Link
                    onClick={() => switchPage(c.key!)}
                    style={{ fontSize: 14 }}
                  >
                    {c.label}
                  </Typography.Link>
                ) : (
                  <Typography.Text
                    style={{
                      fontSize: 14,
                      color: i === crumbs.length - 1 ? 'var(--label-1)' : 'var(--label-2)',
                      fontWeight: i === crumbs.length - 1 ? 600 : 500,
                    }}
                  >
                    {c.label}
                  </Typography.Text>
                )}
              </Fragment>
            ))}
          </Space>
          <Space size={8}>
            {/* 主题切换：token 覆盖层早就备好了，缺的只是入口（此前 main.tsx 硬编码 light） */}
            <Tooltip title={mode === 'dark' ? '切到浅色' : '切到深色'}>
              <Button
                type="text"
                size="small"
                aria-label={mode === 'dark' ? '切换到浅色主题' : '切换到深色主题'}
                icon={mode === 'dark' ? <SunOutlined /> : <MoonOutlined />}
                onClick={() => setMode(mode === 'dark' ? 'light' : 'dark')}
              />
            </Tooltip>
            <Tag color={backendOk === false ? 'red' : backendOk === true ? 'green' : 'default'}>
              {backendOk === false ? '后端离线' : backendOk === true ? '在线' : '连接中…'}
            </Tag>
          </Space>
        </Header>
        <Content style={{ padding: 24, overflow: 'auto' }}>
          {page === 'chat' && <ChatPage />}
          {page === 'experts' && <ExpertsPage />}
          {page === 'plugins' && <PluginsPage />}
          {page === 'pluginMarket' && <PluginMarketPage />}
          {page === 'skills' && <SkillsPage />}
          {page === 'skillMarket' && <SkillMarketPage />}
          {page === 'connectors' && <ConnectorsPage />}
          {page === 'knowledge' && (kbDetailId ? <KnowledgeDetailPage kbId={kbDetailId} /> : <KnowledgePage />)}
          {page === 'avatarModels' && <AvatarModelsPage />}
          {page === 'settings' && <SettingsPage />}
        </Content>
      </Layout>
    </Layout>
  );
}
