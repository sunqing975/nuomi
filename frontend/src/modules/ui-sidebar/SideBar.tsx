/** ui-sidebar：单栏侧边栏（对齐 Octop chatHistoryRail 按专家维度组织会话）。
 *  自上而下：品牌行 → 新会话 → 导航（插件）→ 会话视图（Agent 组 + 自定义组 + 未分组）
 *  → 底部设置。
 *  会话归属 Agent 实例（threads.agent，服务端写入当前 Agent）；组内会话默认 5 条
 *  + 展开其余/收起、置顶、移动自定义组、全局搜索、空标题未命名。
 *  文件树已移出侧栏：主区右上角按钮展开当前项目（存储单元）的文件树抽屉。 */
import { useEffect, useState } from "react";
import type { AgentInfo, ThreadInfo } from "../../api";
import { t as tr } from "../../i18n";
import ConfirmDialog, { type ConfirmState } from "../ui-confirm/ConfirmDialog";
import PromptDialog, { type PromptState } from "../ui-confirm/PromptDialog";
import {
  FolderIcon,
  FolderPlusIcon,
  GearIcon,
  LogoMark,
  PencilIcon,
  PinIcon,
  PlusIcon,
  PuzzleIcon,
  SearchIcon,
  TrashIcon,
  XIcon,
} from "../icons";

export type Tab = "chat" | "plugins";

const PIN_KEY = "nuomi.sidebar.pinned";
const EXPANDED_KEY = "nuomi.sidebar.expanded";
const GROUP_KEY = "nuomi.sidebar.groupExpanded";
/** 自定义分组（纯本地）：组名 → 会话 id 列表。对齐 Octop 会话 rail 的自定义分组。 */
const CUSTOM_KEY = "nuomi.sidebar.customGroups";
const COLLAPSED_SESSION_LIMIT = 5;
const UNGROUPED_KEY = "u";

/** 紧凑相对时间（对齐 dsh localized compact relative time）。 */
function relTime(iso: string): string {
  const at = new Date(iso).getTime();
  if (!Number.isFinite(at)) return "";
  const diff = Date.now() - at;
  const min = Math.floor(diff / 60000);
  if (min < 1) return tr("sidebar.timeJustNow");
  if (min < 60) return tr("sidebar.timeMinute", { n: min });
  const h = Math.floor(min / 60);
  if (h < 24) return tr("sidebar.timeHour", { n: h });
  const d = Math.floor(h / 24);
  if (d < 30) return tr("sidebar.timeDay", { n: d });
  const date = new Date(iso);
  return `${date.getMonth() + 1}/${date.getDate()}`;
}

function loadJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

interface Group {
  key: string;
  name: string;
  agentId: string | null;
  threads: ThreadInfo[];
}

