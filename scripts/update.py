#!/usr/bin/env python3
"""Gold Macro Radar: safe, source-linked public-data snapshot generator.

Stdlib-only. No user keys needed. The classifier labels OBSERVED changes,
not economic surprises versus analysts' consensus. It never fabricates values.
"""
import csv
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
JST = ZoneInfo('Asia/Tokyo')
UTC = timezone.utc

# Entries represent observable series, NOT all macro drivers or a complete calendar.
SERIES = [
    ('DFII10', '美国10年期TIPS实际收益率', 'real_rate', 'pct_point', 0.05, 5, 5),
    ('DGS2', '美国2年期国债收益率', 'nominal_rate', 'pct_point', 0.08, 5, 4),
    ('DGS10', '美国10年期国债收益率', 'nominal_rate', 'pct_point', 0.10, 5, 3),
    ('DTWEXBGS', '美元广义贸易加权指数（非DXY）', 'dollar', 'percent', 0.6, 5, 5),
    ('DCOILWTICO', 'WTI原油（FRED日频价）', 'oil', 'percent', 4.0, 5, 2),
    ('VIXCLS', 'VIX恐慌指数', 'vix', 'percent', 10.0, 5, 2),
    ('T10YIE', '10年期通胀盈亏平衡率', 'breakeven', 'pct_point', 0.08, 5, 2),
    ('DFEDTARU', '美联储目标利率上限', 'fed_policy', 'pct_point', 0.01, 1, 5),
    ('ICSA', '美国首次申请失业救济人数', 'claims', 'percent', 7.0, 1, 3),
    ('UNRATE', '美国失业率', 'unemployment', 'pct_point', 0.15, 1, 4),
    ('PAYEMS', '美国非农就业人数（总量）', 'payroll', 'payroll', 50.0, 1, 4),
    ('CPIAUCSL', '美国CPI同比（由季调指数计算）', 'inflation', 'yoy', 0.15, 1, 4),
    ('PCEPILFE', '美国核心PCE同比（由季调指数计算）', 'inflation', 'yoy', 0.15, 1, 4),
]

FEEDS = [
    ('美联储货币政策公告', 'https://www.federalreserve.gov/feeds/press_monetary.xml', 'policy'),
    ('美联储讲话与证词', 'https://www.federalreserve.gov/feeds/speeches_and_testimony.xml', 'policy'),
    ('美国非农就业发布', 'https://www.bls.gov/feed/empsit.rss', 'release'),
    ('美国CPI发布', 'https://www.bls.gov/feed/cpi.rss', 'release'),
    ('黄金与宏观新闻线索', 'https://news.google.com/rss/search?' + urllib.parse.urlencode({
        'q': '(gold OR XAUUSD) (Federal Reserve OR dollar OR inflation OR oil OR geopolitics) when:3d',
        'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'}), 'news'),
]

HEADERS = {'User-Agent': 'GoldMacroRadar/1.1 (+public macro dashboard; personal use)', 'Accept': '*/*'}


def request_bytes(url: str, timeout: int = 20) -> bytes:
    if not url.startswith('https://'):
        raise ValueError('HTTPS data source required')
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return resp.read(2_500_000)


def fetch_fred(series_id: str) -> list[tuple[str, float]]:
    # Limiting history reduces request payload; yearly CPI calculation needs >12 months.
    since = (datetime.now(UTC).date() - timedelta(days=580)).isoformat()
    url = 'https://fred.stlouisfed.org/graph/fredgraph.csv?' + urllib.parse.urlencode({'id': series_id, 'cosd': since})
    payload = request_bytes(url)
    body = payload.decode('utf-8-sig')
    rows = csv.reader(io.StringIO(body))
    header = next(rows, [])
    if len(header) != 2 or header[0] not in ('observation_date', 'DATE') or header[1] != series_id:
        raise ValueError('Unexpected FRED format: ' + str(header[:2]))
    result = []
    for row in rows:
        if len(row) != 2 or row[1] in ('', '.'): continue
        try:
            val = float(row[1])
            if abs(val) < 1e10:
                result.append((row[0], val))
        except ValueError:
            continue
    if not result: raise ValueError('No valid observations')
    return result


