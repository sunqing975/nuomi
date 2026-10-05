import { useCallback, useEffect, useState } from 'react';
import { Button, Card, Empty, Space, Tag, Typography, message } from 'antd';
import { CheckCircleOutlined, DownloadOutlined } from '@ant-design/icons';
import { get, post } from '../api';

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
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        {market?.name || '插件市场'}
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 20 }}>
        从市场安装插件：安装后出现在「插件」列表，带配置项的插件会在「设置」中出现对应配置页。
      </Typography.Paragraph>
      {!loading && (!market?.plugins?.length) && <Empty description="市场暂无插件" />}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 16 }}>
        {(market?.plugins ?? []).map((item) => (
          <Card
            key={item.id}
            title={
              <Space>
                <span>{item.name}</span>
                <Tag color="blue">v{item.version}</Tag>
                {item.kind && <Tag>{item.kind}</Tag>}
              </Space>
            }
            extra={item.installed
              ? <Tag color="green" icon={<CheckCircleOutlined />}>已安装</Tag>
              : <Tag color="orange">未安装</Tag>}
          >
            <Typography.Paragraph type="secondary" style={{ minHeight: 48 }}>
              {item.description}
            </Typography.Paragraph>
            <Space wrap style={{ marginBottom: 12 }}>
              {item.tags?.map(t => <Tag key={t}>{t}</Tag>)}
              {item.author && <Typography.Text type="secondary" style={{ fontSize: 12 }}>{item.author}</Typography.Text>}
            </Space>
            {item.installed_note && (
              <Typography.Paragraph style={{ fontSize: 12, color: '#8b5cf6', marginBottom: 12 }}>
                {item.installed_note}
              </Typography.Paragraph>
            )}
            {item.installed
              ? <Typography.Text type="success">可在「设置 → {item.name}」配置并启用</Typography.Text>
              : (
                <Button
                  type="primary"
                  icon={<DownloadOutlined />}
                  loading={installing === item.id}
                  onClick={() => install(item)}
                >
                  安装
                </Button>
              )}
          </Card>
        ))}
      </div>
    </div>
  );
}
