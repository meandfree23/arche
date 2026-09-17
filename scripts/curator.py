#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
문학의 정원 (ARCHE) - 데일리 큐레이션 관리 및 업데이트 엔진
"""

import os
import json
import datetime
import argparse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "literature_db.json")

VALID_CATEGORIES = [
    "시", "소설", "영화 대본", "철학", "칼럼 & 비평",
    "작가의 서신", "신화 & 구전", "매거진 & 씬", "시대의 잠언"
]

def load_db():
    if not os.path.exists(DB_PATH):
        return []
    with open(DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(data):
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def show_stats():
    data = load_db()
    print("\n" + "="*50)
    print(f"📖 [문학의 정원 ARCHE] 아카이브 현황 보고")
    print("="*50)
    print(f"• 총 보관된 문장 수: {len(data)}편")
    
    category_counts = {}
    for item in data:
        cat = item.get("category", "기타")
        category_counts[cat] = category_counts.get(cat, 0) + 1
        
    print("\n[카테고리별 분포]")
    for cat in VALID_CATEGORIES:
        count = category_counts.get(cat, 0)
        print(f"  - {cat:12s} : {count}편")
    print("="*50 + "\n")

def get_today_quote():
    data = load_db()
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    
    # 1. 오늘 날짜와 일치하는 문구 검색
    for item in data:
        if item.get("date") == today_str:
            return item
            
    # 2. 없다면 일차 계산으로 순환(Circular) 반환
    if data:
        day_of_year = datetime.date.today().timetuple().tm_yday
        idx = day_of_year % len(data)
        return data[idx]
    return None

def print_today():
    item = get_today_quote()
    if not item:
        print("보관된 문장이 없습니다.")
        return
        
    print("\n" + "🌿 "*15)
    print(f"【 오늘의 문학 • {item.get('category')} 】")
    print(f"출전: 《{item.get('title')}》 ({item.get('year', '연대미상')})")
    print(f"작가: {item.get('author')}")
    print("-" * 45)
    print(item.get("quote_kr"))
    if item.get("quote_original"):
        print(f"\n[원문 ({item.get('original_language', '원전')}):]")
        print(item.get("quote_original"))
    print("-" * 45)
    print(f"💡 [사유의 질문]:\n{item.get('imagination_prompt')}")
    print("🌿 "*15 + "\n")

def add_entry(entry):
    data = load_db()
    data.append(entry)
    save_db(data)
    print(f"✨ 새로운 문구가 아카이브에 성공적으로 안착되었습니다. (ID: {entry.get('id')})")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="문학의 정원 큐레이션 CLI")
    parser.add_argument("--stats", action="store_true", help="현재 아카이브 통계 출력")
    parser.add_argument("--today", action="store_true", help="오늘의 문장 출력")
    args = parser.parse_args()

    if args.stats:
        show_stats()
    elif args.today:
        print_today()
    else:
        show_stats()
        print_today()