def parse_feed(data: bytes, feed_name: str, group: str) -> list[dict]:
    root = ET.fromstring(data)
    out = []
    items = root.findall('.//item')
    if not items:
        items = root.findall('.//{http://www.w3.org/2005/Atom}entry')
    for item in items[:25]:
        title = (item.findtext('title') or item.findtext('{http://www.w3.org/2005/Atom}title') or '').strip()
        link = (item.findtext('link') or '').strip()
        if not link:
            link_el = item.find('{http://www.w3.org/2005/Atom}link')
            if link_el is not None: link = link_el.get('href') or ''
        date_str = (item.findtext('pubDate') or item.findtext('updated') or
                    item.findtext('{http://www.w3.org/2005/Atom}updated') or '').strip()
        published = None
        try:
            if date_str:
                try: dt = parsedate_to_datetime(date_str)
                except Exception: dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                if dt.tzinfo is None: dt = dt.replace(tzinfo=UTC)
                published = dt.astimezone(UTC).isoformat()
        except Exception:
            pass
        if not title or not link.startswith('https://'): continue
        out.append({'id': 'rss:' + hashlib.sha256((feed_name + link).encode()).hexdigest()[:18],
                    'title': title[:280], 'link': link[:1500], 'published_at': published,
                    'source': feed_name, 'group': group})
    return out


def fetch_feed(source):
    name, url, group = source
    return parse_feed(request_bytes(url), name, group)


def round_clean(x, n=3):
    return round(x, n) if x is not None else None


def create_factor(cfg, points: list[tuple[str, float]]) -> dict:
    sid, name, kind, compare, threshold, lookback, weight = cfg
    latest_date, latest_val = points[-1]
    base_date, base_val = points[-1 - lookback] if len(points) > lookback else points[0]
    if compare == 'yoy':
        # Monthly SA index: derive a *12-observation* annual change.
        if len(points) < 14:
            raise ValueError('Insufficient observations for CPI/PCE YoY')
        year_ago = points[-13][1]
        prev_year_ago = points[-14][1]
        current_yoy = (latest_val / year_ago - 1) * 100
        previous_yoy = (points[-2][1] / prev_year_ago - 1) * 100
        latest = round_clean(current_yoy)
        prior = round_clean(previous_yoy)
        delta = current_yoy - previous_yoy
        units, comparator = '% 同比', '同比较前一期'
    elif compare == 'percent':
        latest, prior = round_clean(latest_val), round_clean(base_val)
        delta = ((latest_val / base_val) - 1) * 100 if base_val else 0
        units, comparator = ('美元/桶', f'较前{lookback}期') if sid == 'DCOILWTICO' else ('指数', f'较前{lookback}期')
    elif compare == 'payroll':
        latest, prior = round_clean(latest_val), round_clean(base_val)
        delta = latest_val - base_val
        units, comparator = '千人', '非农就业总量月差（不是相对预期）'
    else:
        latest, prior = round_clean(latest_val), round_clean(base_val)
        delta = latest_val - base_val
        units = '人' if sid == 'ICSA' else '%' if kind in ('real_rate','nominal_rate','breakeven','fed_policy','unemployment') else '指数'
        if sid == 'ICSA':
            delta = ((latest_val / base_val) - 1) * 100 if base_val else 0
            units = '人'
        comparator = f'较前{lookback}期'
    direction, description, confidence = classify_factor(kind, delta, threshold)
    return {'id': sid, 'name': name, 'category': kind, 'date': latest_date, 'comparison_date': base_date,
            'value': latest, 'previous': prior, 'unit': units, 'delta': round_clean(delta),
            'delta_unit': '%' if compare == 'percent' or sid == 'ICSA' else ('千人' if compare == 'payroll' else '百分点'),
            'comparison': comparator, 'signal': direction, 'reason': description, 'confidence': confidence,
            'weight': weight, 'material': abs(delta) >= threshold,
            'url': f'https://fred.stlouisfed.org/series/{sid}',
            'source': 'FRED（源自美联储/BLS/BEA等）',
            'qualification': '仅比较已公布历史值，不是实际值与分析师一致预期之差。',
            'freshness_days': (datetime.now(UTC).date() - datetime.fromisoformat(latest_date).date()).days}


