import MarketPage from './Market';
import PageLayout from '../components/PageLayout';

/** 插件市场独立页：面包屑「能力 / 插件市场」（安装后到「插件」页管理） */
export default function PluginMarketPage() {
  return (
    <PageLayout
      title="插件市场"
      description="从市场安装插件：安装后出现在「插件」页，可全局启停"
    >
      <MarketPage />
    </PageLayout>
  );
}
