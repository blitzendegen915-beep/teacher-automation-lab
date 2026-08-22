"""安全調査CSVの読み込みと、名簿との突き合わせ。

Googleフォームのエクスポートは設問文がそのまま列見出しになるため
（例:「アレルギーについて具体的に記入してください（無ければ「なし」）」）、
列見出しの完全一致ではなく部分一致（サブストリングマッチ）でフィールドを
特定する。列の並び順や余分な列（メールアドレス等）があっても壊れない。
"""
from __future__ import annotations

import csv
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "rugby"

DEFAULT_SURVEY_PATH = DATA_DIR / "survey-sample.csv"
DEFAULT_ROSTER_PATH = DATA_DIR / "roster-2026.csv"

# ---------------------------------------------------------------------------
# 列見出しの部分一致マッピング
# ---------------------------------------------------------------------------

# (フィールド名, 見出しに含まれるべき部分文字列) の優先順リスト。
# 上から順に検査し、まだ埋まっていないフィールドのうち最初に一致したものへ
# その列を割り当てる。「緊急連絡先①（電話番号）」のように①②③の行に
# 「番号」という文字列が含まれてしまうため、①②③の判定を「番号」より
# 先に行う必要がある点に注意。
FIELD_PATTERNS = [
    ("timestamp", "タイムスタンプ"),
    ("timestamp", "Timestamp"),
    ("timestamp", "timestamp"),
    ("contact3", "緊急連絡先③"),
    ("contact2", "緊急連絡先②"),
    ("contact1", "緊急連絡先①"),
    ("allergy", "アレルギー"),
    ("medical", "病歴"),
    ("medical", "既往"),
    ("number", "番号"),
    ("grade", "学年"),
    ("klass", "組"),
    ("name", "氏名"),
]

REQUIRED_FIELDS = ["name"]

FIELD_LABEL_JA = {
    "timestamp": "タイムスタンプ",
    "grade": "学年",
    "klass": "組",
    "number": "番号",
    "name": "氏名",
    "allergy": "アレルギー調査",
    "medical": "病歴・傷歴",
    "contact1": "緊急連絡先①",
    "contact2": "緊急連絡先②",
    "contact3": "緊急連絡先③",
}

# 「アレルギーなし」「既往症なし」相当として扱う値。緊急時対応シートの
# 太字・網掛けフラグやアレルギー一覧への掲載対象外とする。
EMPTY_LIKE = {"", "なし", "特になし", "無し", "無", "-", "ー", "n/a"}


def is_meaningful(value: Optional[str]) -> bool:
    """アレルギー・病歴の欄が「実質的に記入あり」かどうかを判定する。"""
    v = (value or "").strip()
    return v.lower() not in EMPTY_LIKE


def map_headers(fieldnames: list) -> dict:
    """CSVの列見出しリストから {フィールド名: 実際の列見出し} を作る。

    一致する列が見つからなかったフィールドはキーに含まれない
    （呼び出し側で欠落チェックする）。
    """
    mapping: dict = {}
    for header in fieldnames:
        for field_name, pattern in FIELD_PATTERNS:
            if field_name in mapping:
                continue
            if pattern in header:
                mapping[field_name] = header
                break
    return mapping


def _normalize_name(name: str) -> str:
    """全角/半角スペースの違いなどを吸収して氏名を比較できる形にする。"""
    n = unicodedata.normalize("NFKC", name or "")
    n = " ".join(n.split())
    return n.strip()


TIMESTAMP_FORMATS = [
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d",
    "%Y-%m-%d",
]


def parse_timestamp(value: str) -> Optional[datetime]:
    v = (value or "").strip()
    if not v:
        return None
    for fmt in TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# データクラス
# ---------------------------------------------------------------------------


@dataclass
class Response:
    grade: str
    klass: str
    number: str
    name: str
    allergy: str
    medical: str
    contact1: str
    contact2: str
    contact3: str
    timestamp_raw: str
    row_index: int = 0

    @property
    def normalized_name(self) -> str:
        return _normalize_name(self.name)

    @property
    def has_allergy(self) -> bool:
        return is_meaningful(self.allergy)

    @property
    def has_medical(self) -> bool:
        return is_meaningful(self.medical)

    @property
    def is_flagged(self) -> bool:
        return self.has_allergy or self.has_medical

    @property
    def sort_number(self):
        n = (self.number or "").strip()
        return (0, int(n)) if n.isdigit() else (1, n)


@dataclass
class DuplicateInfo:
    name: str
    count: int