def classify_factor(kind: str, delta: float, threshold: float) -> tuple[str, str, str]:
    if abs(delta) < threshold:
        return ('neutral', '较选定基准变动未达到观察阈值，不表示没有市场影响。', '中')
    if kind in ('real_rate', 'nominal_rate'):
        if delta < 0:
            return ('bull', '收益率回落通常降低持金机会成本；需核对美元及预期是否已定价。', '中')
        return ('bear', '收益率走高通常提高持金机会成本；若来自财政信用风险，关系可能反转。', '中')
    if kind == 'dollar':
        return ('bull' if delta < 0 else 'bear',
                '美元广义贸易加权指数走' + ('弱' if delta < 0 else '强') + '，通常对美元计价黄金形成' + ('支持。' if delta < 0 else '压制。') + '这不是DXY。', '中')
    if kind == 'oil':
        return ('mixed', '油价波动同时可能改变通胀、政策利率及避险需求，不能单凭油价确定金价方向。', '高')
    if kind == 'vix':
        return ('mixed', 'VIX大幅变动说明风险情绪变化；避险买盘与流动性抛售可能同时出现。', '高')
    if kind == 'breakeven':
        return ('mixed', '通胀预期变动需与名义利率、TIPS实际利率一起判断。', '高')
    if kind == 'fed_policy':
        return ('bull' if delta < 0 else 'bear', '目标利率已' + ('下降' if delta < 0 else '上调') + '；这并不等于超出市场预期，需核对决议声明和FedWatch。', '低')
    if kind == 'claims':
        return ('bull' if delta > 0 else 'bear', '初请失业金人数' + ('增加' if delta > 0 else '减少') + '，通常意味着就业' + ('趋弱' if delta > 0 else '更稳') + '；需结合季节性和降息预期。', '低')
    if kind == 'unemployment':
        return ('bull' if delta > 0 else 'bear', '失业率' + ('上升' if delta > 0 else '下降') + '可能影响降息预期；需核对工资、劳动参与率与非农修正。', '低')
    if kind == 'inflation':
        if delta < 0:
            return ('bull', '同比通胀放缓可能缓解利率压力，但是否利多取决于实际利率与市场预期。', '低')
        return ('mixed', '同比通胀加快既可能提高黄金通胀对冲需求，也可能推高鹰派利率预期。', '高')
    if kind == 'payroll':
        return ('unknown', '这是就业总量的月差，并非“非农实际－预期”；没有市场共识预期及工资、失业率，不能自动判断超预期利多利空。', '高')
    return ('unknown', '缺少足够证据判断方向。', '高')


def classify_headline(title: str) -> tuple[str, str]:
    s = title.lower()
    # Low-confidence headline-only heuristics, never misrepresent as full-text analysis.
    if re.search(r'\b(fed|federal reserve|fomc)\b', s) and re.search(r'\b(cuts?|lowers?|reduces?)\b.{0,35}\b(rate|rates)\b', s):
        return ('bull', '标题提到降息，通常利多黄金；是否超预期和资产反应需核对正文。')
    if re.search(r'\b(fed|federal reserve|fomc)\b', s) and re.search(r'\b(raises?|hikes?|increases?)\b.{0,35}\b(rate|rates)\b', s):
        return ('bear', '标题提到加息，通常不利黄金；已被定价或信用风险因素可能改变结果。')
    if re.search(r'\b(attack|strikes?|war|invasion|sanctions|escalat|conflict)\b', s):
        return ('mixed', '地缘事件可能提高避险需求，也可能推高美元或实际利率。仅依据标题，待核实。')
    if re.search(r'\b(oil|opec|crude)\b', s):
        return ('mixed', '油价或供给新闻的黄金传导取决于通胀预期与实际利率。')
    if re.search(r'\b(inflation|cpi|pce|tariff|nonfarm|payroll|unemployment)\b', s):
        return ('unknown', '数据或政策标题不足以判断相对市场预期的意外程度。需看实际值、预期、修正。')
    return ('unknown', '当前仅抓取标题，未核对全文或市场一致预期。')


def eval_news(item: dict) -> dict:
    sig, rationale = classify_headline(item['title'])
    return {**item, 'signal': sig, 'reason': rationale,
            'confidence': '低', 'kind': 'news', 'classification_basis': '标题规则初判，不代表已验证报道正文'}


def make_event(factor: dict) -> dict:
    # ID includes date AND measured value, preserving back-revisions in history.
    eid = f"obs:{factor['id']}:{factor['date']}:{factor['value']}"
    return {'id': eid, 'title': factor['name'] + '出现显著变化', 'published_at': factor['date'] + 'T00:00:00+00:00',
            'observation_date': factor['date'], 'source': factor['source'], 'url': factor['url'],
            'signal': factor['signal'], 'reason': factor['reason'], 'kind': 'metric',
            'confidence': factor['confidence'], 'value': factor['value'], 'previous': factor['previous'],
            'delta': factor['delta'], 'delta_unit': factor['delta_unit'], 'comparison': factor['comparison'],
            'disclaimer': factor['qualification']}


def read_json(path, fallback):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception: return fallback


def iso_dt(d):
    try: return datetime.fromisoformat(d.replace('Z', '+00:00'))
    except Exception: return datetime(1970, 1, 1, tzinfo=UTC)


