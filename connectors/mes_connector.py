#!/usr/bin/env python3
# ruff: noqa: DTZ011
"""只读 MES 连接器（MCP server，stdio 传输）。

供糯米「连接器」挂载，对模拟 MES 数据库（connectors/data/mes.db）提供只读查询工具：
日产量、良率趋势、报警、设备状态、工单、OEE。

设计原则：
- 所有工具只做 SELECT；数据库以 SQLite 只读模式（mode=ro）打开，双保险写不进去；
- 指标口径贴近行业：良率 = 良品/(良品+不良)；
  OEE = 可用率(计划工时-停机维护/计划工时) × 性能(实际产量/按标准节拍的理论产量) × 良率；
- 接真实工厂系统：把环境变量 MES_DB_PATH 指向真实数据库只读账号即可，本文件不动。

用法（stdin/stdout 由 MCP 客户端拉起）：
    MES_DB_PATH=/path/to/real.db python mes_connector.py
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("nuomi-mes-connector")

# 默认数据库：本文件同级的 data/mes.db（由 scripts/gen_mes_data.py 生成）
_DEFAULT_DB = Path(__file__).resolve().parent / "data" / "mes.db"
_PLANNED_MINUTES_PER_DAY = 16 * 60  # 白班+夜班，用于 OEE 可用率


def _connect() -> sqlite3.Connection:
    db_path = os.environ.get("MES_DB_PATH") or str(_DEFAULT_DB)
    # uri 只读模式：即使工具逻辑出错也无法写入模拟/真实工厂数据
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_dict(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(r) for r in rows]


@mcp.tool()
def get_daily_production(query_date: str = "", line: str = "") -> list[dict]:
    """查询某天的生产日报：按设备返回产量/良品/不良/良率/停机分钟/报警数。

    Args:
        query_date: 日期 YYYY-MM-DD，留空默认今天。
        line: 产线 A 或 B，留空返回全部产线。
    """
    target = query_date or date.today().isoformat()
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT e.id AS equipment_id, e.name, e.line,
                   COALESCE(SUM(r.qty_good), 0) AS qty_good,
                   COALESCE(SUM(r.qty_bad), 0) AS qty_bad,
                   COALESCE((SELECT SUM(ev.duration_min) FROM equipment_events ev
                             WHERE ev.equipment_id = e.id AND ev.event_type IN ('stopped','maintenance')
                               AND substr(ev.event_time,1,10) = ?), 0) AS downtime_min,
                   COALESCE((SELECT COUNT(*) FROM equipment_events ev
                             WHERE ev.equipment_id = e.id AND ev.event_type = 'alarm'
                               AND substr(ev.event_time,1,10) = ?), 0) AS alarm_count
            FROM equipment e
            LEFT JOIN work_reports r
              ON r.equipment_id = e.id AND r.report_date = ?
            WHERE (? = '' OR e.line = ?)
            GROUP BY e.id
            ORDER BY e.id
            """,
            (target, target, target, line, line),
        ).fetchall()
        out = _row_to_dict(rows)
        for r in out:
            total = r["qty_good"] + r["qty_bad"]
            r["yield"] = round(r["qty_good"] / total, 4) if total else None
        return out
    finally:
        conn.close()


@mcp.tool()
def get_yield_trend(date_from: str = "", date_to: str = "", line: str = "") -> list[dict]:
    """查询良率趋势：按天返回良品/不良/良率，默认最近 7 天。

    Args:
        date_from: 起始日期 YYYY-MM-DD，留空默认今天往前 6 天。
        date_to: 结束日期 YYYY-MM-DD，留空默认今天。
        line: 产线 A 或 B，留空返回全部。
    """
    end = date_to or date.today().isoformat()
    start = date_from or (date.fromisoformat(end) - timedelta(days=6)).isoformat()
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT r.report_date, e.line,
                   SUM(r.qty_good) AS qty_good, SUM(r.qty_bad) AS qty_bad
            FROM work_reports r JOIN equipment e ON e.id = r.equipment_id
            WHERE r.report_date BETWEEN ? AND ?
              AND (? = '' OR e.line = ?)
            GROUP BY r.report_date, e.line
            ORDER BY r.report_date, e.line
            """,
            (start, end, line, line),
        ).fetchall()
        out = _row_to_dict(rows)
        for r in out:
            total = r["qty_good"] + r["qty_bad"]
            r["yield"] = round(r["qty_good"] / total, 4) if total else None
        return out
    finally:
        conn.close()


@mcp.tool()
def get_alarms(query_date: str = "", line: str = "") -> list[dict]:
    """查询报警记录：时间/设备/报警代码/内容，按时间倒序，默认今天。

    Args:
        query_date: 日期 YYYY-MM-DD，留空默认今天。
        line: 产线 A 或 B，留空返回全部。
    """
    target = query_date or date.today().isoformat()
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT ev.event_time, ev.equipment_id, e.line, ev.alarm_code, ev.note
            FROM equipment_events ev JOIN equipment e ON e.id = ev.equipment_id
            WHERE ev.event_type = 'alarm' AND substr(ev.event_time,1,10) = ?
              AND (? = '' OR e.line = ?)
            ORDER BY ev.event_time DESC
            """,
            (target, line, line),
        ).fetchall()
        return _row_to_dict(rows)
    finally:
        conn.close()


