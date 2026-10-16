import { useCallback, useEffect, useState } from 'react';
import { Avatar, Button, Card, Space, Tag, Typography, message } from 'antd';
import { CheckCircleOutlined, DownloadOutlined } from '@ant-design/icons';
import { get, post } from '../api';
import EntityGrid from '../components/EntityGrid';
import ErrorState from '../components/ErrorState';
import { pickAvatarColor } from '../utils/palette';

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

export default function MarketPage({ onInstalled }: MarketProps = {}) {
  const [market, setMarket] = useState<MarketResp | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [installing, setInstalling] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setMarket(await get<MarketResp>('/plugins/market'));
      setLoadError(null);
    } catch (e) {
      // 市场是远程聚合接口，最容易失败（无网 / 源站挂了）。原来异常冒泡成 unhandled rejection，
      // 页面显示「市场暂无插件」——用户会以为市场是空的，而不是请求失败了。
      setLoadError((e as Error).message);
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
      {loadError ? (
        <ErrorState description={loadError} onRetry={load} />
      ) : (
        <EntityGrid
          items={market?.plugins ?? []}
          loading={loading}
          emptyText="市场暂无插件"
          renderItem={(item) => {
            const color = pickAvatarColor(item.id);
            return (
              <Card
                key={item.id}
                size="small"
                hoverable
                style={{ height: '100%' }}
                title={
                  <Space>
                    <Avatar size={24} style={{ backgroundColor: color, fontSize: 12, flexShrink: 0 }}>
                      {(item.name[0] || '?').toUpperCase()}
                    </Avatar>
                    <span>{item.name}</span>
                  </Space>
                }
                extra={
                  item.installed
                    ? <Tag color="green" icon={<CheckCircleOutlined />} style={{ marginInlineEnd: 0 }}>已安装 v{item.installed_version || item.version}</Tag>
                    : (
                      <Button size="small" type="primary" loading={installing === item.id}
                        icon={<DownloadOutlined />}
                        onClick={() => install(item)}>
                        安装
                      </Button>
                    )
                }
              >
                <Typography.Paragraph type="secondary" ellipsis={{ rows: 2 }} style={{ fontSize: 13, minHeight: 40, marginBottom: 8 }}>
                  {item.description || '（暂无描述）'}
                </Typography.Paragraph>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {KIND_LABEL[item.kind] ?? '插件'} · v{item.version}
                  </Typography.Text>
                  {item.tags && item.tags.length > 0 && (
                    <Space size={4} wrap>
                      {item.tags.slice(0, 3).map(t => (
                        <Tag key={t} style={{ marginInlineEnd: 0, fontSize: 11 }}>{t}</Tag>
                      ))}
                    </Space>
                  )}
                </div>
              </Card>
            );
          }}
        />
      )}
    </div>
  );
}
