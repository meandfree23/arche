#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ARCHE 발행 감시기 (watchdog)

data/columns_db.json 을 검사해 다음 중 하나라도 어긋나면 exit 1 로 실패한다.
GitHub Actions 가 실패하면 저장소 소유자에게 메일 알림이 간다.

  1. START_DATE 부터 오늘(KST)까지 모든 날짜에 9개 카테고리 각 1편이 있는가
  2. id 중복이 없는가
  3. 필수 키 15개가 모두 있고 date_added 형식이 맞는가
  4. category 값이 정해진 9개 중 하나인가

옵션:
  --allow-today-missing   오늘 날짜 누락은 경고만 (발행 전 시간대 점검용)
"""

import argparse
import datetime
import json
import os
import re
import sys
from collections import Counter, defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "columns_db.json")

# 9개 카테고리 체계가 완성된 첫 날 (매거진 & 씬 신설일)
START_DATE = datetime.date(2026, 9, 21)

CATEGORIES = {
    "문학의 심연": "Literature",
    "시네마 & 대본의 시학": "Cinema",
    "철학적 전율": "Philosophy",
    "칼럼 & 문화비평": "Criticism",
    "신화 & 영원의 기억": "Myth",
    "시대의 잠언": "Manifesto",
    "시": "Poetry",
    "작가의 서신 & 비망록": "Epistolary",
    "매거진 & 씬": "Magazine",
}

REQUIRED_KEYS = [
    "id", "category", "category_en", "order", "title", "subtitle",
    "author_topic", "read_time", "lead", "content", "key_quote",
    "key_quote_source", "reflection_prompt", "zeitgeist_connection", "date_added",
]

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def gh_error(msg):
    print(f"::error::{msg}")


def gh_warning(msg):
    print(f"::warning::{msg}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-today-missing", action="store_true")
    args = parser.parse_args()

    kst = datetime.timezone(datetime.timedelta(hours=9))
    today = datetime.datetime.now(kst).date()

    with open(DB_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    errors = []

    # id 중복
    dup_ids = [i for i, n in Counter(a.get("id") for a in data).items() if n > 1]
    if dup_ids:
        errors.append(f"중복 id: {', '.join(map(str, dup_ids))}")

    # 스키마
    for a in data:
        missing = [k for k in REQUIRED_KEYS if k not in a]
        if missing:
            errors.append(f"{a.get('id')}: 필수 키 누락 {missing}")
        if a.get("category") not in CATEGORIES:
            errors.append(f"{a.get('id')}: 알 수 없는 category '{a.get('category')}'")
        if not DATE_RE.match(str(a.get("date_added", ""))):
            errors.append(f"{a.get('id')}: date_added 형식 오류 '{a.get('date_added')}'")

    # 날짜별 커버리지
    by_date = defaultdict(list)
    for a in data:
        by_date[a.get("date_added")].append(a.get("category"))

    missing_dates = []
    d = START_DATE
    while d <= today:
        key = d.isoformat()
        cats = Counter(by_date.get(key, []))
        lacking = [c for c in CATEGORIES if cats.get(c, 0) < 1]
        if lacking:
            msg = f"{key}: {9 - len(lacking)}/9편, 누락 카테고리 {lacking}"
            if d == today and args.allow_today_missing:
                gh_warning("오늘 분량 아직 없음 → " + msg)
            else:
                missing_dates.append(key)
                errors.append(msg)
        d += datetime.timedelta(days=1)

    future = sorted(k for k in by_date if k and k > today.isoformat())
    if future:
        gh_warning(f"미래 날짜 글 존재: {future}")

    print(f"ARCHE 감시기 | 오늘(KST) {today} | 총 {len(data)}편 | 점검 범위 {START_DATE}~{today}")
    if errors:
        for e in errors:
            gh_error(e)
        if missing_dates:
            gh_error(f"누락 날짜 {len(missing_dates)}일: {', '.join(missing_dates)}")
        sys.exit(1)
    print("이상 없음: 모든 날짜에 9개 카테고리 각 1편")


if __name__ == "__main__":
    main()
