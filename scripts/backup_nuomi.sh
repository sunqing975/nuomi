#!/usr/bin/env bash
# =============================================================================
# 糯米数据根备份 / 恢复（backup_nuomi.sh backup|restore|list）
#
# 为什么要有这个脚本：整个产品的事实都在本机一个目录里（NUOMI_HOME：人格
# persona MD + 长期记忆 sqlite + nuomi.db 里的会话/插件/知识库元数据 +
# connectors.json + 密钥 providers.json/env.json/langfuse.json + 知识索引），
# 而仓库里此前**没有任何备份工具，也没有任何 export 端点**（live openapi 76 个
# path 里只有 7 个 `*/import`）。磁盘坏了 = 记忆和人格一起没了，无从恢复。
#
# 三个设计约束（都是踩出来的）：
#  1) memory.sqlite 家族是 WAL 模式：直接 cp 主文件会丢掉 -wal 里未合并的
#     最后一截（实测 -wal 有 3.4MB，比主文件 820KB 还大）。所以所有 *.db/*.sqlite
#     一律走 `VACUUM INTO` 出**单文件一致快照**，不拷 -wal/-shm，也不碰原库。
#  2) 备份必须"能恢复"才算数，不是"能打包"就算数：restore 会先对每个库跑
#     integrity_check，再做一次恢复前自备份。未验证的备份 = 安慰剂。
#  3) 默认排除 models/（110MB 可重下的 ONNX 嵌入模型）、logs/、tmp/ ——
#     不然备份体积被可再生内容撑爆，真正的记忆只占 30MB。要留就 --with-models。
#
# 数据根解析顺序与 backend/app/config.py 完全一致：
#   $NUOMI_HOME → 仓库 .env 里的 NUOMI_HOME= → default_data_root()
#   （macOS: ~/Library/Application Support/Nuomi，其它: ~/.nuomi）
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SQLITE_BIN="${SQLITE_BIN:-/usr/bin/sqlite3}"
BACKUP_DIR="${NUOMI_BACKUP_DIR:-$HOME/Nuomi-backups}"
KEEP="${NUOMI_BACKUP_KEEP:-10}"
WITH_MODELS=0
FORCE=0
ASSUME_YES=0
DELETE_EXTRAS=0
TARGET_HOME=""

