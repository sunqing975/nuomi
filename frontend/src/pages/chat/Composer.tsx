/**
 * Composer：对话输入区（能力 chips + 选择器 + 中断重试条 + 输入框 + 发送/停止）。
 *
 * 从 Chat.tsx 抽出（P0-4，2026-10-06）——纯重构，行为不变。
 * 选择器（技能/连接器/知识库/模型）沿用原 Popover 交互；发送/停止/重试回调由
 * ChatPage 的 useChatStream 提供。
 */

import {
  ApiOutlined, BookOutlined, CloseOutlined, SendOutlined, StopOutlined, ThunderboltOutlined,
} from '@ant-design/icons';
import { Button, Input, Popover, Select, Space, Switch } from 'antd';
import type { ReactNode } from 'react';

import type { ConnectorServer, KnowledgeBase, Skill, SkillPackage } from '../../api';
import { MODEL_AUTO, type InterruptedTurn } from './useChatStream';

/** 能力 chip（输入框上方，可移除） */
function AbilityChip({ label, color, onRemove }: { label: string; color: string; onRemove: () => void }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4, padding: '2px 8px', borderRadius: 999,
      fontSize: 12, background: `${color}1a`, color, border: `1px solid ${color}55`,
    }}>
      {label}
      <CloseOutlined style={{ fontSize: 10, cursor: 'pointer' }} onClick={onRemove} />
    </span>
  );
}

/** 技能选择器（Popover 三分组：已启用技能 / 内置技能 / 已启用技能包；技能包=整包勾选） */
function SkillPicker({
  skills, builtin, packages, selected, onToggleSkill, onTogglePackage,
}: {
  skills: Skill[]; builtin: Skill[]; packages: SkillPackage[];
  selected: string[]; onToggleSkill: (name: string) => void; onTogglePackage: (pkg: SkillPackage) => void;
}) {
  const GroupLabel = ({ children }: { children: ReactNode }) => (
    <div style={{ fontSize: 11, color: 'var(--label-4)', padding: '6px 10px 2px', fontWeight: 600 }}>{children}</div>
  );
  const Row = ({ active, onClick, title, desc }: { active: boolean; onClick: () => void; title: string; desc?: string }) => (
    <div
      onClick={onClick}
      style={{
        display: 'flex', gap: 8, alignItems: 'flex-start', padding: '7px 10px', borderRadius: 8,
        cursor: 'pointer', background: active ? 'var(--info-soft)' : 'transparent', marginBottom: 2,
      }}
    >
      <span style={{ color: 'var(--link)', fontSize: 13, marginTop: 1 }}>{active ? '☑' : '☐'}</span>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 500 }}>{title}</div>
        {desc ? (
          <div style={{ fontSize: 12, color: 'var(--label-3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{desc}</div>
        ) : null}
      </div>
    </div>
  );
  const empty = skills.length === 0 && builtin.length === 0 && packages.length === 0;
  const content = (
    <div style={{ width: 300, maxHeight: 340, overflow: 'auto' }}>
      {empty ? (
        <div style={{ color: 'var(--label-3)', textAlign: 'center', padding: 16 }}>暂无可用技能，先到「技能」页安装/启用</div>
      ) : (
        <>
          {skills.length > 0 && (
            <>
              <GroupLabel>已启用的技能</GroupLabel>
              {skills.map(s => (
                <Row key={s.name} active={selected.includes(s.name)} onClick={() => onToggleSkill(s.name)}
                  title={s.name} desc={s.description || undefined} />
              ))}
            </>
          )}
          {builtin.length > 0 && (
            <>
              <GroupLabel>内置技能</GroupLabel>
              {builtin.map(b => (
                <Row key={`builtin-${b.name}`} active={selected.includes(b.name)} onClick={() => onToggleSkill(b.name)}
                  title={b.name} desc={b.description || '随 harness 内置分发，只读'} />
              ))}
            </>
          )}
          {packages.length > 0 && (
            <>
              <GroupLabel>已启用的技能包</GroupLabel>
              {packages.map(p => {
                const slugs = (p.skills || []).filter(s => s.enabled).map(s => s.slug);
                const active = slugs.length > 0 && slugs.some(x => selected.includes(x));
                return (
                  <Row key={`pkg-${p.id}`} active={active} onClick={() => onTogglePackage(p)}
                    title={`${p.name}（${p.skill_count ?? slugs.length} 技能）`} desc={p.description || undefined} />
                );
              })}
            </>
          )}
        </>
      )}
    </div>
  );
  return (
    <Popover trigger="click" placement="topLeft" content={content}>
      <Button size="small" icon={<ThunderboltOutlined />}>技能{selected.length ? ` (${selected.length})` : ''}</Button>
    </Popover>
  );
}

