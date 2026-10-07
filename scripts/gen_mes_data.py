#!/usr/bin/env python3
# ruff: noqa: DTZ011
"""生成模拟 MES 数据库（CNC 机加工场景）。

用于给糯米"只读 MES 连接器"提供一份可复现的假工厂数据，schema 仿真实 MES：
equipment（设备）/ work_orders（工单）/ work_reports（报工）/ quality_events（不良）
/ equipment_events（状态迁移 + 报警）。

设计要点：
- 固定 seed + 可传 --end-date，同一参数组合可完整复现同一份数据；
- 数据带真实业务痕迹：良率波动、刀具磨损导致的良率跳水、报警与停机事件；
- 指标口径贴近行业：良率 = 良品/(良品+不良)；OEE 由查询端按
  可用率×性能×良率计算（本脚本只保证报工数量与标准节拍自洽）。

用法：
    python scripts/gen_mes_data.py                       # 默认：近 90 天，写到 connectors/data/mes.db
    python scripts/gen_mes_data.py --db /tmp/mes.db --end-date 2026-10-06 --days 30 --seed 42
"""

from __future__ import annotations

import argparse
import random
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------- 设备/产品档案

# (id, name, line, type, manufacturer, standard_cycle_min)
EQUIPMENT = [
    ("A-01", "立式加工中心 VMC-850", "A", "CNC 加工中心", "通用机床", 2.0),
    ("A-02", "立式加工中心 VMC-850", "A", "CNC 加工中心", "通用机床", 2.0),
    ("A-03", "龙门加工中心 GM-2015", "A", "CNC 加工中心", "华中数控", 3.5),
    ("B-01", "数控车床 CK-6150", "B", "数控车床", "沈阳机床", 1.8),
    ("B-02", "数控车床 CK-6150", "B", "数控车床", "沈阳机床", 1.8),
]

# (product_code, product_name, line)
PRODUCTS = [
    ("FL-100", "法兰盘", "A"),
    ("EC-200", "电机端盖", "A"),
    ("GS-300", "齿轮轴", "B"),
    ("BR-400", "轴承座", "B"),
    ("CP-500", "连接板", "A"),
    ("VB-600", "阀体", "B"),
]

DEFECT_TYPES = ["尺寸超差", "表面粗糙度", "刀具磨损", "撞机", "毛刺未清"]

ALARM_DEFS = [
    ("AL-101", "主轴过载", 2),
    ("AL-204", "刀具寿命到", 1),
    ("AL-305", "冷却液温度高", 2),
    ("AL-402", "气压不足", 2),
    ("AL-510", "门联锁打开", 3),
    ("AL-607", "伺服报警", 1),
]

SHIFTS = [("白班", 8.0), ("夜班", 8.0)]