usage() {
  cat <<'EOF'
用法：scripts/backup_nuomi.sh <command> [options]

  backup    把数据根打包成 ~/Nuomi-backups/nuomi-backup-<时间戳>.tar.gz
  restore   从指定 tar 恢复：scripts/backup_nuomi.sh restore <tar> [--home DIR] [--yes] [--delete-extras] [--force]
  list      列出已有备份（新的在前）

选项：
  --home DIR        覆盖数据根（默认按 NUOMI_HOME / .env / 内置默认值解析）
  --dest DIR        备份目录（默认 $NUOMI_BACKUP_DIR 或 ~/Nuomi-backups）
  --keep N          保留份数（默认 $NUOMI_BACKUP_KEEP 或 10；旧的手动删除）
  --with-models     连 models/（可重下的 ONNX 模型，约 110MB）一起备份
  --no-confirm      backup 时不问；restore 必须 --yes
  --delete-extras   restore 时删掉目标里"备份之后新增"的文件（默认只做覆盖式合并）
  --force           restore 时跳过"后端还在跑"的检查（不建议：正在写的库会被覆盖）

一致性说明：*.db / *.sqlite 用 `VACUUM INTO` 生成快照（WAL 已合并，单文件），
其余文件 rsync 原样拷贝；logs/ tmp/ *.sqlite-wal/-shm/*-journal/.DS_Store 不进备份。
EOF
}

die() { echo "✘ $*" >&2; exit 1; }

resolve_home() {
  if [ -n "$TARGET_HOME" ]; then printf '%s' "$TARGET_HOME"; return; fi
  if [ -n "${NUOMI_HOME:-}" ]; then printf '%s' "${NUOMI_HOME}"; return; fi
  if [ -f "$REPO_ROOT/.env" ]; then
    local line
    line="$(grep -E '^[[:space:]]*(NUOMI_HOME|nuomi_home)[[:space:]]*=' "$REPO_ROOT/.env" | tail -1 || true)"
    if [ -n "$line" ]; then
      local val="${line#*=}"
      val="${val%\"}"; val="${val#\"}"; val="${val%\'}"; val="${val#\'}"
      case "$val" in "~"*) val="$HOME/${val#\~/}" ;; esac
      printf '%s' "$val"; return
    fi
  fi
  if [ "$(uname)" = "Darwin" ]; then
    printf '%s' "$HOME/Library/Application Support/Nuomi"
  else
    printf '%s' "$HOME/.nuomi"
  fi
}

human_size() {
  # du -sh 在 macOS/Linux 都可用；失败时退回字节数
  du -sh "$1" 2>/dev/null | awk '{print $1}'
}

do_backup() {
  local home="$1"
  command -v "$SQLITE_BIN" >/dev/null 2>&1 || die "找不到 sqlite3（${SQLITE_BIN}）。VACUUM INTO 是备份一致性的前提，不能退化成 cp。"
  [ -d "$home" ] || die "数据根不存在：${home}（解析自 NUOMI_HOME / .env / 默认值）。--home 可以显式指定。"

  local stage ts tar
  stage="$(mktemp -d)"
  ts="$(date +%Y%m%d-%H%M%S)"
  tar="$BACKUP_DIR/nuomi-backup-$ts.tar.gz"
  # 清理临时目录：trap 在函数返回**之后**才触发，那时 local stage 已经不在作用域里，
  # `set -u` 下引用 "$stage" 会变成 unbound variable 并把整个脚本的退出码打成 1
  # ——备份其实成功了却报失败。所以必须 ${stage:-}。
  STAGE_DIR="$stage"
  trap 'rm -rf "${STAGE_DIR:-}"' EXIT
  mkdir -p "$stage/data" "$BACKUP_DIR"

  # 1) 非数据库文件：rsync 原样搬（排除库文件本身、WAL 边车、可再生内容）
  # 排除清单里的边车**两种后缀都要写**：memory.sqlite 家族是 `-wal/-shm`，
  # 但 nuomi.db 的是 `nuomi.db-wal` / `nuomi.db-shm`（第一版只挡了 sqlite 那套，
  # 结果真跑出来的归档里躺着 nuomi.db-wal/-shm —— 恢复时会盖在 VACUUM 出来的
  # 单文件快照旁边，是脏的）。
  local -a rsync_ex=(--exclude "*/nuomi.db" --exclude "*.sqlite" --exclude "*.db"
                     --exclude "*.sqlite-wal" --exclude "*.sqlite-shm" --exclude "*.sqlite-journal"
                     --exclude "*.db-wal" --exclude "*.db-shm" --exclude "*.db-journal"
                     --exclude "logs" --exclude "tmp" --exclude ".DS_Store")
  [ "$WITH_MODELS" -eq 1 ] || rsync_ex+=(--exclude "models")
  # shellcheck disable=SC2086
  rsync -a "${rsync_ex[@]}" "$home/" "$stage/data/"

  # 2) 数据库文件：VACUUM INTO 快照（相对路径保持原样，恢复时放回原位）
  local db_count=0 manifest="$stage/manifest.tsv"
  : > "$manifest"
  printf 'kind\tpath\tbytes\tnote\n' >> "$manifest"
  while IFS= read -r -d '' src; do
    local rel dst rows
    rel="${src#"$home"/}"
    dst="$stage/data/$rel"
    mkdir -p "$(dirname "$dst")"
    rm -f "$dst"
    # `PRAGMA busy_timeout=...` 会回一行数字（第一次真跑就刷屏 "5000"），
    # stdout 丢掉、stderr 留着给 die 判断
    "$SQLITE_BIN" "$src" "PRAGMA busy_timeout=5000; VACUUM INTO '$dst';" >/dev/null \
      || die "VACUUM INTO 失败：${rel}（库可能被独占，稍后重试）"
    local chk
    chk="$("$SQLITE_BIN" "$dst" "PRAGMA integrity_check;" | head -1)"
    [ "$chk" = "ok" ] || die "备份快照完整性检查未通过：$rel → $chk"
    rows="$("$SQLITE_BIN" "$dst" "SELECT count(*) FROM sqlite_master WHERE type='table';" | head -1)"
    printf 'db\t%s\t%s\tintegrity=ok tables=%s\n' "$rel" "$(wc -c <"$dst" | tr -d ' ')" "$rows" >> "$manifest"
    db_count=$((db_count + 1))
  done < <(find "$home" -type f \( -name "*.db" -o -name "*.sqlite" \) \
             ! -path "*/models/*" ! -path "*/tmp/*" -print0 | sort -z)

  # 3) 清单补一份非库文件清单（恢复时不用它，但人要看懂备份里有什么）
  ( cd "$stage/data" && find . -type f ! -name "*.db" ! -name "*.sqlite" | sed 's|^\./||' | sort ) \
    > "$stage/files.txt"
  local n_files
  n_files="$(wc -l <"$stage/files.txt" | tr -d ' ')"
  printf 'files\t-\t%s\t-\n' "$n_files" >> "$manifest"
  printf 'home\t-\t%s\texcluded=%s\n' "$(human_size "$home")" \
    "$([ "$WITH_MODELS" -eq 1 ] && echo '无' || echo 'models/ logs/ tmp/ WAL 边车')" >> "$manifest"

  # 4) 打包（tar 里放的是 stage/data + 两份清单）
  tar -czf "$tar" -C "$stage" data manifest.tsv files.txt

  # 5) 保留策略：只留最近 KEEP 份（按文件名时间戳排序，不猜 mtime）
  #    注意：BSD/GNU 的 `head -n -K` 行为不一致（macOS 上会当成非法参数），
  #    所以这里数出总数再取前 N 个删，不依赖负数偏移。
  local all total
  all="$(cd "$BACKUP_DIR" && ls -1 2>/dev/null | grep '^nuomi-backup-.*\.tar\.gz$' | sort || true)"
  total="$(printf '%s\n' "$all" | grep -c . || true)"
  if [ "${total:-0}" -gt "$KEEP" ]; then
    printf '%s\n' "$all" | head -n "$((total - KEEP))" | while IFS= read -r f; do
      [ -n "$f" ] && rm -f "$BACKUP_DIR/$f" && echo "  已按保留策略删除旧备份：$f"
    done
  fi

  echo "✔ 备份完成：$tar"
  echo "  体积 $(human_size "$tar")｜数据库快照 $db_count 个（全部 integrity_check=ok）｜其它文件 $n_files 个"
  echo "  内容清单：tar -xzf '$tar' -O manifest.tsv"
  echo "  恢复命令：scripts/backup_nuomi.sh restore '$tar' --yes"
}

