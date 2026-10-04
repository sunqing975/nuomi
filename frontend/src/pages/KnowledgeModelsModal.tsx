import { useEffect, useRef, useState } from 'react';
import { Button, Modal, Select, Space, Switch, Tag, Tooltip, Typography, message } from 'antd';
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
        return;
      }
      if (timer.current) clearInterval(timer.current);
      let tries = 0;
      timer.current = setInterval(async () => {
        tries += 1;
        const cap = await knowledgeApi.capability();
        onChanged(cap);
        if (cap.downloaded || !cap.downloading.includes(model) || tries > 90) {
          if (timer.current) clearInterval(timer.current);
          setBusy(null);
          if (cap.downloaded) message.success('模型下载完成');
          else message.error('模型下载失败，请重试');
        }
      }, 2000);
    } catch (e) {
      setBusy(null);
      message.error(`下载失败：${(e as Error).message}`);
    }
  };

  useEffect(() => () => { if (timer.current) clearInterval(timer.current); }, []);

  const toggleEnabled = async (v: boolean) => {
    if (v && capability && !capability.downloaded) {
      message.warning('请先下载模型');
      return;
    }
    try {
      await knowledgeApi.feature({ enabled: v });
      message.success(v ? '知识库已启用' : '知识库已停用');
      await refresh();
    } catch (e) {
      message.error(`操作失败：${(e as Error).message}`);
    }
  };

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
  const modelOptions = presets
    .filter(p => p.supported)
    .map(p => ({ value: p.id, label: p.id }));
  const current = capability?.model ?? '';

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
          <span style={{ minWidth: 80 }}>知识库功能</span>
          <Switch checked={capability?.enabled ?? false} onChange={toggleEnabled} />
          <span style={{ color: '#6b7280', fontSize: 13 }}>
            {capability?.ready ? '就绪' : capability?.downloaded ? '未启用' : '模型未就绪'}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ minWidth: 80 }}>嵌入模型</span>
          <Select
            style={{ minWidth: 320 }}
            options={modelOptions}
            value={current || undefined}
            onChange={switchModel}
            placeholder="选择嵌入模型"
          />
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