def build_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE equipment (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            line TEXT NOT NULL,
            type TEXT NOT NULL,
            manufacturer TEXT NOT NULL,
            standard_cycle_min REAL NOT NULL,
            install_date TEXT NOT NULL,
            status TEXT NOT NULL
        );
        CREATE TABLE work_orders (
            id TEXT PRIMARY KEY,
            product_code TEXT NOT NULL,
            product_name TEXT NOT NULL,
            line TEXT NOT NULL,
            qty_planned INTEGER NOT NULL,
            planned_start TEXT NOT NULL,
            planned_end TEXT NOT NULL,
            status TEXT NOT NULL
        );
        CREATE TABLE work_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            work_order_id TEXT NOT NULL,
            equipment_id TEXT NOT NULL,
            report_date TEXT NOT NULL,
            shift TEXT NOT NULL,
            qty_good INTEGER NOT NULL,
            qty_bad INTEGER NOT NULL,
            work_hours REAL NOT NULL
        );
        CREATE TABLE quality_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_date TEXT NOT NULL,
            equipment_id TEXT NOT NULL,
            work_order_id TEXT NOT NULL,
            defect_type TEXT NOT NULL,
            qty INTEGER NOT NULL
        );
        CREATE TABLE equipment_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_time TEXT NOT NULL,
            equipment_id TEXT NOT NULL,
            event_type TEXT NOT NULL,   -- running / stopped / maintenance / alarm
            duration_min INTEGER NOT NULL,
            alarm_code TEXT,
            note TEXT
        );
        CREATE INDEX idx_reports_date ON work_reports(report_date);
        CREATE INDEX idx_reports_equip ON work_reports(equipment_id);
        CREATE INDEX idx_events_equip ON equipment_events(equipment_id);
        CREATE INDEX idx_events_time ON equipment_events(event_time);
        CREATE INDEX idx_quality_date ON quality_events(report_date);
        """
    )


def gen(conn: sqlite3.Connection, days: int, end: date, rng: random.Random) -> dict:
    """生成数据，返回统计信息。"""
    stats = {"work_orders": 0, "reports": 0, "quality": 0, "events": 0}

    # ---- 设备档案 ----
    for eid, name, line, etype, mfr, cycle in EQUIPMENT:
        conn.execute(
            "INSERT INTO equipment VALUES (?,?,?,?,?,?,?,?)",
            (eid, name, line, etype, mfr, cycle, "2023-01-01", "running"),
        )

    # 异常注入计划（相对 end 的偏移天数）
    # A-01：end-14 ~ end-12 连续 3 天良率跳水（刀具磨损未及时更换）
    bad_tool_days = {end - timedelta(days=k) for k in (14, 13, 12)}
    # B-02：end-6 当天冷却液报警频繁 + 一次停机
    hot_alarm_day = end - timedelta(days=6)

    wo_seq = 0
    for day_offset in range(days):
        d = end - timedelta(days=days - 1 - day_offset)
        is_sunday = d.weekday() == 6  # 每周日停线检修

        for eid, name, line, etype, mfr, cycle in EQUIPMENT:
            # ---- 工单：每设备每天 1 个（周日无工单）----
            if is_sunday:
                continue
            wo_seq += 1
            wo_id = f"WO-{d.strftime('%Y%m%d')}-{wo_seq:04d}"
            product = rng.choice([p for p in PRODUCTS if p[2] == line])
            # 排产量按设备节拍约束（理论产能的 65%~90%），保证 OEE 性能率 < 1、贴近真实
            theoretical = int(16 * 60 / cycle)
            qty_planned = rng.randint(int(theoretical * 0.65), int(theoretical * 0.9))
            planned_hours = round(qty_planned * cycle / 60 * rng.uniform(0.9, 1.1), 1)
            start = datetime.combine(d, datetime.min.time().replace(hour=8))
            end_t = start + timedelta(hours=planned_hours)
            conn.execute(
                "INSERT INTO work_orders VALUES (?,?,?,?,?,?,?,?)",
                (
                    wo_id,
                    product[0],
                    product[1],
                    line,
                    qty_planned,
                    start.isoformat(sep=" "),
                    end_t.isoformat(sep=" "),
                    "done",
                ),
            )
            stats["work_orders"] += 1

            # ---- 报工：按班次拆（一般 1-2 班完成）----
            remaining = qty_planned
            shift_count = 1 if rng.random() < 0.5 else 2
            # 良率：正常 96.5%~99.5%；异常期 A-01 掉到 88%~92%
            if eid == "A-01" and d in bad_tool_days:
                yield_base = rng.uniform(0.88, 0.92)
            elif eid == "A-01" and d in {end - timedelta(days=11)}:  # 恢复期
                yield_base = rng.uniform(0.93, 0.95)
            else:
                yield_base = rng.uniform(0.965, 0.995)

            for si in range(shift_count):
                if remaining <= 0:
                    break
                qty_this = remaining if si == shift_count - 1 else remaining // (shift_count - si)
                bad = max(0, round(qty_this * (1 - yield_base) * rng.uniform(0.6, 1.4)))
                bad = min(bad, qty_this - 1)
                good = qty_this - bad
                shift_name, shift_len = SHIFTS[si % 2]
                conn.execute(
                    "INSERT INTO work_reports (work_order_id, equipment_id, report_date, shift, qty_good, qty_bad, work_hours) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (wo_id, eid, d.isoformat(), shift_name, good, bad, shift_len),
                )
                stats["reports"] += 1

                # ---- 不良明细 ----
                if bad > 0:
                    if eid == "A-01" and d in bad_tool_days:
                        defect = rng.choices(DEFECT_TYPES, weights=[15, 10, 60, 5, 10])[0]
                    else:
                        defect = rng.choices(DEFECT_TYPES, weights=[30, 25, 15, 5, 25])[0]
                    conn.execute(
                        "INSERT INTO quality_events (report_date, equipment_id, work_order_id, defect_type, qty) "
                        "VALUES (?,?,?,?,?)",
                        (d.isoformat(), eid, wo_id, defect, bad),
                    )
                    stats["quality"] += 1
                remaining -= qty_this

            # ---- 设备事件：运行 + 计划维护 + 随机故障 + 报警 ----
            events: list[tuple[str, str, str, int, str | None, str | None]] = []
            # 运行（白班 8h 默认）
            events.append((f"{d.isoformat()} 08:00:00", eid, "running", 480, None, "正常生产"))
            # 每周计划维护 30-90min
            if rng.random() < 0.25:
                events.append((f"{d.isoformat()} 12:00:00", eid, "maintenance", rng.randint(30, 90), None, "计划保养"))
            # 随机短停 / 故障
            if rng.random() < 0.18:
                events.append((f"{d.isoformat()} 14:00:00", eid, "stopped", rng.randint(30, 120), None, "临时停机"))
            # B-02 在 hot_alarm_day：冷却液高温反复报警 + 一次停机
            if eid == "B-02" and d == hot_alarm_day:
                for k in range(3):
                    alarm_t = datetime.combine(d, datetime.min.time().replace(hour=10, minute=30)) + timedelta(minutes=20 * k)
                    events.append(
                        (alarm_t.isoformat(sep=" "), eid, "alarm", 5, "AL-305", "冷却液温度高")
                    )
                events.append((f"{d.isoformat()} 11:00:00", eid, "stopped", rng.randint(30, 120), None, "冷却系统故障停机"))
            # 日常偶发报警
            if rng.random() < 0.10:
                code, desc, _ = rng.choices(ALARM_DEFS, weights=[a[2] for a in ALARM_DEFS])[0]
                events.append((f"{d.isoformat()} 15:00:00", eid, "alarm", 5, code, desc))

            for ev_time, ev_eid, etype, ev_dur, code, note in events:
                conn.execute(
                    "INSERT INTO equipment_events (event_time, equipment_id, event_type, duration_min, alarm_code, note) "
                    "VALUES (?,?,?,?,?,?)",
                    (ev_time, ev_eid, etype, ev_dur, code, note),
                )
                stats["events"] += 1

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="生成模拟 MES 数据库（CNC 机加工）")
    parser.add_argument("--db", default=str(Path(__file__).resolve().parents[1] / "connectors" / "data" / "mes.db"))
    parser.add_argument("--end-date", type=date.fromisoformat, default=None, help="数据结束日期，默认今天")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    end = args.end_date or date.today()
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()  # 幂等：覆盖旧数据

    rng = random.Random(args.seed)
    conn = sqlite3.connect(db_path)
    try:
        build_schema(conn)
        stats = gen(conn, args.days, end, rng)
        conn.commit()
    finally:
        conn.close()

    print(f"模拟 MES 数据库已生成：{db_path}")
    print(f"  日期范围：{end - timedelta(days=args.days - 1)} ~ {end}（{args.days} 天）")
    print(f"  工单 {stats['work_orders']} · 报工 {stats['reports']} · 不良记录 {stats['quality']} · 设备事件 {stats['events']}")
    print("  异常注入：A-01 刀具磨损良率跳水（近 14~12 天）；B-02 冷却液高温报警（近 6 天）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
