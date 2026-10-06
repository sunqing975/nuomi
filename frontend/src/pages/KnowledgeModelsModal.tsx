import { useEffect, useRef, useState } from 'react';
import { Button, Modal, Select, Space, Tag, Tooltip, Typography, message } from 'antd';
import { DeleteOutlined, DownloadOutlined, ReloadOutlined } from '@ant-design/icons';
import { knowledgeApi, type KnowledgeCapability } from '../api';

interface Props {
  open: boolean;
  onClose: () => void;
  /** 父页持有的最新能力状态；变更后通过 onChanged 回传刷新 */
  capability: KnowledgeCapability | null;
  onChanged: (c: KnowledgeCapability) => void;
}

/** 模型管理 Modal：启用开关 + 模型选择/下载/删除（轮询就绪，对齐 Octop onnx 面板简化版）。 */
export default function KnowledgeModelsModal({ open, onClose, capability, onChanged }: Props) {
  const [busy, setBusy] = useState<string | null>(null); // 进行中的模型 id
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = async () => {
    onChanged(await knowledgeApi.capability());
  };

  // 下载完成后轮询 capability 直到 downloaded（最多 ~3 分钟）
  const startDownload = async (model: string) => {
    setBusy(model);
    try {
      const r = await knowledgeApi.onnxDownload(model);
      if (r.reason === 'already_downloaded') {
        message.success('模型已就绪');
        await refresh();
        setBusy(null); // 提前 return 必须复位，否则按钮一直 loading
        return;
      }
      if (timer.current) clearInterval(timer.current);
      let tries = 0;
      // setInterval 的 async 回调必须自带 try/catch：轮询失败（后端重启/网络抖动）时
      // 未捕获的 rejection 会冒泡成 unhandled rejection，而 setBusy(null) 永远不执行 →
      // 下载按钮永久 loading。
      timer.current = setInterval(() => {
        void (async () => {
          tries += 1;
          try {
            const cap = await knowledgeApi.capability();
            onChanged(cap);
            if (cap.downloaded || !cap.downloading.includes(model) || tries > 90) {
              if (timer.current) clearInterval(timer.current);
              timer.current = null;
              setBusy(null);
              if (cap.downloaded) message.success('模型下载完成');
              else message.error('模型下载失败，请重试');
            }
          } catch (e) {
            if (timer.current) clearInterval(timer.current);
            timer.current = null;
            setBusy(null);
            message.error(`查询下载状态失败：${(e as Error).message}`);
          }
        })();
      }, 2000);
    } catch (e) {
      setBusy(null);
      message.error(`下载失败：${(e as Error).message}`);
    }
  };

  useEffect(() => () => { if (timer.current) clearInterval(timer.current); }, []);

  const switchModel = async (model: string) => {
    try {
      await knowledgeApi.feature({ enabled: true, model });
      message.success('模型已切换，正在重建索引');
      await refresh();
    } catch (e) {
      message.error(`切换失败：${(e as Error).message}`);
    }
  };

  const removeModel = async (model: string) => {
    try {
      await knowledgeApi.onnxDelete(model);
      message.success('模型已删除');
      await refresh();
    } catch (e) {
      message.error(`删除失败：${(e as Error).message}`);
    }
  };

  const presets = capability?.presets_meta ?? [];
  const current = capability?.model ?? '';
  const localIds = capability?.local_models ?? [];
  // 只能切换已下载的模型；当前模型未下载时以禁用占位显示（提示先下载）
  const modelOptions = [
    ...(current && !localIds.includes(current)
      ? [{ value: current, label: `${current}（未下载，请先下载）`, disabled: true }]
      : []),
    ...localIds.map(id => ({ value: id, label: id })),
  ];

  const sizeLabel = (gb: number | null) =>
    gb == null ? '' : ` · ${gb < 1 ? `${Math.round(gb * 1024)}MB` : `${gb.toFixed(1)}GB`}`;

  return (
    <Modal title="嵌入模型管理" open={open} onCancel={onClose} footer={null} width={620}>
      {capability?.deps_available === false && (
        <Typography.Paragraph type="danger" style={{ marginTop: 0 }}>
          本地嵌入依赖缺失：请在 backend 环境安装 fastembed / onnxruntime（uv add fastembed onnxruntime huggingface_hub），然后刷新重试。
        </Typography.Paragraph>
      )}
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ minWidth: 80 }}>嵌入模型</span>
          <Select
            style={{ minWidth: 320 }}
            options={modelOptions}
            value={current || undefined}
            onChange={switchModel}
            placeholder="选择嵌入模型"
          />
          <Typography.Text type="secondary" style={{ fontSize: 13 }}>
            {capability?.ready ? '就绪' : capability?.downloaded ? '未启用' : '模型未就绪'}
          </Typography.Text>
        </div>
        <div>
          <Typography.Text type="secondary" style={{ fontSize: 13 }}>
            可用模型（切换后所有文档将重建索引）：
          </Typography.Text>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
            {presets.filter(p => p.supported).map(p => {
              const downloaded = capability?.local_models.includes(p.id);
              const running = busy === p.id || capability?.downloading.includes(p.id);
              return (
                <div key={p.id} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <code style={{ fontSize: 13, flex: 1 }}>{p.id}{sizeLabel(p.size_gb)}</code>
                  {downloaded ? (
                    <Tag color="green">已就绪</Tag>
                  ) : running ? (
                    <Tag color="blue">下载中…</Tag>
                  ) : (
                    <Tag>未下载</Tag>
                  )}
                  <Tooltip title={downloaded ? '删除模型缓存' : '下载模型（官方源 + 镜像竞速）'}>
                    {downloaded ? (
                      <Button size="small" danger icon={<DeleteOutlined />} onClick={() => removeModel(p.id)} />
                    ) : (
                      <Button size="small" icon={<DownloadOutlined />} disabled={running} loading={running} onClick={() => startDownload(p.id)} />
                    )}
                  </Tooltip>
                </div>
              );
            })}
          </div>
        </div>
        <Button size="small" icon={<ReloadOutlined />} onClick={refresh} style={{ alignSelf: 'flex-start' }}>
          刷新状态
        </Button>
      </Space>
    </Modal>
  );
}
