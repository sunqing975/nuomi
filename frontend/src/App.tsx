import { useEffect, useState } from 'react';
import { Layout, Menu, Tag, Typography } from 'antd';
import type { ReactNode } from 'react';
import {
  RobotOutlined, ApiOutlined, ReadOutlined, GlobalOutlined, DatabaseOutlined,
  SmileOutlined, MessageOutlined, SettingOutlined, BookOutlined,
} from '@ant-design/icons';
import ChatPage from './pages/Chat';
import ExpertsPage from './pages/Experts';
import PluginsPage from './pages/Plugins';
import SkillsPage from './pages/Skills';
import ConnectorsPage from './pages/Connectors';
import StoragePage from './pages/Storage';
import AvatarModelsPage from './pages/AvatarModels';
import SettingsPage from './pages/Settings';
import KnowledgePage from './pages/Knowledge';
import KnowledgeDetailPage from './pages/KnowledgeDetail';

const { Sider, Content, Header } = Layout;

/**
 * 导航三分组（P0-6，2026-10-06）：对话 ｜ 能力 ｜ 系统。
 * 「记忆」不再占平级菜单 —— 它是对话的伴生视图（Chat 页「记忆」抽屉）。
 */
interface NavLeaf { key: string; icon: ReactNode; label: string; title: string; [k: `data-${string}`]: any; }
interface NavGroup { key: string; type: 'group'; label: string; children: NavLeaf[]; }
type NavEntry = NavLeaf | NavGroup;

const NAV: NavEntry[] = [
  { key: 'chat', icon: <MessageOutlined />, label: '对话', title: '对话' },
  {
    key: 'abilities',
    type: 'group',
    label: '能力',
    children: [
      { key: 'experts', icon: <RobotOutlined />, label: '专家', title: '专家' },
      { key: 'plugins', icon: <ApiOutlined />, label: '插件', title: '插件（市场 / 已安装管理）' },
      { key: 'skills', icon: <ReadOutlined />, label: '技能', title: '技能 / 技能包' },
      { key: 'connectors', icon: <GlobalOutlined />, label: '连接器', title: '连接器（MCP 协议）' },
      { key: 'knowledge', icon: <BookOutlined />, label: '知识库', title: '知识库 / 文档检索' },
    ],
  },
  {
    key: 'system',
    type: 'group',
    label: '系统',
    children: [
      { key: 'avatarModels', icon: <SmileOutlined />, label: 'AI 数字人', title: 'AI 数字人模型资产' },
      { key: 'settings', icon: <SettingOutlined />, label: '设置', title: '设置 / 环境变量' },
      { key: 'storage', icon: <DatabaseOutlined />, label: '存储', title: '存储 / 总览' },
    ],
  },
];

/** 扁平化导航（含 group children），供 hash 路由与标题查找 */
const ALL_NAV: NavLeaf[] = NAV.flatMap(n => ('children' in n ? n.children : [n]));

export default function App() {
  const [page, setPage] = useState('chat');
  const [kbDetailId, setKbDetailId] = useState<string | null>(null); // #knowledge/detail/<id> 独立详情页
  const [backendOk, setBackendOk] = useState<boolean | null>(null);

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

  const title = kbDetailId ? '知识库详情' : (ALL_NAV.find(n => n.key === page)?.title ?? '');

  const switchPage = (key: string) => {
    setPage(key);
    setKbDetailId(null);
    history.replaceState(null, '', '#' + key);
  };

  return (
    <Layout style={{ height: '100vh' }}>
      <Sider
        width={200}
        theme="light"
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
        <div style={{ position: 'absolute', bottom: 16, left: 20, fontSize: 12, color: 'var(--label-3)' }}>
          表现层可插拔 · 协议标准化
        </div>
      </Sider>
      <Layout>
        <Header
          style={{
            background: 'var(--surface)', borderBottom: '1px solid var(--line-2)',
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '0 28px', height: 60,
          }}
        >
          <Typography.Title level={4} style={{ margin: 0 }}>{title}</Typography.Title>
          <Tag color={backendOk === false ? 'red' : backendOk === true ? 'green' : 'default'}>
            {backendOk === false ? '后端离线' : backendOk === true ? '后端在线' : '连接中…'}
          </Tag>
        </Header>
        <Content style={{ padding: 24, overflow: 'auto' }}>
          {page === 'chat' && <ChatPage />}
          {page === 'experts' && <ExpertsPage onBackend={setBackendOk} />}
          {page === 'plugins' && <PluginsPage />}
          {page === 'skills' && <SkillsPage />}
          {page === 'connectors' && <ConnectorsPage />}
          {page === 'knowledge' && (kbDetailId ? <KnowledgeDetailPage kbId={kbDetailId} /> : <KnowledgePage />)}
          {page === 'avatarModels' && <AvatarModelsPage />}
          {page === 'settings' && <SettingsPage />}
          {page === 'storage' && <StoragePage />}
        </Content>
      </Layout>
    </Layout>
  );
}
