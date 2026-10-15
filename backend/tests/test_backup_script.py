"""数据根备份/恢复脚本（scripts/backup_nuomi.sh）的行为锁定。

为什么值得测：备份是"没出事时永远不被检查、出事时唯一有用"的东西。
只测三件真会死人的人肉看不出来的事：
 1) **WAL 里未合并的写入必须进备份**——记忆库是 WAL 模式，直接 cp 主文件
    会丢 -wal 里最后一截（真实数据根里 -wal 3.4MB 比主文件 820KB 还大）。
    做法：测试进程持有一个不关闭的 WAL 连接写数据（-wal 留在盘上没合并），
    跑备份，再从快照里读——读得到才证明走的是 VACUUM INTO 而不是 cp。
 2) 恢复要真能还原：persona MD、密钥 json、多个库（主库 + 每个专家的 memory.sqlite）都在。
 3) 可再生的大块头（models/）默认不进备份。
"""

import sqlite3
import subprocess
import tarfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "backup_nuomi.sh"
SQLITE_BIN = Path("/usr/bin/sqlite3")


@pytest.fixture()
def fake_home(tmp_path: Path):
    """搭一个数据根：主库 + 一个专家的 WAL 记忆库 + 人格 MD + 密钥 + models（应被排除）。"""
    home = tmp_path / "Nuomi"
    (home / "agent-workspaces" / "a1").mkdir(parents=True)
    (home / "models").mkdir()
    (home / "logs").mkdir()

    # 主库：普通模式
    db = home / "nuomi.db"
    con = sqlite3.connect(db)
    con.execute("PRAGMA journal_mode=WAL;")
    con.executescript(
        "CREATE TABLE agents (agent_id TEXT PRIMARY KEY, name TEXT, last_state TEXT);"
        "CREATE TABLE messages (thread_id TEXT, role TEXT, content TEXT);"
        "INSERT INTO agents VALUES ('a1','糯米','running');"
        "INSERT INTO messages VALUES ('t1','user','记得买猫粮');"
    )
    con.commit()
    con.close()

    # 记忆库：WAL，并且**不关连接**——-wal 里留着没合并的帧，正是 cp 会丢的那部分
    mem = home / "agent-workspaces" / "a1" / "memory.sqlite"
    wal_con = sqlite3.connect(mem)
    wal_con.execute("PRAGMA journal_mode=WAL;")
    wal_con.execute("CREATE TABLE facts (k TEXT PRIMARY KEY, v TEXT);")
    wal_con.execute("INSERT INTO facts VALUES ('cat','主人喜欢布偶猫');")
    wal_con.commit()

    # 主库也用 WAL（真实 nuomi.db 就是 WAL）：写完不关闭 → 数据留在 -wal 里，
    # 正是"直接 cp 主文件会丢"的那一截
    (home / "agents" / "a1").mkdir(parents=True)
    (home / "agents" / "a1" / "SOUL.md").write_text("你是糯米。\n", encoding="utf-8")
    (home / "providers.json").write_text('{"deepseek":"sk-secret"}', encoding="utf-8")
    (home / "connectors.json").write_text('{"mes":{}}', encoding="utf-8")
    (home / "models" / "bge.onnx").write_bytes(b"\x00" * 4096)
    (home / "logs" / "app.log").write_text("噪声\n", encoding="utf-8")

    yield home, wal_con
    wal_con.close()


