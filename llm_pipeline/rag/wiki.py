"""WikiStore — ETF 상품·세제·규제 지식 베이스 (SQLite)."""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS wiki_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL,
    key TEXT NOT NULL UNIQUE,
    data JSON NOT NULL,
    updated_at TEXT NOT NULL,
    source TEXT
);
CREATE INDEX IF NOT EXISTS idx_wiki_domain ON wiki_entries(domain);
"""


class WikiStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_table()

    def _ensure_table(self) -> None:
        con = sqlite3.connect(self.db_path)
        con.executescript(_DDL)
        con.close()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def upsert(self, domain: str, key: str, data: dict, source: str = "manual") -> None:
        con = self._connect()
        con.execute(
            """INSERT INTO wiki_entries (domain, key, data, updated_at, source)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET
                 data=excluded.data, updated_at=excluded.updated_at, source=excluded.source""",
            (domain, key, json.dumps(data, ensure_ascii=False),
             datetime.now().strftime("%Y-%m-%d %H:%M"), source),
        )
        con.commit()
        con.close()

    def upsert_products_from_api(self, products: list[dict]) -> int:
        con = self._connect()
        count = 0
        for p in products:
            con.execute(
                """INSERT INTO wiki_entries (domain, key, data, updated_at, source)
                   VALUES ('product', ?, ?, ?, 'naver_finance')
                   ON CONFLICT(key) DO UPDATE SET
                     data=excluded.data, updated_at=excluded.updated_at, source=excluded.source""",
                (p["code"], json.dumps(p, ensure_ascii=False),
                 datetime.now().strftime("%Y-%m-%d %H:%M")),
            )
            count += 1
        con.commit()
        con.close()
        logger.info("[Wiki] %d개 상품 upsert 완료", count)
        return count

    def search_products(self, keywords: list[str], top_k: int = 15) -> list[dict]:
        """키워드로 ETF 상품 검색 (상품명 + 테마 LIKE 매칭, 시총 순 정렬)."""
        con = self._connect()
        cleaned = [kw for kw in keywords if kw]
        if not cleaned:
            con.close()
            return []
        conds = []
        for kw in cleaned:
            conds.append(f"json_extract(data, '$.name') LIKE '%{kw}%'")
            conds.append(f"data LIKE '%\"themes\":%' AND data LIKE '%{kw}%'")
        conditions = " OR ".join(conds)
        rows = con.execute(
            f"""SELECT data FROM wiki_entries
                WHERE domain='product' AND ({conditions})
                ORDER BY CAST(json_extract(data, '$.market_cap') AS INTEGER) DESC
                LIMIT ?""",
            (top_k,),
        ).fetchall()
        con.close()
        return [json.loads(r["data"]) for r in rows]

    def search_products_by_theme(self, themes: list[str], top_k: int = 15) -> list[dict]:
        """테마명으로 ETF 검색 (themes 배열 LIKE 매칭, 시총순)."""
        con = self._connect()
        cleaned = [t for t in themes if t]
        if not cleaned:
            con.close()
            return []
        conds = " OR ".join(f"data LIKE '%\"{t}\"%'" for t in cleaned)
        rows = con.execute(
            f"""SELECT data FROM wiki_entries
                WHERE domain='product' AND ({conds})
                ORDER BY CAST(json_extract(data, '$.market_cap') AS INTEGER) DESC
                LIMIT ?""",
            (top_k,),
        ).fetchall()
        con.close()
        return [json.loads(r["data"]) for r in rows]

    def update_product_themes(self, theme_map: dict[str, list[str]]) -> int:
        """종목코드 → 테마 리스트 매핑을 product entries에 주입."""
        con = self._connect()
        count = 0
        for code, themes in theme_map.items():
            row = con.execute(
                "SELECT data FROM wiki_entries WHERE domain='product' AND key=?", (code,)
            ).fetchone()
            if not row:
                continue
            data = json.loads(row["data"])
            data["themes"] = themes
            con.execute(
                "UPDATE wiki_entries SET data=?, updated_at=? WHERE domain='product' AND key=?",
                (json.dumps(data, ensure_ascii=False),
                 datetime.now().strftime("%Y-%m-%d %H:%M"), code),
            )
            count += 1
        con.commit()
        con.close()
        logger.info("[Wiki] %d개 상품에 테마 정보 주입", count)
        return count

    def update_product_metadata(self, metadata_map: dict[str, dict]) -> int:
        """종목코드 → 메타데이터(themes/ter/replication/hedge_type/...) 일괄 주입."""
        con = self._connect()
        count = 0
        for code, meta in metadata_map.items():
            row = con.execute(
                "SELECT data FROM wiki_entries WHERE domain='product' AND key=?", (code,)
            ).fetchone()
            if not row:
                continue
            data = json.loads(row["data"])
            for k, v in meta.items():
                if v is not None:
                    data[k] = v
            con.execute(
                "UPDATE wiki_entries SET data=?, updated_at=? WHERE domain='product' AND key=?",
                (json.dumps(data, ensure_ascii=False),
                 datetime.now().strftime("%Y-%m-%d %H:%M"), code),
            )
            count += 1
        con.commit()
        con.close()
        logger.info("[Wiki] %d개 상품에 메타데이터 주입", count)
        return count

    def search_by_hedge_type(self, hedge_type: str, top_k: int = 15) -> list[dict]:
        """환헤지 타입('환헤지'|'환노출'|'합성')으로 검색."""
        con = self._connect()
        rows = con.execute(
            f"""SELECT data FROM wiki_entries
                WHERE domain='product'
                  AND json_extract(data, '$.hedge_type') = ?
                ORDER BY CAST(json_extract(data, '$.market_cap') AS INTEGER) DESC
                LIMIT ?""",
            (hedge_type, top_k),
        ).fetchall()
        con.close()
        return [json.loads(r["data"]) for r in rows]

    def get_top_by_market_cap(self, n: int = 20) -> list[dict]:
        con = self._connect()
        rows = con.execute(
            """SELECT data FROM wiki_entries
               WHERE domain='product'
               ORDER BY CAST(json_extract(data, '$.market_cap') AS INTEGER) DESC
               LIMIT ?""",
            (n,),
        ).fetchall()
        con.close()
        return [json.loads(r["data"]) for r in rows]

    def get_by_operator(self, operator: str, top_k: int = 10) -> list[dict]:
        con = self._connect()
        rows = con.execute(
            """SELECT data FROM wiki_entries
               WHERE domain='product'
                 AND json_extract(data, '$.operator') = ?
               ORDER BY CAST(json_extract(data, '$.market_cap') AS INTEGER) DESC
               LIMIT ?""",
            (operator, top_k),
        ).fetchall()
        con.close()
        return [json.loads(r["data"]) for r in rows]

    def search_tax_rules(self, keywords: list[str]) -> list[dict]:
        con = self._connect()
        conditions = " OR ".join(
            f"data LIKE '%{kw}%'" for kw in keywords if kw
        )
        if not conditions:
            con.close()
            return []
        rows = con.execute(
            f"""SELECT data FROM wiki_entries
                WHERE domain='tax_rule' AND ({conditions})""",
        ).fetchall()
        con.close()
        return [json.loads(r["data"]) for r in rows]

    def search_regulations(self, keywords: list[str]) -> list[dict]:
        con = self._connect()
        conditions = " OR ".join(
            f"data LIKE '%{kw}%'" for kw in keywords if kw
        )
        if not conditions:
            con.close()
            return []
        rows = con.execute(
            f"""SELECT data FROM wiki_entries
                WHERE domain='regulation' AND ({conditions})""",
        ).fetchall()
        con.close()
        return [json.loads(r["data"]) for r in rows]

    def get_all(self, domain: str) -> list[dict]:
        con = self._connect()
        rows = con.execute(
            "SELECT data FROM wiki_entries WHERE domain=?", (domain,)
        ).fetchall()
        con.close()
        return [json.loads(r["data"]) for r in rows]

    def count(self, domain: str) -> int:
        con = self._connect()
        row = con.execute(
            "SELECT COUNT(*) FROM wiki_entries WHERE domain=?", (domain,)
        ).fetchone()
        con.close()
        return row[0]

    # ── 포맷터 (LLM 프롬프트 주입용) ──────────────────────────────────────────

    @staticmethod
    def format_products(products: list[dict]) -> str:
        if not products:
            return ""
        lines = ["[관련 ETF 상품]"]
        for p in products:
            cap_str = f"시총 {p.get('market_cap', 0):,}억" if p.get("market_cap") else ""
            ret_str = f"3M수익률 {p.get('three_month_return', 0):+.1f}%" if p.get("three_month_return") else ""
            ter = p.get("ter")
            ter_str = f"TER {ter:.2f}%" if ter is not None else ""
            hedge = p.get("hedge_type")
            hedge_str = hedge if hedge and hedge != "환노출" else ""
            repl = p.get("replication")
            repl_str = repl if repl else ""
            themes = p.get("themes", [])
            theme_str = f"테마: {', '.join(themes[:5])}" if themes else ""
            parts = [
                f"- {p['name']} ({p['code']})",
                p.get('operator', '?'),
                cap_str, ret_str, ter_str, hedge_str, repl_str, theme_str,
            ]
            lines.append(" | ".join(x for x in parts if x))
        return "\n".join(lines)

    @staticmethod
    def format_tax_rules(rules: list[dict]) -> str:
        if not rules:
            return ""
        lines = ["[세제 정보]"]
        for r in rules:
            source = r.get("source", "")
            lines.append(f"- {r.get('rule_name', '')}: {r.get('description', '')} (출처: {source})")
        return "\n".join(lines)

    @staticmethod
    def format_regulations(regs: list[dict]) -> str:
        if not regs:
            return ""
        lines = ["[규제 정보]"]
        for r in regs:
            lines.append(f"- {r.get('name', '')}: {r.get('summary', '')} (출처: {r.get('source', '')})")
        return "\n".join(lines)
