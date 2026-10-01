/** ui-sidebar：单栏侧边栏（工作区对齐 dsh ui-workspace WorkspaceBrowser）。
 *  自上而下：品牌行 → 新会话 → 导航（插件）→ 工作区浏览器（项目分组树 + 会话列表）
 *  → 底部设置。
 *  对齐 dsh：项目（Workspace）直接铺为可折叠分组（无下拉），未分组会话为独立组；
 *  组内会话默认 5 条 + 展开其余/收起、置顶（本地持久化）、全局搜索、空标题未命名。 */
import { useEffect, useState } from "react";
import type { ProjectInfo, ThreadInfo } from "../../api";
import { t as tr } from "../../i18n";
import {
  ChevronDownIcon,
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
} from "../icons";

export type Tab = "chat" | "plugins";

const PIN_KEY = "nuomi.sidebar.pinned";
const EXPANDED_KEY = "nuomi.sidebar.expanded";
const GROUP_KEY = "nuomi.sidebar.groupExpanded";
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
  projectId: number | null;
  threads: ThreadInfo[];
}

export default function SideBar({
  tab,
  projects,
  threads,
  currentProjectId,
  currentThreadId,
  open,
  onClose,
  onTab,
  onOpenSettings,
  onNewThread,
  onNewThreadIn,
  onSelectThread,
  onSelectProject,
  onCreateProject,
  onRenameThread,
  onDeleteThread,
}: {
  tab: "chat" | "plugins";
  projects: ProjectInfo[];
  threads: ThreadInfo[];
  currentProjectId: number | null;
  currentThreadId: string | null;
  /** 移动端抽屉展开态 */
  open: boolean;
  onClose: () => void;
  onTab: (t: "chat" | "plugins") => void;
  onOpenSettings: () => void;
  onNewThread: () => void;
  /** 在指定项目（null=未分组）下新建会话 */
  onNewThreadIn: (projectId: number | null) => void;
  onSelectThread: (id: string) => void;
  onSelectProject: (id: number | null) => void;
  onCreateProject: (name: string) => void;
  onRenameThread: (id: string, title: string) => void;
  onDeleteThread: (id: string) => void;
}) {
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameText, setRenameText] = useState("");
  const [search, setSearch] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [pinned, setPinned] = useState<Record<number, string[]>>(() => loadJson(PIN_KEY, {}));
  const [expanded, setExpanded] = useState<Record<number, boolean>>(() => loadJson(EXPANDED_KEY, {}));
  const [groupOpen, setGroupOpen] = useState<Record<string, boolean>>(() => loadJson(GROUP_KEY, {}));

  useEffect(() => localStorage.setItem(PIN_KEY, JSON.stringify(pinned)), [pinned]);
  useEffect(() => localStorage.setItem(EXPANDED_KEY, JSON.stringify(expanded)), [expanded]);
  useEffect(() => localStorage.setItem(GROUP_KEY, JSON.stringify(groupOpen)), [groupOpen]);

  const searching = search.trim().length > 0;
  const q = search.trim().toLowerCase();

  // 分组树：项目（含空项目）+ 未分组（dsh Ungrouped，最后）
  const grouped = new Map<string, ThreadInfo[]>();
  for (const t of threads) {
    const key = t.project_id != null ? `p:${t.project_id}` : UNGROUPED_KEY;
    const arr = grouped.get(key);
    if (arr) arr.push(t);
    else grouped.set(key, [t]);
  }
  const groups: Group[] = [
    ...projects.map((p) => ({ key: `p:${p.id}`, name: p.name, projectId: p.id, threads: grouped.get(`p:${p.id}`) ?? [] })),
    { key: UNGROUPED_KEY, name: tr("sidebar.ungrouped"), projectId: null, threads: grouped.get(UNGROUPED_KEY) ?? [] },
  ].filter((g) => g.threads.length > 0 || g.projectId !== null);

  const isGroupOpen = (g: Group) => (searching ? true : groupOpen[g.key] ?? true);

  const toggleGroup = (g: Group) => {
    setGroupOpen((o) => ({ ...o, [g.key]: !(o[g.key] ?? true) }));
  };

  const renderThreads = (g: Group) => {
    const pinnedIds = new Set(pinned[g.projectId ?? 0] ?? []);
    const sorted = [...g.threads].sort((a, b) => {
      const ap = pinnedIds.has(a.id) ? 0 : 1;
      const bp = pinnedIds.has(b.id) ? 0 : 1;
      if (ap !== bp) return ap - bp;
      return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
    });
    const filtered = searching ? sorted.filter((t) => t.title.toLowerCase().includes(q)) : sorted;
    const groupExpanded = Boolean(expanded[g.projectId ?? 0]);
    const visible = searching || groupExpanded ? filtered : filtered.slice(0, COLLAPSED_SESSION_LIMIT);
    const hiddenCount = filtered.length - visible.length;

    const togglePin = (id: string) => {
      const key = g.projectId ?? 0;
      const cur = pinned[key] ?? [];
      const next = cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id];
      setPinned((p) => ({ ...p, [key]: next }));
    };
    const toggleExpanded = () => setExpanded((e) => ({ ...e, [g.projectId ?? 0]: !groupExpanded }));

    return (
      <div className="thread-list">
        {visible.map((t) => {
          const title = t.title || tr("sidebar.untitled");
          const isPinned = pinnedIds.has(t.id);
          return (
            <div
              key={t.id}
              className={`thread-item ${t.id === currentThreadId ? "on" : ""}`}
              onClick={() => {
                onSelectProject(g.projectId);
                onSelectThread(t.id);
                onTab("chat");
                onClose();
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
                        if (window.confirm(tr("sidebar.deleteThreadConfirm", { title }))) onDeleteThread(t.id);
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
        {filtered.length === 0 && !searching && g.projectId !== null && (
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
    <aside className={`sidebar ${open ? "open" : ""}`}>
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
      <button className="new-session-btn" onClick={() => { onNewThread(); onClose(); }}>
        <PlusIcon size={14} />
        {tr("sidebar.newSession")}
      </button>

      {/* 导航：插件 */}
      <button
        className={`nav-item ${tab === "plugins" ? "on" : ""}`}
        onClick={() => { onTab("plugins"); onClose(); }}
      >
        <span className="nav-icon"><PuzzleIcon /></span>
        {tr("sidebar.navPlugins")}
      </button>

      {/* 工作区浏览器（dsh WorkspaceBrowser：标题行右侧图标，非整行搜索框） */}
      <div className="workspace-head">
        <span>{tr("sidebar.workspace")}</span>
        <span className="workspace-head-actions">
          <button
            className={`icon-btn ${searchOpen ? "on" : ""}`}
            title={tr("sidebar.searchPlaceholder")}
            onClick={() => setSearchOpen((v) => !v)}
          >
            <SearchIcon />
          </button>
          <button
            className="icon-btn"
            title={tr("sidebar.newProjectIcon")}
            onClick={() => {
              const name = window.prompt(tr("sidebar.newProjectName"));
              if (name?.trim()) onCreateProject(name.trim());
            }}
          >
            <FolderPlusIcon />
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
            const on = g.projectId === currentProjectId;
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
                  <button
                    className="group-new"
                    title={tr("sidebar.newThreadIn")}
                    onClick={(e) => {
                      e.stopPropagation();
                      onNewThreadIn(g.projectId);
                      onClose();
                    }}
                  >
                    <PlusIcon size={12} />
                  </button>
                  <span className="model-caret group-caret">
                    <ChevronDownIcon />
                  </span>
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
        <button className="foot-settings" onClick={() => { onOpenSettings(); onClose(); }}>
          <span className="nav-icon"><GearIcon /></span>
          {tr("sidebar.settings")}
        </button>
      </div>
    </aside>
  );
}