def generate(fetcher=request_bytes, output=True):
    now = datetime.now(UTC)
    old_latest = read_json(DATA / 'latest.json', {})
    history = read_json(DATA / 'history.json', {'events': []}).get('events', [])
    err, observations, news = [], {}, []

    # Dataset fetcher is injectable for tests; respects provider errors individually.
    def get_series(cfg):
        sid = cfg[0]
        since = (now.date() - timedelta(days=580)).isoformat()
        url = 'https://fred.stlouisfed.org/graph/fredgraph.csv?' + urllib.parse.urlencode({'id': sid, 'cosd': since})
        body = fetcher(url).decode('utf-8-sig')
        rows = list(csv.reader(io.StringIO(body)))
        h = rows[0] if rows else []
        if len(h) != 2 or h[0] not in ('observation_date', 'DATE') or h[1] != sid:
            raise ValueError('Unexpected CSV header')
        pts = []
        for row in rows[1:]:
            if len(row) == 2 and row[1] not in ('', '.'):
                try: pts.append((row[0], float(row[1])))
                except ValueError: pass
        if not pts: raise ValueError('No valid observations')
        return create_factor(cfg, pts)

    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = {pool.submit(get_series, cfg): cfg[0] for cfg in SERIES}
        for future in as_completed(jobs):
            sid = jobs[future]
            try: observations[sid] = future.result()
            except Exception as exc: err.append(f'{sid}: {type(exc).__name__}: {exc}')

    for f in FEEDS:
        try:
            payload = fetcher(f[1])
            news.extend(eval_news(x) for x in parse_feed(payload, f[0], f[2]))
        except Exception as exc: err.append(f'RSS {f[0]}: {type(exc).__name__}: {exc}')
    cutoff = now - timedelta(days=14)
    recent_news = [e for e in news if e.get('published_at') and iso_dt(e['published_at']) >= cutoff]
    news_ids = set()
    recent_news = [e for e in sorted(recent_news, key=lambda x: x.get('published_at') or '', reverse=True)
                   if not (e['id'] in news_ids or news_ids.add(e['id']))][:45]

    factors = [observations[cfg[0]] for cfg in SERIES if cfg[0] in observations]
    if not factors and not recent_news:
        # On provider outage, keep previous verified data rather than overwrite with empty/made-up values.
        if not old_latest.get('factors'):
            result = {'status': 'unavailable', 'generated_at': now.isoformat(), 'factors': [],
                      'news': [], 'summary': {'signal': 'unknown', 'reason': '所有数据源暂时不可用'}, 'errors': err}
        else:
            result = {**old_latest, 'status': 'stale', 'last_attempt_at': now.isoformat(), 'errors': err}
    else:
        usable = [f for f in factors if f['material'] and f['signal'] in ('bull','bear')
                  and f['category'] in ('real_rate','nominal_rate','dollar')
                  and f['freshness_days'] <= 7]
        bullish = sum(f['weight'] for f in usable if f['signal']=='bull')
        bearish = sum(f['weight'] for f in usable if f['signal']=='bear')
        if len(usable) < 2: overall, why = 'unknown', '关键市场因子尚不足两个显著有效观测，不能确认共同方向。'
        elif bullish >= 2 * max(1,bearish): overall, why = 'bull', '仅从已抓取到的利率与美元方向看，短线更偏多；非涨幅预测。'
        elif bearish >= 2 * max(1,bullish): overall, why = 'bear', '仅从已抓取到的利率与美元方向看，短线更偏空；非跌幅预测。'
        else: overall, why = 'mixed', '利率与美元关键因子互相抵消，缺少一致信号。'
        result = {'status': 'ok' if not err else 'partial', 'generated_at': now.isoformat(),
                  'factors': factors, 'news': recent_news[:25],
                  'summary': {'signal': overall, 'reason': why, 'bull_weight': bullish,
                              'bear_weight': bearish, 'basis': '已抓取的利率和美元历史变动，不包含市场一致预期'},
                  'coverage': {'received_series': len(observations), 'expected_series': len(SERIES),
                               'working_feeds': len(FEEDS) - sum(1 for x in err if x.startswith('RSS')),
                               'expected_feeds': len(FEEDS)}, 'errors': err}
    new_events = [make_event(f) for f in factors if f['material'] and f['freshness_days'] <= 15]
    new_events += recent_news
    ids = set()
    merged = []
    for e in new_events + history:
        if e['id'] not in ids:
            ids.add(e['id']); merged.append(e)
    merged.sort(key=lambda e: e.get('published_at') or '', reverse=True)
    merged = merged[:350]
    if output:
        DATA.mkdir(parents=True, exist_ok=True)
        (DATA / 'latest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        (DATA / 'history.json').write_text(json.dumps({'generated_at': now.isoformat(), 'events': merged}, ensure_ascii=False, indent=2), encoding='utf-8')
    return result, merged


if __name__ == '__main__':
    payload, events = generate()
    print(json.dumps({'status': payload['status'], 'factors': len(payload.get('factors',[])),
                      'news': len(payload.get('news',[])), 'historical_events': len(events),
                      'errors': payload.get('errors',[])[:5]}, ensure_ascii=False))
    # Fail only if ALL series/feeds failed; GitHub actions will not claim success.
    if payload['status'] in ('unavailable', 'stale'): sys.exit(2)
