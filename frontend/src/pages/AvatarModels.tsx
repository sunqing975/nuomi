import { useCallback, useEffect, useState } from 'react';
import {
  Button, Card, Popconfirm, Space, Switch, Tag, Tooltip, Typography, Upload, message,
} from 'antd';
import {
  CheckCircleFilled, DeleteOutlined, LoadingOutlined, PlayCircleOutlined, SmileOutlined, UploadOutlined,
} from '@ant-design/icons';
import { del, get, post, put, upload, type AvatarModel, type AvatarModelsResponse } from '../api';
import EntityGrid from '../components/EntityGrid';
import ErrorState from '../components/ErrorState';
import PageLayout from '../components/PageLayout';

export default function AvatarModelsPage() {
  const [models, setModels] = useState<AvatarModel[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [switching, setSwitching] = useState<string | null>(null);
  const [avatarEnabled, setAvatarEnabled] = useState(true);
  const [toggling, setToggling] = useState(false);
  const [importingVrm, setImportingVrm] = useState(false);
  const [importingFbx, setImportingFbx] = useState(false);
  const [previewing, setPreviewing] = useState<string | null>(null);
  const [actions, setActions] = useState<{ name: string; label_zh?: string }[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const d = await get<AvatarModelsResponse>('/avatar/models');
      setModels(d.models);
      setActive(d.active);
      setLoadError(null);
    } catch (e) {
      // 主列表读不到时，下面两个附带请求（动作清单/开关状态）没有意义，先报错再返回；
      // 原来这里没有 catch，异常冒泡后页面渲染不出列表，用户只看到空白。
      setLoadError((e as Error).message);
      return;
    }
    try {
      const a = await get<{ actions: { name: string; label_zh?: string }[] }>('/avatar/animations');
      setActions(a.actions);
    } catch { /* 动作清单读取失败时保持空 */ }
    try {
      const s = await get<{ enabled: boolean }>('/avatar/status');
      setAvatarEnabled(s.enabled);
    } catch { /* 状态读取失败时保持默认开 */ }
  }, []);

  useEffect(() => { load(); }, [load]);

  const togglePet = async (enabled: boolean) => {
    setToggling(true);
    try {
      const r = await put<{ enabled: boolean }>('/avatar/status', { enabled });
      setAvatarEnabled(r.enabled);
      message.success(r.enabled ? 'AI 数字人已开启' : 'AI 数字人已关闭（窗口已销毁，可随时再开）');
    } catch (e) {
      message.error(`操作失败：${(e as Error).message}`);
    } finally {
      setToggling(false);
    }
  };

  const importVrm = async (file: File) => {
    setImportingVrm(true);
    try {
      const d = await upload<{ ok: boolean; models: AvatarModel[] }>('/avatar/models/import', file);
      setModels(d.models);
      message.success(`VRM 模型「${file.name}」已导入，可在列表切换（无需重启）`);
    } catch (e) {
      message.error(`导入失败：${(e as Error).message}`);
    } finally {
      setImportingVrm(false);
    }
    return false;
  };

  const importFbx = async (file: File) => {
    setImportingFbx(true);
    message.loading({ content: `正在转换「${file.name}」→ 动作（首次约 10~30s）…`, key: 'fbx-convert', duration: 0 });
    try {
      const d = await upload<{ ok: boolean; action: string }>('/avatar/animations/import', file);
      message.destroy('fbx-convert');
      message.success(`动作「${d.action}」已导入，数字人页面正在刷新…`);
      load(); // 刷新动作清单（后端已广播 SSE，壳自动 reload 页面）
    } catch (e) {
      message.destroy('fbx-convert');
      message.error(`转换失败：${(e as Error).message}`);
    } finally {
      setImportingFbx(false);
    }
    return false;
  };

  const preview = async (kind: 'action' | 'expression', name: string) => {
    setPreviewing(`${kind}:${name}`);
    try {
      const r = await post<{ ok: boolean; payload: object }>('/avatar/preview', { kind, name });
      message.success(`已播放${kind === 'action' ? '动作' : '表情'}「${name}」（数字人窗口）`);
    } catch (e) {
      message.error(`预览失败：${(e as Error).message}`);    } finally {
      setPreviewing(null);
    }
  };

  const deleteAction = async (name: string) => {
    try {
      const d = await del<{ ok: boolean; action: string }>(`/avatar/animations/${encodeURIComponent(name)}`);
      message.success(`动作「${d.action}」已删除，数字人页面已刷新`);
      load(); // 刷新动作清单（后端已广播 SSE，壳自动 reload 页面）
    } catch (e) {
      message.error(`删除失败：${(e as Error).message}`);
    }
  };

  const switchModel = async (m: AvatarModel) => {
    if (m.id === active) return;
    setSwitching(m.id);
    try {
      const r = await post<{ ok: boolean; model: AvatarModel }>(
        '/avatar/models/switch', { model_id: m.id },
      );
      setActive(r.model.id);
      message.success(
        `已切换到「${r.model.id}」（表情工具随模型自动更新，壳 watch config 自动重载）`,
      );
    } catch (e) {
      message.error(`切换失败：${(e as Error).message}`);
    } finally {
      setSwitching(null);
    }
  };

  const removeModel = async (m: AvatarModel) => {
    try {
      await del(`/avatar/models/${m.id}`);
      message.success(`AI 数字人 ${m.id} 已删除（资产 + 插件级联清除）`);
      load();
    } catch (e) {
      message.error(`删除失败：${(e as Error).message}`);
    }
  };

  return (
    <PageLayout
      title="AI 数字人"
      description="管理数字人形象、动作与表情：导入即用，对话时用语言驱动"
      extra={
        <Tooltip
          title={avatarEnabled
            ? '关闭将销毁数字人窗口并停用动作 / 表情能力，后端对话不受影响'
            : '开启后恢复数字人窗口与动作 / 表情能力'}
        >
          <Switch
            checked={avatarEnabled}
            loading={toggling}
            onChange={togglePet}
            checkedChildren="开"
            unCheckedChildren="关"
          />
        </Tooltip>
      }
    >
      <Card
        size="small"
        style={{ marginBottom: 16 }}
        title="导入资产"
      >
        <Space wrap>
          <Upload
            accept=".vrm"
            showUploadList={false}
            beforeUpload={importVrm}
            disabled={importingVrm}
          >
            <Button icon={importingVrm ? <LoadingOutlined /> : <UploadOutlined />} loading={importingVrm}>
              导入 VRM 模型
            </Button>
          </Upload>
          <Upload
            accept=".fbx"
            showUploadList={false}
            beforeUpload={importFbx}
            disabled={importingFbx}
          >
            <Button icon={importingFbx ? <LoadingOutlined /> : <UploadOutlined />} loading={importingFbx}>
              导入动作（Mixamo FBX，自动转换）
            </Button>
          </Upload>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            VRM 直接成为可选形象；FBX 转换后自动注册新动作，AI 即可调用。均无需重启。
          </Typography.Text>
        </Space>
      </Card>

      <Card
        size="small"
        style={{ marginBottom: 16 }}
        title={<span><SmileOutlined /> 动作资产（全局共享，所有数字人通用）</span>}
      >
        {actions.length === 0 ? (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            暂无动作资产，可在上方「导入资产」导入 Mixamo FBX 动作
          </Typography.Text>
        ) : (
          <div>
            {actions.map(a => (
              <Tag key={a.name} style={{ marginBottom: 4 }}>
                {a.label_zh || a.name}
                <PlayCircleOutlined
                  style={{ marginLeft: 5, color: 'var(--link)', cursor: 'pointer' }}
                  onClick={ev => { ev.stopPropagation(); preview('action', a.name); }}
                />
                <Popconfirm
                  title={`删除动作「${a.label_zh || a.name}」？`}
                  description={a.name === 'idle'
                    ? 'idle 是待机动画，删除后数字人退化为呼吸微晃兜底姿态'
                    : '删除后该动作不再可调用，数字人页面自动刷新'}
                  onConfirm={() => deleteAction(a.name)}
                  okText="删除"
                  cancelText="取消"
                  okButtonProps={{ danger: true }}
                >
                  <DeleteOutlined
                    style={{ marginLeft: 6, color: 'var(--label-3)', cursor: 'pointer' }}
                    onClick={ev => ev.stopPropagation()}
                  />
                </Popconfirm>
              </Tag>
            ))}
            <Typography.Text type="secondary" style={{ display: 'block', fontSize: 12, marginTop: 6 }}>
              动作是全局资产：导入一次，所有数字人都可调用；删除后数字人页面自动刷新。
            </Typography.Text>
          </div>
        )}
      </Card>

      {loadError ? (
        <ErrorState description={loadError} onRetry={load} />
      ) : (
        <EntityGrid
          items={models}
          minWidth={340}
          emptyText="3D/ 目录下没有可用的 VRM AI 数字人形象"
          renderItem={m => {
            const isActive = m.id === active;
            const hasCapability = m.motions.length > 0 || m.expressions.length > 0;
            return (
              <Card
                size="small"
                hoverable
                style={{
                  height: '100%',
                  display: 'flex',
                  flexDirection: 'column',
                  borderColor: isActive ? 'var(--accent)' : undefined,
                  boxShadow: isActive ? '0 0 0 2px rgba(245,158,11,.18)' : undefined,
                }}
                onClick={() => switchModel(m)}
                title={
                  <span>
                    {isActive && <CheckCircleFilled style={{ color: 'var(--accent)', marginRight: 6 }} />}
                    {m.id}
                  </span>
                }
                extra={
                  <span onClick={e => e.stopPropagation()}>
                    {switching === m.id && (
                      <Typography.Text type="warning" style={{ fontSize: 12, marginRight: 8 }}>
                        <LoadingOutlined /> 分析中…
                      </Typography.Text>
                    )}
                    {switching !== m.id && isActive && (
                      <Typography.Text type="success" style={{ fontSize: 12, marginRight: 8 }}>使用中</Typography.Text>
                    )}
                    {switching !== m.id && !isActive && hasCapability && (
                      <Typography.Text type="secondary" style={{ fontSize: 12, marginRight: 8 }}>点击切换</Typography.Text>
                    )}
                    {switching !== m.id && !isActive && !hasCapability && (
                      <Tag color="default" style={{ marginRight: 8 }}>无动作/表情</Tag>
                    )}
                    {m.builtin && (
                      <Tag color="blue" style={{ marginRight: 8 }}>内置</Tag>
                    )}
                    {!m.builtin && (
                      <Popconfirm
                        title="删除AI 数字人？"
                        description="将删除AI 数字人资产与对应插件（不可恢复）；删除使用中的AI 数字人会自动切换"
                        okText="删除" cancelText="取消"
                        onConfirm={() => removeModel(m)}
                      >
                        <DeleteOutlined
                          style={{ color: 'var(--danger)', fontSize: 14 }}
                        />
                      </Popconfirm>
                    )}
                  </span>
                }
              >
                <Typography.Paragraph
                  type="secondary"
                  style={{ fontSize: 12, marginBottom: 10, wordBreak: 'break-all' }}
                >
                  {m.path}
                </Typography.Paragraph>

                {m.expressions.length > 0 && (
                  <div style={{ marginBottom: 8 }}>
                    <Typography.Text strong style={{ fontSize: 12 }}>表情 </Typography.Text>
                    {m.expressions_have_data === false && (
                      <Typography.Text type="warning" style={{ fontSize: 12 }}>
                        ⚠ 该模型无表情变形数据（binds 空），预览/对话表情不会变化，请更换带表情的 VRM
                      </Typography.Text>
                    )}
                    {m.expressions.map(e => (
                      <Tag key={e} color="purple" style={{ marginBottom: 4 }}>
                        {e}
                        {isActive && m.expressions_have_data !== false && (
                          <PlayCircleOutlined
                            style={{ marginLeft: 5, color: '#7c3aed', cursor: 'pointer' }}
                            onClick={ev => { ev.stopPropagation(); preview('expression', e); }}
                          />
                        )}
                      </Tag>
                    ))}
                  </div>
                )}
              </Card>
            );
          }}
        />
      )}
    </PageLayout>
  );
}
