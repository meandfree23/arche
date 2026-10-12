#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ARCHE 발행 검문소 (publish guard)

손으로 1MB 넘는 JSON 을 고치지 않는다. 새 글은 초안 파일에 따로 쓰고,
이 스크립트가 검사한 뒤 원본 끝에 붙인다. 원본을 덮어쓰거나 기존 글을
건드리는 변경은 통과시키지 않는다.

사용법
  python3 scripts/publish_guard.py plan               # 오늘(KST) 써야 할 글, 다음 id, 피해야 할 작가
  python3 scripts/publish_guard.py add drafts.json    # 초안 검사 → 원본 끝에 원자적으로 추가
  python3 scripts/publish_guard.py check [--base REF] # 커밋 전 회귀 검사 (기본 REF=HEAD)
  python3 scripts/publish_guard.py audit              # 아카이브 전체 구조 점검 (감시기용)

종료 코드: 0 통과 / 1 실패(아무것도 쓰지 않음)
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_REL = "data/columns_db.json"
DB_PATH = os.path.join(BASE_DIR, DB_REL)

START_DATE = datetime.date(2026, 9, 21)  # 9개 카테고리 체계가 완성된 첫 날
KST = datetime.timezone(datetime.timedelta(hours=9))

# 발행 순서 = 배열에 붙는 순서 = 사이트의 '오늘의 ARCHE' 순서
CATEGORIES = [
    # (category, category_en, id prefix)
    ("문학의 심연", "Literature", "lit"),
    ("시네마 & 대본의 시학", "Cinema", "cin"),
    ("철학적 전율", "Philosophy", "phi"),
    ("칼럼 & 문화비평", "Criticism", "cri"),
    ("신화 & 영원의 기억", "Myth", "myt"),
    ("시대의 잠언", "Manifesto", "man"),
    ("시", "Poetry", "poe"),
    ("작가의 서신 & 비망록", "Epistolary", "epi"),
    ("매거진 & 씬", "Magazine", "mag"),
]
CAT_EN = {c: e for c, e, _ in CATEGORIES}
CAT_PREFIX = {c: p for c, _, p in CATEGORIES}
CAT_RANK = {c: i for i, (c, _, _) in enumerate(CATEGORIES)}

KEY_ORDER = [
    "id", "category", "category_en", "order", "title", "subtitle",
    "author_topic", "read_time", "lead", "content", "key_quote",
    "key_quote_source", "reflection_prompt", "zeitgeist_connection", "date_added",
]
TEXT_KEYS = [k for k in KEY_ORDER if k not in ("order",)]