/** 连接器选择器（Popover Switch 列表） */
function ConnectorPicker({ connectors, selected, onToggle }: { connectors: ConnectorServer[]; selected: string[]; onToggle: (name: string) => void }) {
  const content = (
    <div style={{ width: 280, maxHeight: 320, overflow: 'auto' }}>
      {connectors.length === 0 ? (
        <div style={{ color: 'var(--label-3)', textAlign: 'center', padding: 16 }}>暂无连接器，先到「连接器」页添加</div>
      ) : (
        connectors.map(c => (
          <div key={c.name} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 10px', borderRadius: 8 }}>
            <span style={{ fontSize: 13 }}>{c.name}</span>
            <Switch size="small" checked={selected.includes(c.name)} onChange={() => onToggle(c.name)} />
          </div>
        ))
      )}
    </div>
  );
  return (
    <Popover trigger="click" placement="topLeft" content={content}>
      <Button size="small" icon={<ApiOutlined />}>连接器{selected.length ? ` (${selected.length})` : ''}</Button>
    </Popover>
  );
}

/** 知识库选择器（Popover 多选；不选 = 不注入，与技能/连接器同维度） */
function KnowledgePicker({ bases, selected, onToggle, disabled }: { bases: KnowledgeBase[]; selected: string[]; onToggle: (id: string) => void; disabled?: boolean }) {
  const content = (
    <div style={{ width: 300, maxHeight: 320, overflow: 'auto' }}>
      {bases.length === 0 ? (
        <div style={{ color: 'var(--label-3)', textAlign: 'center', padding: 16 }}>暂无知识库，先到「知识库」页创建</div>
      ) : (
        bases.map(b => {
          const active = selected.includes(b.id);
          return (
            <div
              key={b.id}
              onClick={() => onToggle(b.id)}
              style={{
                display: 'flex', gap: 8, alignItems: 'flex-start', padding: '8px 10px', borderRadius: 8,
                cursor: 'pointer', background: active ? 'var(--pink-soft)' : 'transparent', marginBottom: 2,
              }}
            >
              <span style={{ color: '#eb2f96', fontSize: 13, marginTop: 1 }}>{active ? '☑' : '☐'}</span>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 500 }}>{b.name}</div>
                {b.description ? (
                  <div style={{ fontSize: 12, color: 'var(--label-3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{b.description}</div>
                ) : null}
              </div>
            </div>
          );
        })
      )}
    </div>
  );
  return (
    <Popover trigger="click" placement="topLeft" content={content}>
      <Button size="small" icon={<BookOutlined />} disabled={disabled}>知识库{selected.length ? ` (${selected.length})` : ''}</Button>
    </Popover>
  );
}

export interface ComposerProps {
  input: string;
  setInput: (v: string) => void;
  sending: boolean;
  agentId: string | null;
  skills: Skill[];
  builtinSkills: Skill[];
  skillPackages: SkillPackage[];
  connectors: ConnectorServer[];
  knowledgeBases: KnowledgeBase[];
  kbEnabled: boolean;
  selectedSkills: string[];
  selectedConnectors: string[];
  selectedKnowledgeBaseIds: string[];
  selectedModel: string | null;
  modelOptions: { value: string; label: string }[];
  interrupted: InterruptedTurn | null;
  onSend: (text: string) => void;
  onStop: () => void;
  onToggleSkill: (name: string) => void;
  onToggleSkillPackage: (pkg: SkillPackage) => void;
  onToggleConnector: (name: string) => void;
  onToggleKnowledgeBase: (id: string) => void;
  /** 模型下拉选中（含「自动」） */
  onChangeModel: (value: string) => void;
  /** 移除模型 chip → 回到「自动」 */
  onResetModel: () => void;
  onRetry: (turn: InterruptedTurn) => void;
  onDismissInterrupted: () => void;
}

