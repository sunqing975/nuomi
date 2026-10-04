import { useCallback, useEffect, useState } from 'react';
import {
  Alert, Card, Col, Empty, Popconfirm, Row, Tag, Typography, message,
} from 'antd';
import { CheckCircleFilled, DeleteOutlined, SmileOutlined } from '@ant-design/icons';
import { del, get, post, type PetModel, type PetModelsResponse } from '../api';

export default function ModelsPage() {
  const [models, setModels] = useState<PetModel[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [switching, setSwitching] = useState<string | null>(null);

  const load = useCallback(async () => {
    const d = await get<PetModelsResponse>('/pet/models');
    setModels(d.models);
    setActive(d.active);
  }, []);

  useEffect(() => { load(); }, [load]);

  const switchModel = async (m: PetModel) => {
    if (m.id === active) return;
    setSwitching(m.id);
    try {
      const r = await post<{ ok: boolean; model: PetModel; activated_plugin?: string }>(
        '/pet/models/switch', { model_id: m.id },
      );
      setActive(r.model.id);
      message.success(
        r.activated_plugin
          ? `已切换到「${r.model.id}」，并激活桌宠插件「${r.activated_plugin}」（LLM 现在可以直接叫它做动作）`
          : `已切换到「${r.model.id}」（壳 watch config 自动重载）`,
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
      message.success(`模型 ${m.id} 已删除（资产 + 插件级联清除）`);
      load();
    } catch (e) {
      message.error(`删除失败：${(e as Error).message}`);
    }
  };

  return (
    <>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="桌宠模型资产（工作区 models/2D/）"
        description={
          <span style={{ fontSize: 13 }}>
            插件名 = 模型名，工具名 = 模型真实动作/表情名。选中模型即激活对应插件，
            对桌宠说「给我比个心」，LLM 会直接调用该模型的动作工具来驱动桌宠。
            没有动作/表情的模型同样可以切换（作为纯外观桌宠），只是不会生成插件。
            标注「内置」的模型由种子机制分发（随仓库分发、启动自动复原），不可删除。
          </span>
        }
      />

      {models.length === 0 && <Empty description="2D/ 目录下没有可用的模型资产" />}

      <Row gutter={[14, 14]}>
        {models.map(m => {
          const isActive = m.id === active;
          const hasCapability = m.motions.length > 0 || m.expressions.length > 0;
          return (
            <Col xs={24} sm={12} lg={8} key={m.id}>
              <Card
                size="small"
                hoverable
                style={{
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
                    {isActive && (
                      <Typography.Text type="success" style={{ fontSize: 12, marginRight: 8 }}>使用中</Typography.Text>
                    )}
                    {!isActive && hasCapability && (
                      <Typography.Text type="secondary" style={{ fontSize: 12, marginRight: 8 }}>点击切换</Typography.Text>
                    )}
                    {!isActive && !hasCapability && (
                      <Tag color="default" style={{ marginRight: 8 }}>无动作/表情</Tag>
                    )}
                    {m.builtin && (
                      <Tag color="blue" style={{ marginRight: 8 }}>内置</Tag>
                    )}
                    {!m.builtin && (
                      <Popconfirm
                        title="删除模型？"
                        description="将删除模型资产与对应桌宠插件（不可恢复）；删除使用中的模型会自动切换"
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

                {switching === m.id && <Typography.Text type="warning">切换中…</Typography.Text>}
              </Card>
            </Col>
          );
        })}
      </Row>
    </>
  );
}