# 최근 발행분(10월) 분포에서 정한 하한/상한. 하한 미달은 실패, 상한 초과는 경고.
LIMITS = {
    "title": (3, 80),
    "subtitle": (10, 140),
    "author_topic": (4, 140),
    "lead": (50, 260),
    "content": (700, 2600),
    "key_quote": (10, 600),
    "key_quote_source": (10, 320),
    "reflection_prompt": (20, 160),
    "zeitgeist_connection": (150, 600),
}
READ_TIME_RE = re.compile(r"^\d{1,2}분 읽기$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
WORK_RE = re.compile(r"[《『〈「]([^》』〉」]+)[》』〉」]")
FORBIDDEN_IN_TEXT = re.compile(r"(<script|<iframe|```|\{\{|TODO|TBD|lorem ipsum)", re.I)


# ───────────────────────── 공통 ─────────────────────────

def today_kst():
    return datetime.datetime.now(KST).date()


def load_json_text(text, label):
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        fail([f"{label}: JSON 파싱 실패 — {e}"])
    if not isinstance(data, list):
        fail([f"{label}: 최상위가 배열이 아님"])
    return data


def load_db():
    with open(DB_PATH, "r", encoding="utf-8") as f:
        return load_json_text(f.read(), DB_REL)


def load_base(ref):
    try:
        out = subprocess.run(
            ["git", "-C", BASE_DIR, "show", f"{ref}:{DB_REL}"],
            capture_output=True, check=True,
        ).stdout.decode("utf-8")
    except subprocess.CalledProcessError as e:
        fail([f"기준본({ref}) 을 git 에서 읽지 못함: {e.stderr.decode('utf-8', 'ignore').strip()}"])
    return load_json_text(out, f"{ref}:{DB_REL}")


def dump(data):
    # 기존 파일과 바이트 단위로 같은 형식(indent=2, ensure_ascii=False, 끝 줄바꿈 없음)
    return json.dumps(data, ensure_ascii=False, indent=2)


def write_atomic(data):
    text = dump(data)
    json.loads(text)  # 쓰기 직전 한 번 더 확인
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(DB_PATH), prefix=".columns_db.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, DB_PATH)


def fail(errors, warnings=()):
    for w in warnings:
        print(f"⚠️  {w}")
    for e in errors:
        print(f"❌ {e}")
    print(f"\n검문 실패: 오류 {len(errors)}건. 원본은 바뀌지 않았다.")
    sys.exit(1)


def person_names(author_topic):
    head = re.split(r"[,『《〈「(]", author_topic)[0]
    names = [n.strip() for n in re.split(r"[·/&]| 와 | 과 ", head) if n.strip()]
    return [n for n in names if len(n) >= 2]


def works(author_topic):
    return [w.strip() for w in WORK_RE.findall(author_topic)]


def coverage_gaps(data, until):
    """START_DATE~until 사이 날짜별로 비어 있는 카테고리."""
    have = defaultdict(set)
    for a in data:
        have[a.get("date_added")].add(a.get("category"))
    gaps = {}
    d = START_DATE
    while d <= until:
        lacking = [c for c, _, _ in CATEGORIES if c not in have.get(d.isoformat(), set())]
        if lacking:
            gaps[d.isoformat()] = lacking
        d += datetime.timedelta(days=1)
    return gaps


def next_numbers(data):
    nxt = {}
    for c, _, p in CATEGORIES:
        nums = [int(a["id"].split("-")[1]) for a in data
                if a.get("category") == c and re.fullmatch(rf"{p}-\d+", str(a.get("id", "")))]
        nxt[c] = (max(nums) if nums else 0) + 1
    return nxt


# ───────────────────────── 항목 검사 ─────────────────────────

def validate_entry(a, errors, warnings, today):
    aid = a.get("id", "?")
    missing = [k for k in KEY_ORDER if k not in a]
    extra = [k for k in a if k not in KEY_ORDER]
    if missing:
        errors.append(f"{aid}: 필수 키 누락 {missing}")
        return
    if extra:
        errors.append(f"{aid}: 정의되지 않은 키 {extra}")
    for k in TEXT_KEYS:
        if not isinstance(a[k], str) or not a[k].strip():
            errors.append(f"{aid}: '{k}' 가 비었거나 문자열이 아님")
    if not isinstance(a["order"], int):
        errors.append(f"{aid}: order 가 정수가 아님")
        return
    cat = a["category"]
    if cat not in CAT_EN:
        errors.append(f"{aid}: 알 수 없는 category '{cat}'")
        return
    if a["category_en"] != CAT_EN[cat]:
        errors.append(f"{aid}: category_en 은 '{CAT_EN[cat]}' 이어야 함 (현재 '{a['category_en']}')")
    m = re.fullmatch(r"([a-z]{3})-(\d{2,})", aid)
    if not m or m.group(1) != CAT_PREFIX[cat]:
        errors.append(f"{aid}: id 는 '{CAT_PREFIX[cat]}-NN' 형식이어야 함")
    elif int(m.group(2)) != a["order"]:
        errors.append(f"{aid}: id 번호({int(m.group(2))})와 order({a['order']})가 다름")
    if not DATE_RE.match(a["date_added"]):
        errors.append(f"{aid}: date_added 형식 오류 '{a['date_added']}'")
    elif a["date_added"] > today.isoformat():
        errors.append(f"{aid}: 미래 날짜 {a['date_added']} (오늘 KST {today})")
    if not READ_TIME_RE.match(a["read_time"]):
        errors.append(f"{aid}: read_time 은 'N분 읽기' 형식 (현재 '{a['read_time']}')")
    for k, (lo, hi) in LIMITS.items():
        n = len(a[k])
        if n < lo:
            errors.append(f"{aid}: {k} 가 너무 짧음 ({n}자 < {lo})")
        elif n > hi:
            warnings.append(f"{aid}: {k} 가 평소보다 김 ({n}자 > {hi})")
    paras = [p for p in a["content"].split("\n\n") if p.strip()]
    if len(paras) < 3:
        errors.append(f"{aid}: content 문단이 {len(paras)}개 (빈 줄로 나눈 3문단 이상)")
    for k in TEXT_KEYS:
        if FORBIDDEN_IN_TEXT.search(a[k]):
            errors.append(f"{aid}: '{k}' 에 남은 작업 흔적/코드 조각이 있음")
    if not re.search(r"(19|20)\d{2}", a["zeitgeist_connection"]):
        errors.append(f"{aid}: zeitgeist_connection 에 날짜(연도)가 붙은 최근 사실이 없음")


def validate_new(new, old, errors, warnings, today):
    """old(기존 전체) 뒤에 new 를 붙일 때의 검사."""
    nxt = next_numbers(old)
    gaps = coverage_gaps(old, today)
    seen_ids = {a["id"] for a in old}
    seen_titles = {a["title"].strip() for a in old}
    seen_topics = {a["author_topic"].strip() for a in old}
    old_works = Counter(w for a in old for w in works(a["author_topic"]))
    recent_cut = (today - datetime.timedelta(days=60)).isoformat()
    recent_people = Counter(n for a in old if a["date_added"] >= recent_cut for n in person_names(a["author_topic"]))
    all_people = Counter(n for a in old for n in person_names(a["author_topic"]))
    batch_slots = Counter()

    for a in new:
        validate_entry(a, errors, warnings, today)
        if any(k not in a for k in KEY_ORDER) or a.get("category") not in CAT_EN:
            continue
        aid, cat, day = a["id"], a["category"], a["date_added"]
        if aid in seen_ids:
            errors.append(f"{aid}: 이미 있는 id")
        seen_ids.add(aid)
        expected = f"{CAT_PREFIX[cat]}-{nxt[cat]:02d}"
        if aid != expected:
            errors.append(f"{aid}: 다음 번호는 {expected} 이어야 함")
        else:
            nxt[cat] += 1
        if cat not in gaps.get(day, []):
            errors.append(f"{aid}: {day} '{cat}' 는 발행할 자리가 아님 (이미 발행됐거나 날짜 범위 밖 — plan 으로 확인)")
        batch_slots[(day, cat)] += 1
        if batch_slots[(day, cat)] > 1:
            errors.append(f"{aid}: 이번 묶음에 {day} '{cat}' 가 두 편")
        if day < START_DATE.isoformat():
            errors.append(f"{aid}: {START_DATE} 이전 날짜로는 발행하지 않음")
        if a["title"].strip() in seen_titles:
            errors.append(f"{aid}: 같은 제목이 이미 있음 '{a['title']}'")
        seen_titles.add(a["title"].strip())
        if a["author_topic"].strip() in seen_topics:
            errors.append(f"{aid}: 같은 author_topic 이 이미 있음 '{a['author_topic']}'")
        seen_topics.add(a["author_topic"].strip())
        for w in works(a["author_topic"]):
            if old_works[w]:
                errors.append(f"{aid}: 이미 다룬 작품 《{w}》")
        for n in person_names(a["author_topic"]):
            if recent_people[n]:
                errors.append(f"{aid}: '{n}' 은 최근 60일 안에 이미 다룸")
            elif all_people[n]:
                warnings.append(f"{aid}: '{n}' 은 예전에 다룬 적 있음 (다른 작품이면 허용)")
            recent_people[n] += 1
            all_people[n] += 1


def validate_archive(data, errors, warnings, today):
    ids = Counter(a.get("id") for a in data)
    for i, n in ids.items():
        if n > 1:
            errors.append(f"중복 id: {i}")
    for a in data:
        missing = [k for k in KEY_ORDER if k not in a]
        if missing:
            errors.append(f"{a.get('id')}: 필수 키 누락 {missing}")
            continue
        if a["category"] not in CAT_EN:
            errors.append(f"{a['id']}: 알 수 없는 category '{a['category']}'")
            continue
        if a["category_en"] != CAT_EN[a["category"]]:
            errors.append(f"{a['id']}: category_en '{a['category_en']}' ≠ '{CAT_EN[a['category']]}'")
        if not READ_TIME_RE.match(a["read_time"]):
            errors.append(f"{a['id']}: read_time 형식 '{a['read_time']}'")
        if not DATE_RE.match(str(a["date_added"])):
            errors.append(f"{a['id']}: date_added 형식 '{a['date_added']}'")
        elif a["date_added"] > today.isoformat():
            errors.append(f"{a['id']}: 미래 날짜 {a['date_added']}")
    for c, _, p in CATEGORIES:
        nums = sorted(int(a["id"].split("-")[1]) for a in data
                      if a.get("category") == c and re.fullmatch(rf"{p}-\d+", str(a.get("id"))))
        if nums != list(range(1, len(nums) + 1)):
            errors.append(f"{p}: 번호가 1부터 빈틈없이 이어지지 않음")
    per_day = Counter((a.get("date_added"), a.get("category")) for a in data
                      if str(a.get("date_added")) >= START_DATE.isoformat())
    for (d, c), n in per_day.items():
        if n > 1:
            errors.append(f"{d} '{c}' 가 {n}편 (하루 카테고리당 1편)")


# ───────────────────────── 명령 ─────────────────────────

def cmd_plan(args):
    data = load_db()
    today = today_kst()
    gaps = coverage_gaps(data, today)
    nxt = next_numbers(data)
    print(f"오늘(KST) {today} · 아카이브 {len(data)}편")
    if not gaps:
        print("✅ 써야 할 글 없음 — 오늘까지 모든 날짜·카테고리 발행 완료")
        return
    print("\n써야 할 글 (날짜 오래된 것부터, 한 실행에 최대 2일치):")
    for day in sorted(gaps)[:2]:
        for c in gaps[day]:
            print(f"  {day}  {CAT_PREFIX[c]}-{nxt[c]:02d}  {c} ({CAT_EN[c]})")
            nxt[c] += 1
    if len(gaps) > 2:
        print(f"  … 그 밖에 비어 있는 날짜 {len(gaps) - 2}일: {', '.join(sorted(gaps)[2:])}")
    cut = (today - datetime.timedelta(days=60)).isoformat()
    people = sorted({n for a in data if a["date_added"] >= cut for n in person_names(a["author_topic"])})
    ws = sorted({w for a in data for w in works(a["author_topic"])})
    print(f"\n최근 60일에 다룬 인물 (다시 쓰지 않음, {len(people)}명):\n  " + ", ".join(people))
    print(f"\n이미 다룬 작품 (다시 쓰지 않음, {len(ws)}편):\n  " + ", ".join(ws))


def normalize_drafts(drafts, old):
    """초안에 id·order·category_en 을 채우고 키 순서·배열 순서를 표준으로 맞춘다."""
    drafts = sorted(drafts, key=lambda a: (a.get("date_added", ""), CAT_RANK.get(a.get("category"), 99)))
    nxt = next_numbers(old)
    out = []
    for a in drafts:
        a = dict(a)
        cat = a.get("category")
        if cat in CAT_EN:
            exp_num = nxt[cat]
            nxt[cat] += 1
            a.setdefault("id", f"{CAT_PREFIX[cat]}-{exp_num:02d}")
            a.setdefault("order", exp_num)
            a.setdefault("category_en", CAT_EN[cat])
        out.append({k: a[k] for k in KEY_ORDER if k in a} | {k: v for k, v in a.items() if k not in KEY_ORDER})
    return out


def cmd_add(args):
    with open(args.drafts, "r", encoding="utf-8") as f:
        drafts = load_json_text(f.read(), args.drafts)
    old = load_db()
    today = today_kst()
    new = normalize_drafts(drafts, old)
    errors, warnings = [], []
    if not new:
        errors.append("초안이 비어 있음")
    validate_new(new, old, errors, warnings, today)
    if errors:
        fail(errors, warnings)
    merged = old + new
    errs2 = []
    validate_archive(merged, errs2, [], today)
    if errs2:
        fail(errs2, warnings)
    write_atomic(merged)
    for w in warnings:
        print(f"⚠️  {w}")
    print(f"✅ {len(new)}편 추가: {', '.join(a['id'] for a in new)} · {len(old)}→{len(merged)}편")


def cmd_check(args):
    base = load_base(args.base)
    cur = load_db()
    today = today_kst()
    errors, warnings = [], []
    if len(cur) < len(base):
        errors.append(f"글 수가 줄었음 {len(base)}→{len(cur)} (삭제·덮어쓰기 의심)")
    if cur[:len(base)] != base:
        changed = [b.get("id") for b, c in zip(base, cur) if b != c]
        errors.append(f"기존 글이 바뀌었거나 순서가 달라짐 (append-only 위반): {changed[:10]}")
    new = cur[len(base):]
    if not errors:
        validate_new(new, base, errors, warnings, today)
    validate_archive(cur, errors, warnings, today)
    if errors:
        fail(errors, warnings)
    for w in warnings:
        print(f"⚠️  {w}")
    print(f"✅ 검문 통과: 기준({args.base}) {len(base)}편 + 새 글 {len(new)}편 = {len(cur)}편")


def cmd_audit(args):
    data = load_db()
    today = today_kst()
    errors, warnings = [], []
    validate_archive(data, errors, warnings, today)
    if errors:
        fail(errors, warnings)
    print(f"✅ 아카이브 구조 이상 없음 ({len(data)}편)")


def main():
    p = argparse.ArgumentParser(description="ARCHE 발행 검문소")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan")
    a = sub.add_parser("add")
    a.add_argument("drafts")
    c = sub.add_parser("check")
    c.add_argument("--base", default="HEAD")
    sub.add_parser("audit")
    args = p.parse_args()
    {"plan": cmd_plan, "add": cmd_add, "check": cmd_check, "audit": cmd_audit}[args.cmd](args)


if __name__ == "__main__":
    main()