backend_running() {
  # 有两种形态的后端：uvicorn（make web/start）与壳自带的；按监听端口判最稳
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1 && return 0
  fi
  if command -v curl >/dev/null 2>&1; then
    curl -fsS --max-time 1 http://127.0.0.1:8000/api/health >/dev/null 2>&1 && return 0
  fi
  return 1
}

do_restore() {
  local archive="$1"
  [ -f "$archive" ] || die "备份文件不存在：$archive"
  [ "$ASSUME_YES" -eq 1 ] || die "恢复会覆盖数据根。确认无误后加 --yes 再执行。"
  local home
  home="$(resolve_home)"

  if [ "$FORCE" -ne 1 ] && backend_running; then
    die "后端还在 :8000 跑着。先 `make stop`（正在写的 sqlite 被覆盖会静默丢数据）。确实要强行恢复加 --force。"
  fi

  local stage
  stage="$(mktemp -d)"
  STAGE_DIR="$stage"
  trap 'rm -rf "${STAGE_DIR:-}"' EXIT
  tar -xzf "$archive" -C "$stage"
  [ -d "$stage/data" ] || die "备份结构不对（缺 data/）：$archive"

  # 1) 先验货再动手：每个库都 integrity_check，坏一个都不恢复
  command -v "$SQLITE_BIN" >/dev/null 2>&1 || die "找不到 sqlite3，无法校验备份内容。"
  local db_count=0
  while IFS= read -r -d '' dst; do
    local chk
    chk="$("$SQLITE_BIN" "$dst" "PRAGMA integrity_check;" | head -1)"
    [ "$chk" = "ok" ] || die "备份里的库校验失败：${dst#"$stage"/data/} → ${chk}（这个备份不可用）"
    db_count=$((db_count + 1))
  done < <(find "$stage/data" -type f \( -name "*.db" -o -name "*.sqlite" \) -print0 | sort -z)

  # 2) 恢复前把当前数据根也备份一份（restore 自己也要能回滚）
  if [ -d "$home" ] && [ -n "$(ls -A "$home" 2>/dev/null)" ]; then
    echo "· 先把当前数据根备份一份再动手…"
    do_backup "$home" | sed 's/^/  /'
  fi
  mkdir -p "$home"

  # 3) 覆盖式合并（默认不删目标里多出来的文件；--delete-extras 才做精确还原）
  if [ "$DELETE_EXTRAS" -eq 1 ]; then
    rsync -a --delete "$stage/data/" "$home/"
  else
    rsync -a "$stage/data/" "$home/"
  fi

  # 4) 密钥文件权限收回去（tar 保留权限，但跨机器/手工解压时未必）
  for f in providers.json env.json langfuse.json; do
    [ -f "$home/$f" ] && chmod 600 "$home/$f"
  done

  echo "✔ 已恢复到 ${home}（数据库快照 $db_count 个，全部 integrity_check=ok）"
  echo "  下一步：make start 后确认专家数量、知识库索引（索引任务在启动时 resume）、记忆是否正常。"
  [ "$DELETE_EXTRAS" -eq 1 ] || echo "  注意：默认只做覆盖式合并——备份之后新增的文件仍然留在原地（要精确还原加 --delete-extras）。"
}