def run_script(args, home, dest):
    env = {**__import__("os").environ, "NUOMI_HOME": str(home), "NUOMI_BACKUP_DIR": str(dest)}
    return subprocess.run(
        [str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=120
    )


@pytest.fixture(autouse=True)
def _need_tools():
    if not SCRIPT.exists():
        pytest.skip("备份脚本不在仓库里")
    if not SQLITE_BIN.exists():
        pytest.skip("没有 /usr/bin/sqlite3")
    if not (
        Path("/usr/bin/rsync").exists()
        or subprocess.run(["which", "rsync"], capture_output=True).returncode == 0
    ):
        pytest.skip("没有 rsync")


def test_backup_captures_unmerged_wal_rows(fake_home, tmp_path):
    home, _ = fake_home
    dest = tmp_path / "backups"
    res = run_script(["backup"], home, dest)
    assert res.returncode == 0, res.stdout + res.stderr

    archives = sorted(dest.glob("nuomi-backup-*.tar.gz"))
    assert len(archives) == 1, res.stdout

    # 把归档里的记忆库快照单独读出来：WAL 里那行必须已经在
    with tarfile.open(archives[0]) as tar:
        names = tar.getnames()
        # filter="tar"：3.12 起默认会过滤归档里的元数据，显式写出来免得 3.14 换默认值时测试变脸
        tar.extractall(tmp_path / "out", filter="tar")
    snap = tmp_path / "out" / "data" / "agent-workspaces" / "a1" / "memory.sqlite"
    assert snap.exists()
    con = sqlite3.connect(snap)
    try:
        assert con.execute("SELECT v FROM facts WHERE k='cat'").fetchone() == ("主人喜欢布偶猫",)
        # nuomi.db 的 WAL 数据同样必须在（脚本扫的是所有 *.db/*.sqlite，不是只认 memory.sqlite）
        main_snap = tmp_path / "out" / "data" / "nuomi.db"
        mcon = sqlite3.connect(main_snap)
        try:
            assert mcon.execute("SELECT name FROM agents").fetchone() == ("糯米",)
        finally:
            mcon.close()
        # 快照是 VACUUM INTO 出来的单文件：不该带 WAL 边车
        assert not (snap.parent / "memory.sqlite-wal").exists()
    finally:
        con.close()

    # 主库和人格 MD、密钥都在；可再生的 models/ 与 logs/ 不在
    assert "data/nuomi.db" in names
    assert "data/agents/a1/SOUL.md" in names
    assert "data/providers.json" in names
    assert not any(n.startswith("data/models/") for n in names), names
    assert not any(n.startswith("data/logs/") for n in names), names

    # 清单里逐库记了 integrity_check 的结果
    manifest = (tmp_path / "out" / "manifest.tsv").read_text(encoding="utf-8")
    assert "nuomi.db" in manifest and "memory.sqlite" in manifest
    assert "integrity=ok" in manifest


def test_restore_roundtrip_into_clean_dir(fake_home, tmp_path):
    home, wal_con = fake_home
    dest = tmp_path / "backups"
    assert run_script(["backup"], home, dest).returncode == 0
    wal_con.close()  # 备份后再关连接（真实场景 = 先 make stop 再 restore）

    target = tmp_path / "restored"
    target.mkdir()
    archive = next(iter(sorted(dest.glob("nuomi-backup-*.tar.gz"))))
    res = run_script(
        ["restore", str(archive), "--home", str(target), "--yes", "--force"], home, dest
    )
    assert res.returncode == 0, res.stdout + res.stderr

    con = sqlite3.connect(target / "nuomi.db")
    try:
        assert con.execute("SELECT name FROM agents").fetchone() == ("糯米",)
        assert con.execute("SELECT content FROM messages").fetchone() == ("记得买猫粮",)
    finally:
        con.close()
    assert (target / "agents" / "a1" / "SOUL.md").read_text(encoding="utf-8") == "你是糯米。\n"
    assert (target / "providers.json").read_text(encoding="utf-8") == '{"deepseek":"sk-secret"}'
    # 密钥文件权限收回 0600（跨机器解压也可能带进来 0644）
    assert (target / "providers.json").stat().st_mode & 0o777 == 0o600
    mem = target / "agent-workspaces" / "a1" / "memory.sqlite"
    con = sqlite3.connect(mem)
    try:
        assert con.execute("SELECT v FROM facts").fetchone() == ("主人喜欢布偶猫",)
    finally:
        con.close()


def test_restore_requires_yes_and_refuses_missing_archive(fake_home, tmp_path):
    home, wal_con = fake_home
    dest = tmp_path / "backups"
    # 没有 --yes → 必须拒绝（这条命令会覆盖数据根，不能顺手执行）
    assert run_script(["backup"], home, dest).returncode == 0
    wal_con.close()
    archive = next(iter(sorted(dest.glob("nuomi-backup-*.tar.gz"))))
    res = run_script(["restore", str(archive)], home, dest)
    assert res.returncode != 0 and "--yes" in (res.stdout + res.stderr)
    # 不存在的备份 → 明确报错而不是静默成功
    res = run_script(["restore", str(tmp_path / "nope.tar.gz"), "--yes"], home, dest)
    assert res.returncode != 0 and "不存在" in (res.stdout + res.stderr)


def test_backup_refuses_missing_home(tmp_path):
    res = run_script(
        ["backup", "--home", str(tmp_path / "ghost")], tmp_path / "ghost", tmp_path / "backups"
    )
    assert res.returncode != 0 and "数据根不存在" in (res.stdout + res.stderr)