export default function SideBar({
  tab,
  agents,
  threads,
  currentThreadId,
  onTab,
  onOpenSettings,
  onNewThread,
  onSelectThread,
  onSelectProject,
  onRenameThread,
  onDeleteThread,
}: {
  tab: "chat" | "plugins";
  agents: AgentInfo[];
  threads: ThreadInfo[];
  currentThreadId: string | null;
  onTab: (t: "chat" | "plugins") => void;
  onOpenSettings: () => void;
  onNewThread: () => void;
  onSelectThread: (id: string) => void;
  onSelectProject: (id: number | null) => void;
  onRenameThread: (id: string, title: string) => void;
  onDeleteThread: (id: string) => void;
}) {
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameText, setRenameText] = useState("");
  const [confirm, setConfirm] = useState<ConfirmState | null>(null);
  const [prompt, setPrompt] = useState<PromptState | null>(null);
  const [search, setSearch] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [pinned, setPinned] = useState<Record<string, string[]>>(() => loadJson(PIN_KEY, {}));
  const [expanded, setExpanded] = useState<Record<string, boolean>>(() => loadJson(EXPANDED_KEY, {}));
  const [groupOpen, setGroupOpen] = useState<Record<string, boolean>>(() => loadJson(GROUP_KEY, {}));
  /** 自定义分组：组名 → 会话 id 列表（localStorage 持久化） */
  const [customGroups, setCustomGroups] = useState<Record<string, string[]>>(() => loadJson(CUSTOM_KEY, {}));
  useEffect(() => localStorage.setItem(PIN_KEY, JSON.stringify(pinned)), [pinned]);
  useEffect(() => localStorage.setItem(EXPANDED_KEY, JSON.stringify(expanded)), [expanded]);
  useEffect(() => localStorage.setItem(GROUP_KEY, JSON.stringify(groupOpen)), [groupOpen]);
  useEffect(() => localStorage.setItem(CUSTOM_KEY, JSON.stringify(customGroups)), [customGroups]);

  const searching = search.trim().length > 0;
  const q = search.trim().toLowerCase();

  // 分组树：Agent 实例（对齐 Octop rail 按专家维度）+ 自定义组 + 未分组（最后）
  const grouped = new Map<string, ThreadInfo[]>();
  for (const t of threads) {
    const key = t.agent != null ? `a:${t.agent}` : UNGROUPED_KEY;
    const arr = grouped.get(key);
    if (arr) arr.push(t);
    else grouped.set(key, [t]);
  }
  const byId = new Map(threads.map((t) => [t.id, t]));
  const groups: Group[] = [
    ...agents.map((a) => ({ key: `a:${a.id}`, name: a.display_name, agentId: a.id, threads: grouped.get(`a:${a.id}`) ?? [] })),
    ...Object.entries(customGroups)
      .filter(([, ids]) => ids.length > 0)
      .map(([name, ids]) => ({
        key: `c:${name}`,
        name,
        agentId: null,
        threads: ids.map((id) => byId.get(id)).filter((t): t is ThreadInfo => Boolean(t)),
      })),
    { key: UNGROUPED_KEY, name: tr("sidebar.ungrouped"), agentId: null, threads: grouped.get(UNGROUPED_KEY) ?? [] },
  ].filter((g) => g.threads.length > 0);

  const isGroupOpen = (g: Group) => (searching ? true : groupOpen[g.key] ?? true);

  const toggleGroup = (g: Group) => {
    setGroupOpen((o) => ({ ...o, [g.key]: !(o[g.key] ?? true) }));
  };

  const renderThreads = (g: Group) => {
    const storageKey = g.agentId !== null ? `a:${g.agentId}` : g.key;
    const pinnedIds = new Set(pinned[storageKey] ?? []);
    const sorted = [...g.threads].sort((a, b) => {
      const ap = pinnedIds.has(a.id) ? 0 : 1;
      const bp = pinnedIds.has(b.id) ? 0 : 1;
      if (ap !== bp) return ap - bp;
      return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
    });
    const filtered = searching ? sorted.filter((t) => t.title.toLowerCase().includes(q)) : sorted;
    const groupExpanded = Boolean(expanded[storageKey]);
    const visible = searching || groupExpanded ? filtered : filtered.slice(0, COLLAPSED_SESSION_LIMIT);
    const hiddenCount = filtered.length - visible.length;

    const togglePin = (id: string) => {
      const key = storageKey;
      const cur = pinned[key] ?? [];
      const next = cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id];
      setPinned((p) => ({ ...p, [key]: next }));
    };
    const toggleExpanded = () => setExpanded((e) => ({ ...e, [storageKey]: !groupExpanded }));

    return (
      <div className="thread-list">
        {visible.map((t) => {
          // 占位标题（模型命名前）一律显示「未命名」，不出现「新建会话」等占位字
          const title = (!t.title || t.title === "新会话" || t.title === "新建会话") ? tr("sidebar.untitled") : t.title;
          const isPinned = pinnedIds.has(t.id);
          return (
            <div
              key={t.id}
              className={`thread-item ${t.id === currentThreadId ? "on" : ""}`}
              onClick={() => {
                onSelectProject(t.project_id ?? null);
                onSelectThread(t.id);
                onTab("chat");
              }}
            >
              {renamingId === t.id ? (
                <input
                  className="thread-rename-input"
                  autoFocus
                  value={renameText}
                  onClick={(e) => e.stopPropagation()}
                  onChange={(e) => setRenameText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && renameText.trim()) {
                      onRenameThread(t.id, renameText.trim());
                      setRenamingId(null);
                    }
                    if (e.key === "Escape") setRenamingId(null);
                  }}
                />
              ) : (
                <>
                  <span className="thread-title">
                    {isPinned && <span className="thread-pin-mark" title={tr("sidebar.pinnedTitle")}>📌</span>}
                    {title}
                  </span>
                  <span className="thread-time">{relTime(t.updated_at)}</span>
                  <span className="thread-actions">
                    <button
                      className={isPinned ? "pin on" : "pin"}
                      title={isPinned ? tr("sidebar.unpin") : tr("sidebar.pin")}
                      onClick={(e) => {
                        e.stopPropagation();
                        togglePin(t.id);
                      }}
                    >
                      <PinIcon />
                    </button>
                    <button
                      title={tr("sidebar.moveToGroup")}
                      onClick={(e) => {
                        e.stopPropagation();
                        setPrompt({
                          message: tr("sidebar.moveToGroupPrompt"),
                          placeholder: tr("sidebar.moveToGroupPlaceholder"),
                          confirmText: tr("common.confirm"),
                          onSubmit: (name) => {
                            const target = name.trim();
                            setCustomGroups((g) => {
                              const next: Record<string, string[]> = {};
                              for (const [k, ids] of Object.entries(g)) {
                                const rest = ids.filter((x) => x !== t.id);
                                if (rest.length) next[k] = rest;
                              }
                              if (target) {
                                const cur = next[target] ?? [];
                                if (!cur.includes(t.id)) next[target] = [...cur, t.id];
                              }
                              return next;
                            });
                          },
                        });
                      }}
                    >
                      <FolderPlusIcon />
                    </button>
                    <button
                      title={tr("sidebar.rename")}
                      onClick={(e) => {
                        e.stopPropagation();
                        setRenamingId(t.id);
                        setRenameText(t.title);
                      }}
                    >
                      <PencilIcon />
                    </button>
                    <button
                      title={tr("common.delete")}
                      onClick={(e) => {
                        e.stopPropagation();
                        setConfirm({
                          message: tr("sidebar.deleteThreadConfirm", { title }),
                          detail: tr("sidebar.deleteThreadDetail"),
                          danger: true,
                          onConfirm: () => onDeleteThread(t.id),
                        });
                      }}
                    >
                      <TrashIcon />
                    </button>
                  </span>
                </>
              )}
            </div>
          );
        })}
        {filtered.length === 0 && !searching && g.agentId !== null && (
          <div className="thread-empty">{tr("sidebar.noThreads")}</div>
        )}
        {!searching && hiddenCount > 0 && (
          <button className="thread-more-btn" onClick={toggleExpanded}>
            {tr("sidebar.expandMore", { n: hiddenCount })}
          </button>
        )}
        {!searching && groupExpanded && filtered.length > COLLAPSED_SESSION_LIMIT && (
          <button className="thread-more-btn" onClick={toggleExpanded}>
            {tr("sidebar.collapse")}
          </button>
        )}
      </div>
    );
  };

  const totalMatches = groups.reduce((n, g) => n + (searching ? g.threads.filter((t) => t.title.toLowerCase().includes(q)).length : g.threads.length), 0);

  return (
    <aside className="sidebar">
      {/* 品牌行：纯展示，非交互 */}
      <div className="sidebar-brand">
        <span className="brand-mark">
          <LogoMark />
        </span>
        <span>
          <div className="brand-wordmark">{tr("brand.name")}</div>
          <div className="brand-sub">{tr("sidebar.agent")}</div>
        </span>
      </div>

      {/* 新会话 */}
      <button className="new-session-btn" onClick={() => onNewThread()}>
        <PlusIcon size={14} />
        {tr("sidebar.newSession")}
      </button>

      {/* 导航：插件 */}
      <button
        className={`nav-item ${tab === "plugins" ? "on" : ""}`}
        onClick={() => onTab("plugins")}
      >
        <span className="nav-icon"><PuzzleIcon /></span>
        {tr("sidebar.navPlugins")}
      </button>

      {/* 工作区浏览器（dsh WorkspaceBrowser：标题行右侧图标，非整行搜索框） */}
      <div className="workspace-head">
        <span className="workspace-tabs">{tr("sidebar.tabSessions")}</span>
        <span className="workspace-head-actions">
          <button
            className={`icon-btn ${searchOpen ? "on" : ""}`}
            title={tr("sidebar.searchPlaceholder")}
            onClick={() => setSearchOpen((v) => !v)}
          >
            <SearchIcon />
          </button>
        </span>
      </div>

      <div className="session-tree">
        {searchOpen && (
          <input
            className="thread-search"
            placeholder={tr("sidebar.searchPlaceholder")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            autoFocus
          />
        )}
        <div className="group-list">
          {groups.map((g) => {
            const open = isGroupOpen(g);
            const on = false;
            const count = searching
              ? g.threads.filter((t) => t.title.toLowerCase().includes(q)).length
              : g.threads.length;
            if (searching && count === 0) return null;
            return (
              <div key={g.key} className={`workspace-group ${on ? "on" : ""} ${open ? "open" : ""}`}>
                <div
                  className="group-head"
                  role="button"
                  tabIndex={0}
                  onClick={() => toggleGroup(g)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      toggleGroup(g);
                    }
                  }}
                  title={tr("sidebar.toggleGroup")}
                >
                  <span className="group-icon"><FolderIcon /></span>
                  <span className="group-title">{g.name}</span>
                  <span className="group-count">{count}</span>
                  {g.key.startsWith("c:") && (
                    <button
                      className="icon-btn group-more-btn"
                      title={tr("sidebar.deleteGroup")}
                      onClick={(e) => {
                        e.stopPropagation();
                        setCustomGroups((cur) => {
                          const next = { ...cur };
                          delete next[g.name];
                          return next;
                        });
                      }}
                    >
                      <XIcon />
                    </button>
                  )}
                </div>
                {open && renderThreads(g)}
              </div>
            );
          })}
          {searching && totalMatches === 0 && <div className="thread-empty">{tr("sidebar.noMatch")}</div>}
        </div>
      </div>

      {/* 底部设置 */}
      <div className="sidebar-foot">
        <button className="foot-settings" onClick={() => onOpenSettings()}>
          <span className="nav-icon"><GearIcon /></span>
          {tr("sidebar.settings")}
        </button>
      </div>
      {confirm && <ConfirmDialog state={confirm} onClose={() => setConfirm(null)} />}
      {prompt && <PromptDialog state={prompt} onClose={() => setPrompt(null)} />}
    </aside>
  );
}