@dataclass
class SurveyResult:
    responses: list
    dropped_count: int
    duplicates: list  # list[DuplicateInfo]
    missing_fields: list  # フィールドが1列も見つからなかったもの
    header_map: dict
    total_rows: int


@dataclass
class RosterStudent:
    grade: str
    klass: str
    name: str
    role: str
    attends: str

    @property
    def normalized_name(self) -> str:
        return _normalize_name(self.name)


# ---------------------------------------------------------------------------
# 読み込み
# ---------------------------------------------------------------------------


def load_survey(path=None) -> SurveyResult:
    path = Path(path) if path else DEFAULT_SURVEY_PATH
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        raw_rows = list(reader)

    field_map = map_headers(fieldnames)

    missing_fields = [
        FIELD_LABEL_JA[key] for key in FIELD_LABEL_JA if key not in field_map
    ]
    for req in REQUIRED_FIELDS:
        if req not in field_map:
            raise ValueError(
                f"安全調査CSVに「{FIELD_LABEL_JA[req]}」に該当する列が見つかりません。"
                f"列見出し: {fieldnames}"
            )

    # タイムスタンプ列が見つからない場合は、Googleフォーム標準のエクスポート
    # 順序（先頭列がタイムスタンプ）を想定してフォールバックする。
    timestamp_header = field_map.get("timestamp")
    if timestamp_header is None and fieldnames:
        timestamp_header = fieldnames[0]

    def get(row, key):
        header = field_map.get(key)
        if header is None:
            return ""
        return (row.get(header) or "").strip()

    all_responses = []
    for i, row in enumerate(raw_rows):
        ts_raw = (row.get(timestamp_header) or "").strip() if timestamp_header else ""
        all_responses.append(
            Response(
                grade=get(row, "grade"),
                klass=get(row, "klass"),
                number=get(row, "number"),
                name=get(row, "name"),
                allergy=get(row, "allergy"),
                medical=get(row, "medical"),
                contact1=get(row, "contact1"),
                contact2=get(row, "contact2"),
                contact3=get(row, "contact3"),
                timestamp_raw=ts_raw,
                row_index=i,
            )
        )

    # -- 同姓同名の重複は最新タイムスタンプのものだけを残す --------------------

    by_name: dict = {}
    for r in all_responses:
        by_name.setdefault(r.normalized_name, []).append(r)

    def sort_key(r: Response):
        ts = parse_timestamp(r.timestamp_raw)
        # タイムスタンプを解析できない行は最も古い扱いにしつつ、
        # 同点の場合はCSV内の出現順（row_index）で決着させる。
        return (ts or datetime.min, r.row_index)

    resolved = []
    duplicates = []
    dropped_count = 0
    for name, group in by_name.items():
        if len(group) > 1:
            duplicates.append(DuplicateInfo(name=group[0].name.strip(), count=len(group)))
            dropped_count += len(group) - 1
        latest = max(group, key=sort_key)
        resolved.append(latest)

    resolved.sort(key=lambda r: r.row_index)

    return SurveyResult(
        responses=resolved,
        dropped_count=dropped_count,
        duplicates=duplicates,
        missing_fields=missing_fields,
        header_map=field_map,
        total_rows=len(raw_rows),
    )


def load_roster(path=None) -> list:
    path = Path(path) if path else DEFAULT_ROSTER_PATH
    students = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            students.append(
                RosterStudent(
                    grade=(row.get("grade") or "").strip(),
                    klass=(row.get("class") or "").strip(),
                    name=(row.get("name") or "").strip(),
                    role=(row.get("role") or "").strip(),
                    attends=(row.get("attends") or "").strip(),
                )
            )
    return students


def find_non_responders(roster: list, responses: list) -> list:
    """回答が見つからない名簿上の生徒を返す（名簿の並び順を保持）。"""
    responded = {r.normalized_name for r in responses}
    return [s for s in roster if s.normalized_name not in responded]


def group_by_grade(responses: list) -> dict:
    """学年ごとに {組, 番号} でソートした回答リストを返す。"""
    grades: dict = {}
    for r in responses:
        grades.setdefault(r.grade or "(学年不明)", []).append(r)
    for g in grades:
        grades[g].sort(key=lambda r: (r.klass or "", r.sort_number, r.name))
    return dict(sorted(grades.items(), key=lambda kv: kv[0]))


def group_roster_by_grade_class(students: list) -> dict:
    groups: dict = {}
    for s in students:
        groups.setdefault((s.grade or "(学年不明)", s.klass or "(組不明)"), []).append(s)
    for k in groups:
        groups[k].sort(key=lambda s: s.name)
    return dict(sorted(groups.items(), key=lambda kv: kv[0]))