export default function Composer(props: ComposerProps) {
  const {
    input, setInput, sending, agentId,
    skills, builtinSkills, skillPackages, connectors, knowledgeBases, kbEnabled,
    selectedSkills, selectedConnectors, selectedKnowledgeBaseIds, selectedModel, modelOptions,
    interrupted,
    onSend, onStop,
    onToggleSkill, onToggleSkillPackage, onToggleConnector, onToggleKnowledgeBase, onChangeModel, onResetModel,
    onRetry, onDismissInterrupted,
  } = props;

  return (
    <div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
        {selectedSkills.map(s => (
          <AbilityChip key={s} label={`技能 · ${s}`} color="#1677ff" onRemove={() => onToggleSkill(s)} />
        ))}
        {selectedConnectors.map(c => (
          <AbilityChip key={c} label={`连接器 · ${c}`} color="#52c41a" onRemove={() => onToggleConnector(c)} />
        ))}
        {selectedKnowledgeBaseIds.map(id => (
          <AbilityChip key={id} label={`知识库 · ${knowledgeBases.find(b => b.id === id)?.name ?? id}`} color="#eb2f96" onRemove={() => onToggleKnowledgeBase(id)} />
        ))}
        {selectedModel && selectedModel !== MODEL_AUTO && (
          <AbilityChip key={selectedModel} label={`模型 · ${selectedModel}`} color="#722ed1" onRemove={onResetModel} />
        )}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <Space size={4}>
          <SkillPicker skills={skills} builtin={builtinSkills} packages={skillPackages} selected={selectedSkills} onToggleSkill={onToggleSkill} onTogglePackage={onToggleSkillPackage} />
          <ConnectorPicker connectors={connectors} selected={selectedConnectors} onToggle={onToggleConnector} />
          <KnowledgePicker bases={knowledgeBases} selected={selectedKnowledgeBaseIds} onToggle={onToggleKnowledgeBase} disabled={!kbEnabled} />
          <Select
            size="small"
            placeholder="选择模型（默认自动）"
            style={{ width: 170 }}
            value={selectedModel ?? undefined}
            onChange={onChangeModel}
            options={modelOptions}
            disabled={modelOptions.length === 0}
            popupMatchSelectWidth={false}
          />
        </Space>
      </div>
      {interrupted && !sending && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6,
          padding: '6px 10px', background: 'var(--warn-bg)', border: '1px solid var(--warn-line)',
          borderRadius: 6, fontSize: 12, color: 'var(--accent-text)',
        }}>
          <span>上一轮回复被中断（未收到完成帧）。</span>
          <a onClick={() => onRetry(interrupted)} style={{ color: 'var(--link)' }}>重试</a>
          <a onClick={onDismissInterrupted} style={{ color: 'var(--label-4)' }}>忽略</a>
        </div>
      )}
      <div style={{
        display: 'flex', gap: 8, alignItems: 'flex-end',
        border: '1px solid var(--line-3)', borderRadius: 12, background: 'var(--surface)',
        padding: '8px 8px 8px 12px',
      }}>
        <Input.TextArea
          value={input}
          onChange={e => setInput(e.target.value)}
          onPressEnter={e => {
            // 中文输入法候选词确认也会发 Enter：合成态必须放行，否则半句话被发出去
            if ((e.nativeEvent as KeyboardEvent).isComposing) return;
            if (!e.shiftKey) { e.preventDefault(); onSend(input); }
          }}
          placeholder="输入消息，Enter 发送"
          autoSize={{ minRows: 1, maxRows: 6 }}
          disabled={sending || !agentId}
          variant="borderless"
          style={{ flex: 1, padding: '4px 0' }}
        />
        {sending ? (
          <Button danger icon={<StopOutlined />} onClick={onStop}>停止</Button>
        ) : (
          <Button
            type="primary"
            icon={<SendOutlined />}
            onClick={() => onSend(input)}
            disabled={!agentId || !input.trim()}
          >发送</Button>
        )}
      </div>
    </div>
  );
}
