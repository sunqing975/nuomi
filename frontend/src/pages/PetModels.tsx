import { useCallback, useEffect, useState } from 'react';
import {
  Alert, Card, Col, Empty, Popconfirm, Row, Switch, Tag, Typography, message,
} from 'antd';
import { CheckCircleFilled, DeleteOutlined, LoadingOutlined, SmileOutlined } from '@ant-design/icons';
import { del, get, post, put, type PetModel, type PetModelsResponse } from '../api';

export default function PetModelsPage() {
  const [models, setModels] = useState<PetModel[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [switching, setSwitching] = useState<string | null>(null);
  const [petEnabled, setPetEnabled] = useState(true);
  const [toggling, setToggling] = useState(false);

  const load = useCallback(async () => {
    const d = await get<PetModelsResponse>('/pet/models');
    setModels(d.models);
    setActive(d.active);
    try {
      const s = await get<{ enabled: boolean }>('/pet/status');
      setPetEnabled(s.enabled);
    } catch { /* 状态读取失败时保持默认开 */ }
  }, []);

  useEffect(() => { load(); }, [load]);

  const togglePet = async (enabled: boolean) => {
    setToggling(true);
    try {
      const r = await put<{ enabled: boolean }>('/pet/status', { enabled });
      setPetEnabled(r.enabled);
      message.success(r.enabled ? '桌宠已开启' : '桌宠已关闭（窗口已销毁，可随时再开）');
    } catch (e) {
      message.error(`操作失败：${(e as Error).message}`);
    } finally {
      setToggling(false);
    }
  };

  const switchModel = async (m: PetModel) => {
    if (m.id === active) return;
    setSwitching(m.id);
    try {
      const r = await post<{ ok: boolean; model: PetModel }>(
        '/pet/models/switch', { model_id: m.id },
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

  const removeModel = async (m: PetModel) => {
    try {
      await del(`/pet/models/${m.id}`);
      message.success(`桌宠 ${m.id} 已删除（资产 + 插件级联清除）`);
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
        title={<b style={{ fontSize: 14 }}>桌宠开关</b>}
        extra={
          <Switch
            checked={petEnabled}
            loading={toggling}
            onChange={togglePet}
            checkedChildren="开"
            unCheckedChildren="关"
          />
        }
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 0 }}>
          {petEnabled
            ? '桌宠窗口显示中。关闭将销毁桌宠窗口（释放资源）并停用桌宠动作/表情插件（vrm-pet），后端对话能力不受影响，可随时重新开启。'
            : '桌宠窗口已完全停止（释放资源），桌宠动作/表情插件已停用（LLM 不再调用动作工具）。开启后恢复桌宠插件。'}
        </Typography.Paragraph>
      </Card>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="桌宠模型资产（工作区 models/3D/，VRM）"
        description={
          <span style={{ fontSize: 13 }}>
            所有桌宠共用同一套动作/表情插件（vrm-pet）：动作来自 Mixamo 动画（.vrma），
            表情来自当前模型的 blend shape。对桌宠说「给我比个心」「笑一个」，
            LLM 会调用动态装配的动作/表情工具来驱动桌宠。切模型 / 新增动画无需重启。
          </span>
        }
      />

      {models.length === 0 && <Empty description="3D/ 目录下没有可用的 VRM 桌宠形象" />}

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
                        title="删除桌宠？"
                        description="将删除桌宠资产与对应插件（不可恢复）；删除使用中的桌宠会自动切换"
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
                    {m.expressions.map(e => <Tag key={e} color="purple" style={{ marginBottom: 4 }}>{e}</Tag>)}
                  </div>
                )}

                <div style={{ marginBottom: 8 }}>
                  <Typography.Text strong style={{ fontSize: 12 }}>
                    <SmileOutlined /> 动作（{m.motions.length}）
                  </Typography.Text>
                  <div style={{ marginTop: 6 }}>
                    {m.motions.map(a => <Tag key={a} style={{ marginBottom: 4 }}>{a}</Tag>)}
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
