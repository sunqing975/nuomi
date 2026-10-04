import { useCallback, useEffect, useState } from 'react';
import {
  Alert, Button, Card, Col, Empty, Popconfirm, Row, Space, Switch, Tag, Typography, Upload, message,
} from 'antd';
import {
  CheckCircleFilled, DeleteOutlined, LoadingOutlined, PlayCircleOutlined, SmileOutlined, UploadOutlined,
} from '@ant-design/icons';
import { del, get, post, put, upload, type AvatarModel, type AvatarModelsResponse } from '../api';

export default function AvatarModelsPage() {
  const [models, setModels] = useState<AvatarModel[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [switching, setSwitching] = useState<string | null>(null);
  const [avatarEnabled, setAvatarEnabled] = useState(true);
  const [toggling, setToggling] = useState(false);
  const [importingVrm, setImportingVrm] = useState(false);
  const [importingFbx, setImportingFbx] = useState(false);
  const [previewing, setPreviewing] = useState<string | null>(null);

  const load = useCallback(async () => {
    const d = await get<AvatarModelsResponse>('/avatar/models');
    setModels(d.models);
    setActive(d.active);
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
    message.loading({ content: `正在转换「${file.name}」→ VRMA（首次约 10~30s）…`, key: 'fbx-convert', duration: 0 });
    try {
      const d = await upload<{ ok: boolean; action: string }>('/avatar/animations/import', file);
      message.destroy('fbx-convert');
      message.success(`动作「${d.action}」已导入（数字人窗口自动注册，LLM 现在可以调用）`);
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
      message.error(`预览失败：${(e as Error).message}`);
    } finally {
      setPreviewing(null);
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
    <>
      <Card
        size="small"
        style={{ marginBottom: 16 }}
        title={<b style={{ fontSize: 14 }}>AI 数字人开关</b>}
        extra={
          <Switch
            checked={avatarEnabled}
            loading={toggling}
            onChange={togglePet}
            checkedChildren="开"
            unCheckedChildren="关"
          />
        }
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 0 }}>
          {avatarEnabled
            ? 'AI 数字人窗口显示中。关闭将销毁AI 数字人窗口（释放资源）并停用AI 数字人动作/表情插件（vrm-avatar），后端对话能力不受影响，可随时重新开启。'
            : 'AI 数字人窗口已完全停止（释放资源），AI 数字人动作/表情插件已停用（LLM 不再调用动作工具）。开启后恢复AI 数字人插件。'}
        </Typography.Paragraph>
      </Card>

      <Card
        size="small"
        style={{ marginBottom: 16 }}
        title={<b style={{ fontSize: 14 }}>导入资产</b>}
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
              导入动作（Mixamo FBX，自动转 VRMA）
            </Button>
          </Upload>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            VRM 直接成为可选模型；FBX 转换后数字人窗口自动注册新动作，LLM 即可调用。均无需重启。
          </Typography.Text>
        </Space>
      </Card>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="AI 数字人模型资产（工作区 models/3D/，VRM）"
        description={
          <span style={{ fontSize: 13 }}>
            所有AI 数字人共用同一套动作/表情插件（vrm-avatar）：动作来自 Mixamo 动画（.vrma），
            表情来自当前模型的 blend shape。对AI 数字人说「给我比个心」「笑一个」，
            LLM 会调用动态装配的动作/表情工具来驱动AI 数字人。切模型 / 新增动画无需重启。
            <b> 使用中的模型支持动作/表情预览（▶），点击即在数字人窗口实播。</b>
          </span>
        }
      />

      {models.length === 0 && <Empty description="3D/ 目录下没有可用的 VRM AI 数字人形象" />}

      <Row gutter={[14, 14]} className="nuomi-grid">
        {models.map(m => {
          const isActive = m.id === active;
          const hasCapability = m.motions.length > 0 || m.expressions.length > 0;
          return (
            <Col xs={24} sm={12} lg={8} key={m.id}>
              <Card
                size="small"
                hoverable
                style={{
                  height: '100%',
                  display: 'flex',
                  flexDirection: 'column',
                  borderColor: isActive ? '#f59e0b' : undefined,
                  boxShadow: isActive ? '0 0 0 2px rgba(245,158,11,.18)' : undefined,
                }}
                onClick={() => switchModel(m)}
                title={
                  <span>
                    {isActive && <CheckCircleFilled style={{ color: '#f59e0b', marginRight: 6 }} />}
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
                          style={{ color: '#dc2626', fontSize: 14 }}
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

                <div style={{ marginBottom: 8 }}>
                  <Typography.Text strong style={{ fontSize: 12 }}>
                    <SmileOutlined /> 动作（{m.motions.length}）
                  </Typography.Text>
                  <div style={{ marginTop: 6 }}>
                    {m.motions.map(a => (
                      <Tag key={a} style={{ marginBottom: 4 }}>
                        {a}
                        {isActive && (
                          <PlayCircleOutlined
                            style={{ marginLeft: 5, color: '#1677ff', cursor: 'pointer' }}
                            onClick={ev => { ev.stopPropagation(); preview('action', a); }}
                          />
                        )}
                      </Tag>
                    ))}
                  </div>
                </div>
              </Card>
            </Col>
          );
        })}
      </Row>
    </>
  );
}
