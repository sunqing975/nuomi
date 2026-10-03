import { useEffect, useState } from 'react';
import { Layout, Menu, Tag, Typography } from 'antd';
import {
  RobotOutlined, ApiOutlined, ReadOutlined, GlobalOutlined, DatabaseOutlined,
} from '@ant-design/icons';
import ExpertsPage from './pages/Experts';
import PluginsPage from './pages/Plugins';
import SkillsPage from './pages/Skills';
import McpPage from './pages/Mcp';
import StoragePage from './pages/Storage';

const { Sider, Content, Header } = Layout;

const NAV = [
  { key: 'experts', icon: <RobotOutlined />, label: '专家', title: '专家' },
  { key: 'plugins', icon: <ApiOutlined />, label: '插件', title: '插件' },
  { key: 'skills', icon: <ReadOutlined />, label: '技能', title: '技能' },
  { key: 'mcp', icon: <GlobalOutlined />, label: 'MCP', title: 'MCP 服务器' },
  { key: 'storage', icon: <DatabaseOutlined />, label: '存储', title: '存储 / 总览' },
];

export default function App() {
  const [page, setPage] = useState('experts');
  const [backendOk, setBackendOk] = useState<boolean | null>(null);

  // 与 URL hash 同步（#plugins 直达 / 浏览器前进后退）
  useEffect(() => {
    const applyHash = () => {
      const h = location.hash.replace('#', '');
      if (NAV.some(n => n.key === h)) setPage(h);
    };
    applyHash();
    window.addEventListener('hashchange', applyHash);
    return () => window.removeEventListener('hashchange', applyHash);
  }, []);

  const title = NAV.find(n => n.key === page)?.title ?? '';

  const switchPage = (key: string) => {
    setPage(key);
    history.replaceState(null, '', '#' + key);
  };

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider width={200} theme="light" style={{ borderRight: '1px solid #e5e7eb' }}>
        <div style={{ padding: '18px 20px 12px', fontSize: 16, fontWeight: 700 }}>
          <span style={{ color: '#f59e0b' }}>●</span> Nuomi
        </div>
        <Menu
          mode="inline"
          selectedKeys={[page]}
          items={NAV}
          onClick={e => switchPage(e.key)}
          style={{ borderInlineEnd: 'none' }}
        />
        <div style={{ position: 'absolute', bottom: 16, left: 20, fontSize: 12, color: '#9ca3af' }}>
          表现层可插拔 · 协议标准化
        </div>
      </Sider>
      <Layout>
        <Header
          style={{
            background: '#fff', borderBottom: '1px solid #e5e7eb',
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
          {page === 'experts' && <ExpertsPage onBackend={setBackendOk} />}
          {page === 'plugins' && <PluginsPage />}
          {page === 'skills' && <SkillsPage />}
          {page === 'mcp' && <McpPage />}
          {page === 'storage' && <StoragePage />}
        </Content>
      </Layout>
    </Layout>
  );
}