do_list() {
  [ -d "$BACKUP_DIR" ] || { echo "（还没有备份：${BACKUP_DIR}）"; return; }
  ls -1 "$BACKUP_DIR" 2>/dev/null | grep '^nuomi-backup-.*\.tar\.gz$' | sort -r | while IFS= read -r f; do
    printf '%s\t%s\n' "$(human_size "$BACKUP_DIR/$f")" "$BACKUP_DIR/$f"
  done
}

# ---- 参数解析 ----
[ $# -ge 1 ] || { usage; exit 1; }
CMD="$1"; shift
while [ $# -gt 0 ]; do
  case "$1" in
    --home) TARGET_HOME="$2"; shift 2 ;;
    --dest) BACKUP_DIR="$2"; shift 2 ;;
    --keep) KEEP="$2"; shift 2 ;;
    --with-models) WITH_MODELS=1; shift ;;
    --force) FORCE=1; shift ;;
    --yes|--no-confirm) ASSUME_YES=1; shift ;;
    --delete-extras) DELETE_EXTRAS=1; shift ;;
    -h|--help) usage; exit 0 ;;
    -*) die "未知选项：$1（--help 看用法）" ;;
    *) POSITIONAL="$1"; shift ;;
  esac
done

case "$CMD" in
  backup) do_backup "$(resolve_home)" ;;
  restore) [ -n "${POSITIONAL:-}" ] || die "restore 需要备份文件路径：$0 restore <tar> --yes"; do_restore "$POSITIONAL" ;;
  list) do_list ;;
  *) usage; die "未知命令：$CMD" ;;
esac
