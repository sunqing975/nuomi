import { useCallback, useEffect, useState } from 'react';
import { Avatar, Button, Card, Space, Tag, Typography, message } from 'antd';
import { CheckCircleOutlined, DownloadOutlined } from '@ant-design/icons';
import { get, post } from '../api';
import EntityGrid from '../components/EntityGrid';

/** 插件 kind 中文化（产品不暴露英文术语） */
const KIND_LABEL: Record<string, string> = { tool: '工具插件', model: '模型插件' };

interface MarketItem {
  id: string;
  name: string;
  version: string;
  author?: string;
  description: string;
  kind: string;
  tags?: string[];
  installed: boolean;
  enabled: boolean;
  installed_version?: string;
  installed_note?: string;
}

interface MarketResp {
  name: string;
  plugins: MarketItem[];
}

interface MarketProps {
  /** 安装成功后回调（嵌入插件页时用于刷新已安装列表） */
  onInstalled?: () => void;
}

const AVATAR_COLORS = ['#f59e0b', '#3b82f6', '#10b981', '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316'];

export default function MarketPage({ onInstalled }: MarketProps = {}) {
  const [market, setMarket] = useState<MarketResp | null>(null);
  const [loading, setLoading] = useState(false);
  const [installing, setInstalling] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setMarket(await get<MarketResp>('/plugins/market'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const install = async (item: MarketItem) => {
    setInstalling(item.id);
    try {
      const r = await post<{ ok: boolean; plugin: { name: string } }>('/plugins/market/install', { plugin_id: item.id });
      message.success(`插件「${r.plugin?.name || item.name}」安装成功（已启用）`);
      load();
      onInstalled?.();
    } catch (e) {
      message.error(`安装失败：${(e as Error).message}`);
    } finally {
      setInstalling(null);
    }
  };

  return (
    <div>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 16, fontSize: 13 }}>
        {market?.name
          ? `来自「${market.name}」市场，安装后出现在「插件」列表`
          : '从市场安装插件，安装后出现在「插件」列表'}
      </Typography.Paragraph>
      <EntityGrid
        items={market?.plugins ?? []}
        loading={loading}
        emptyText="市场暂无插件"
        renderItem={(item) => {
          const color = AVATAR_COLORS[(item.id.charCodeAt(0) || 0) % AVATAR_COLORS.length];
          return (
            <Card
              key={item.id}
              size="small"
              hoverable
              styles={{ body: { display: 'flex', flexDirection: 'column', gap: 8, height: '100%' } }}
            >
              <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                <Avatar size={40} style={{ backgroundColor: color, flexShrink: 0 }}>
                  {(item.name[0] || '?').toUpperCase()}
                </Avatar>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <Typography.Text strong ellipsis style={{ display: 'block' }} title={item.name}>
                    {item.name}
                  </Typography.Text>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {KIND_LABEL[item.kind] ?? '插件'} · v{item.version}
                  </Typography.Text>
                </div>
              </div>
              <Typography.Paragraph
                type="secondary" style={{ fontSize: 12, marginBottom: 0, flex: 1 }}
                ellipsis={{ rows: 2, tooltip: item.description }}
              >
                {item.description || '（暂无描述）'}
              </Typography.Paragraph>
              {item.tags && item.tags.length > 0 && (
                <Space size={4} wrap>
                  {item.tags.slice(0, 3).map(t => (
                    <Tag key={t} style={{ marginInlineEnd: 0, fontSize: 11 }}>{t}</Tag>
                  ))}
                </Space>
              )}
              {item.installed_note && (
                <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                  {item.installed_note}
                </Typography.Text>
              )}
              <div style={{ marginTop: 2 }}>
                {item.installed
                  ? (
                    <Tag color="green" icon={<CheckCircleOutlined />} style={{ marginInlineEnd: 0 }}>
                      已安装 v{item.installed_version || item.version}
                    </Tag>
                  )
                  : (
                    <Button
                      size="small" type="primary" block
                      icon={<DownloadOutlined />}
                      loading={installing === item.id}
                      onClick={() => install(item)}
                    >
                      安装
                    </Button>
                  )}
              </div>
            </Card>
          );
        }}
      />
    </div>
  );
}
