/** ui-chat/FilesPanel：项目文件树（主区右上角抽屉内容，2026-10-02 从侧栏移入）。
 *  展示 /api/projects/{id}/tree 返回的目录树：目录行可展开/收起，文件行显示大小；
 *  隐藏项/依赖目录由后端跳过。展开状态本地持久化（nuomi.filesOpen）。 */
import { useEffect, useState } from "react";
import { fetchProjectTree, type WorkspaceEntry, type WorkspaceTree } from "../../api";
import { t as tr } from "../../i18n";
import { ChevronDownIcon, FolderIcon } from "../icons";

const OPEN_KEY = "nuomi.filesOpen";

function fmtSize(n?: number): string {
  if (n == null) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function loadOpen(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(OPEN_KEY);
    return raw ? (JSON.parse(raw) as Record<string, boolean>) : {};
  } catch {
    return {};
  }
}

export default function FilesPanel({ projectId, refreshTick }: { projectId: number; refreshTick: number }) {
  const [tree, setTree] = useState<WorkspaceTree | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<Record<string, boolean>>(loadOpen);

  useEffect(() => {
    setTree(null);
    setError(null);
    fetchProjectTree(projectId)
      .then((t) => {
        setTree(t);
        setError(null);
      })
      .catch((e) => setError(String(e?.message ?? e)));
  }, [projectId, refreshTick]);

  useEffect(() => {
    try {
      localStorage.setItem(OPEN_KEY, JSON.stringify(open));
    } catch {
      /* 忽略 */
    }
  }, [open]);

  const toggle = (path: string) => setOpen((o) => ({ ...o, [path]: !o[path] }));

  const render = (entries: WorkspaceEntry[], depth: number, path: string): React.ReactNode[] =>
    entries.map((e) => {
      const p = `${path}/${e.name}`;
      if (e.type === "dir") {
        const isOpen = Boolean(open[p]);
        return (
          <div key={p}>
            <div
              className={`file-row dir ${isOpen ? "open" : ""}`}
              role="button"
              tabIndex={0}
              style={{ paddingLeft: depth * 16 + 8 }}
              onClick={() => toggle(p)}
              onKeyDown={(ev) => {
                if (ev.key === "Enter" || ev.key === " ") {
                  ev.preventDefault();
                  toggle(p);
                }
              }}
            >
              <span className="file-caret"><ChevronDownIcon size={12} /></span>
              <span className="file-icon"><FolderIcon size={14} /></span>
              <span className="file-name">{e.name}</span>
              {e.children && e.children.length > 0 && <span className="file-count">{e.children.length}</span>}
            </div>
            {isOpen && e.children && (
              <div>{render(e.children, depth + 1, p)}</div>
            )}
          </div>
        );
      }
      return (
        <div
          key={p}
          className="file-row file"
          style={{ paddingLeft: depth * 16 + 8 }}
          title={p}
        >
          <span className="file-caret-placeholder" />
          <span className="file-icon"><span className="file-dot" /></span>
          <span className="file-name">{e.name}</span>
          <span className="file-size">{fmtSize(e.size)}</span>
        </div>
      );
    });

  return (
    <div className="files-panel">
      <div className="files-head">
        <span className="files-root" title={tree?.root ?? ""}>{tree?.root ?? tr("sidebar.filesRoot")}</span>
      </div>
      {error === "NO_DIR" ? (
        <div className="files-empty">{tr("sidebar.filesNoDir")}</div>
      ) : error ? (
        <div className="files-empty error">{tr("sidebar.filesError")}</div>
      ) : !tree ? (
        <div className="files-empty">{tr("sidebar.filesLoading")}</div>
      ) : tree.entries.length === 0 ? (
        <div className="files-empty">{tr("sidebar.filesEmpty")}</div>
      ) : (
        <div className="files-tree">{render(tree.entries, 0, "")}</div>
      )}
    </div>
  );
}