@mcp.tool()
def get_equipment_status(query_date: str = "") -> list[dict]:
    """查询设备状态：某天各设备的运行/停机/维护分钟与报警数。

    Args:
        query_date: 日期 YYYY-MM-DD，留空默认今天。
    """
    target = query_date or date.today().isoformat()
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT e.id AS equipment_id, e.name, e.line, e.type, e.status,
                   COALESCE(SUM(CASE WHEN ev.event_type = 'running' THEN ev.duration_min END), 0) AS run_min,
                   COALESCE(SUM(CASE WHEN ev.event_type IN ('stopped','maintenance') THEN ev.duration_min END), 0) AS idle_min,
                   COALESCE(SUM(CASE WHEN ev.event_type = 'alarm' THEN 1 ELSE 0 END), 0) AS alarm_count
            FROM equipment e
            LEFT JOIN equipment_events ev
              ON ev.equipment_id = e.id AND substr(ev.event_time,1,10) = ?
            GROUP BY e.id
            ORDER BY e.id
            """,
            (target,),
        ).fetchall()
        return _row_to_dict(rows)
    finally:
        conn.close()


@mcp.tool()
def get_work_orders(status: str = "", line: str = "", limit: int = 20) -> list[dict]:
    """查询工单列表。

    Args:
        status: done / running / open，留空返回全部状态。
        line: 产线 A 或 B，留空返回全部。
        limit: 返回条数上限，默认 20。
    """
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT id, product_code, product_name, line, qty_planned,
                   planned_start, planned_end, status
            FROM work_orders
            WHERE (? = '' OR status = ?) AND (? = '' OR line = ?)
            ORDER BY planned_start DESC
            LIMIT ?
            """,
            (status, status, line, line, limit),
        ).fetchall()
        return _row_to_dict(rows)
    finally:
        conn.close()


@mcp.tool()
def get_oee_summary(query_date: str = "") -> list[dict]:
    """查询 OEE 汇总：按设备返回可用率/性能率/良率/OEE（口径见说明）。

    OEE = 可用率 × 性能率 × 良率：
      - 可用率 = (计划16h - 停机与维护分钟) / 计划16h
      - 性能率 = 实际产量 / (按标准节拍 16h 的理论产量)
      - 良率   = 良品 / 实际产量

    Args:
        query_date: 日期 YYYY-MM-DD，留空默认今天。
    """
    target = query_date or date.today().isoformat()
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT e.id AS equipment_id, e.name, e.line, e.standard_cycle_min AS cycle_min,
                   COALESCE(SUM(r.qty_good), 0) AS qty_good,
                   COALESCE(SUM(r.qty_bad), 0) AS qty_bad,
                   COALESCE((SELECT SUM(ev.duration_min) FROM equipment_events ev
                             WHERE ev.equipment_id = e.id AND ev.event_type IN ('stopped','maintenance')
                               AND substr(ev.event_time,1,10) = ?), 0) AS downtime_min
            FROM equipment e
            LEFT JOIN work_reports r
              ON r.equipment_id = e.id AND r.report_date = ?
            GROUP BY e.id
            ORDER BY e.id
            """,
            (target, target),
        ).fetchall()
        out = []
        for r in _row_to_dict(rows):
            plan_min = _PLANNED_MINUTES_PER_DAY
            availability = max(0.0, (plan_min - r["downtime_min"]) / plan_min)
            total = r["qty_good"] + r["qty_bad"]
            theoretical = plan_min / r["cycle_min"]
            performance = total / theoretical if theoretical else 0.0
            quality = r["qty_good"] / total if total else 0.0
            out.append(
                {
                    "equipment_id": r["equipment_id"],
                    "name": r["name"],
                    "line": r["line"],
                    "availability": round(availability, 3),
                    "performance": round(performance, 3),
                    "quality": round(quality, 3),
                    "oee": round(availability * performance * quality, 3),
                }
            )
        return out
    finally:
        conn.close()


if __name__ == "__main__":
    mcp.run(transport="stdio")
