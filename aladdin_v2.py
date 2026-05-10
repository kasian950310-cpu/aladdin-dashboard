"""
🔮 알라딘 v2.0 — 전세계 돈의 흐름 대시보드
자산 1천억 프로젝트 | 글로벌 기관 자금 흐름 추적

실행: python3 -m streamlit run aladdin_v2.py
"""

import os, json, requests, feedparser
import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path

# ── 번역 (라이브러리 없이 requests만 사용) ────────────────────────────────────
def translate_ko(text: str) -> str:
    """Google Translate 무료 엔드포인트로 한국어 번역"""
    if not text or not text.strip():
        return text
    # 이미 한글이면 스킵
    if any('가' <= c <= '힣' for c in text):
        return text
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {
            'client': 'gtx',
            'sl': 'en',
            'tl': 'ko',
            'dt': 't',
            'q': text[:500],
        }
        r = requests.get(url, params=params, timeout=5)
        result = r.json()
        translated = ''.join(part[0] for part in result[0] if part[0])
        return translated
    except:
        return text

def translate_batch(texts: list) -> list:
    """여러 텍스트 일괄 번역"""
    return [translate_ko(t) for t in texts]

# 공포탐욕 레이블 한글화
FG_KO = {
    'extreme fear': '극도의 공포',
    'fear':         '공포',
    'neutral':      '중립',
    'greed':        '탐욕',
    'extreme greed':'극도의 탐욕',
}
def fg_label_ko(label: str) -> str:
    return FG_KO.get(label.lower(), label)

# ══════════════════════════════════════════════════════════════════════════════
# 페이지 설정
# ══════════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="🔮 알라딘 v2.0 | 전세계 돈의 흐름",
    page_icon="🔮",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
[data-testid="stAppViewContainer"] { background:#0a0e1a; }
[data-testid="stHeader"]           { background:transparent; }
.card {
    background:linear-gradient(135deg,#111827 0%,#1e2535 100%);
    border:1px solid #2a3555; border-radius:14px;
    padding:16px 20px; margin-bottom:8px;
}
.big-num { font-size:1.5rem; font-weight:700; margin:4px 0; }
.label   { font-size:0.74rem; color:#6b7a99; margin:0; }
.green   { color:#00e676; } .red { color:#ff4e6a; } .gray { color:#6b7a99; }
.tag-on  { background:#0d3320; color:#00e676; border:1px solid #00e676;
           padding:3px 10px; border-radius:20px; font-weight:700; font-size:0.85rem; }
.tag-off { background:#3b0a12; color:#ff4e6a; border:1px solid #ff4e6a;
           padding:3px 10px; border-radius:20px; font-weight:700; font-size:0.85rem; }
.tag-neu { background:#2b2000; color:#ffb300; border:1px solid #ffb300;
           padding:3px 10px; border-radius:20px; font-weight:700; font-size:0.85rem; }
.news-item {
    background:#111827; border-left:3px solid #3b5bdb;
    border-radius:0 8px 8px 0; padding:10px 14px; margin:5px 0;
}
.news-src  { font-size:0.72rem; color:#6b7a99; }
.news-title{ font-size:0.88rem; color:#c8d0e7; line-height:1.5; }
div[data-testid="stMetric"] label { color:#6b7a99 !important; }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# 데이터 페치
# ══════════════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=60)
def fetch_market():
    syms = {
        'sp500':'^GSPC','nasdaq':'^IXIC','dow':'^DJI',
        'kospi':'^KS11','nikkei':'^N225','hangseng':'^HSI','dax':'^GDAXI',
        'dxy':'DX-Y.NYB','eurusd':'EURUSD=X','usdjpy':'USDJPY=X','usdkrw':'USDKRW=X',
        'us10y':'^TNX','us3m':'^IRX',
        'gold':'GC=F','oil':'CL=F','silver':'SI=F',
    }
    out = {}
    for k, s in syms.items():
        try:
            h = yf.Ticker(s).history(period='5d').dropna(subset=['Close'])
            if len(h) >= 2:
                p, pr = float(h['Close'].iloc[-1]), float(h['Close'].iloc[-2])
                out[k] = {'price': p, 'change': (p-pr)/pr*100}
            elif len(h) == 1:
                p = float(h['Close'].iloc[-1])
                out[k] = {'price': p, 'change': 0.0}
            else:
                out[k] = {'price': 0.0, 'change': 0.0}
        except:
            out[k] = {'price': 0.0, 'change': 0.0}
    return out


@st.cache_data(ttl=120)
def fetch_etfs():
    """큰손 ETF — 주식/채권/코인/섹터별 자금 추적"""
    groups = {
        '주식 ETF': {
            'SPY': ('S&P500 ETF',       'BlackRock'),
            'QQQ': ('나스닥100 ETF',    'Invesco'),
            'VWO': ('신흥국 ETF',       'Vanguard'),
            'EEM': ('신흥국 ETF(iSh)',  'BlackRock'),
        },
        '채권 ETF': {
            'TLT': ('미 장기채 ETF',    'BlackRock'),
            'SHY': ('미 단기채 ETF',    'BlackRock'),
            'HYG': ('하이일드 ETF',     'BlackRock'),
            'EMB': ('신흥국 채권 ETF',  'BlackRock'),
        },
        '코인 ETF (기관)': {
            'IBIT':('BlackRock BTC ETF','BlackRock'),
            'FBTC':('Fidelity BTC ETF', 'Fidelity'),
            'GBTC':('Grayscale BTC',    'Grayscale'),
            'ETHA':('BlackRock ETH ETF','BlackRock'),
        },
        '원자재 ETF': {
            'GLD': ('금 ETF',           'SPDR'),
            'SLV': ('은 ETF',           'iShares'),
            'USO': ('원유 ETF',         'USCF'),
            'UNG': ('천연가스 ETF',     'USCF'),
        },
        '섹터 ETF': {
            'XLK': ('기술 섹터',        ''),
            'XLF': ('금융 섹터',        ''),
            'XLE': ('에너지 섹터',      ''),
            'XLV': ('헬스케어 섹터',    ''),
            'XLP': ('필수소비재 섹터',  ''),
            'XLI': ('산업재 섹터',      ''),
            'XLRE':('부동산 섹터',      ''),
            'XLU': ('유틸리티 섹터',    ''),
        },
    }
    result = {}
    for grp, etfs in groups.items():
        result[grp] = {}
        for sym, (name, issuer) in etfs.items():
            try:
                t = yf.Ticker(sym)
                h = t.history(period='5d').dropna(subset=['Close'])
                info = {}
                try:
                    info = t.info
                except:
                    pass
                if len(h) >= 2:
                    p  = float(h['Close'].iloc[-1])
                    pr = float(h['Close'].iloc[-2])
                    vol= int(h['Volume'].iloc[-1]) if 'Volume' in h else 0
                    avg_vol = int(h['Volume'].mean()) if 'Volume' in h else 1
                    chg = (p - pr) / pr * 100
                    aum = info.get('totalAssets', 0)
                    result[grp][sym] = {
                        'name': name, 'issuer': issuer,
                        'price': p, 'change': chg,
                        'aum': aum,
                        'vol_ratio': vol / avg_vol if avg_vol > 0 else 1.0,
                        'flow': '유입' if chg > 0.3 else '유출' if chg < -0.3 else '중립',
                    }
                else:
                    result[grp][sym] = {'name': name, 'issuer': issuer,
                                        'price': 0, 'change': 0, 'aum': 0,
                                        'vol_ratio': 1.0, 'flow': '중립'}
            except:
                result[grp][sym] = {'name': name, 'issuer': issuer,
                                    'price': 0, 'change': 0, 'aum': 0,
                                    'vol_ratio': 1.0, 'flow': '중립'}
    return result


@st.cache_data(ttl=120)
def fetch_crypto():
    try:
        r = requests.get(
            'https://api.coingecko.com/api/v3/simple/price',
            params={'ids':'bitcoin,ripple,ethereum,solana',
                    'vs_currencies':'usd,krw',
                    'include_24hr_change':'true',
                    'include_market_cap':'true'},
            timeout=10)
        return r.json()
    except:
        return {}


@st.cache_data(ttl=120)
def fetch_crypto_global():
    try:
        r = requests.get('https://api.coingecko.com/api/v3/global', timeout=10)
        return r.json().get('data', {})
    except:
        return {}


@st.cache_data(ttl=600)
def fetch_fear_greed():
    try:
        r = requests.get('https://api.alternative.me/fng/', timeout=10)
        d = r.json()['data'][0]
        raw_label = d['value_classification']
        return {'value': int(d['value']), 'label': fg_label_ko(raw_label)}
    except:
        return {'value': 50, 'label': '중립'}


@st.cache_data(ttl=1800)  # 30분 캐시 (번역 포함)
def fetch_institution_news():
    """기관투자 뉴스 RSS — BlackRock, 기관 동향 (한글 번역 + 날짜 포함)"""
    feeds = [
        ('Bloomberg Markets',  'https://feeds.bloomberg.com/markets/news.rss'),
        ('Reuters Business',   'https://feeds.reuters.com/reuters/businessNews'),
        ('ETF.com',            'https://www.etf.com/sections/daily-etf-watch?format=feed&type=rss'),
        ('ZeroHedge',          'https://feeds.feedburner.com/zerohedge/feed'),
    ]
    articles = []
    for src, url in feeds:
        try:
            resp = requests.get(url, headers={'User-Agent':'AlaadinBot/2.0'}, timeout=10)
            feed = feedparser.parse(resp.content)
            for e in feed.entries[:20]:
                title = e.get('title','').strip()
                link  = e.get('link','').strip()

                # 날짜 파싱
                pub_date = ''
                if hasattr(e, 'published_parsed') and e.published_parsed:
                    try:
                        import time
                        dt = datetime.fromtimestamp(time.mktime(e.published_parsed))
                        pub_date = dt.strftime('%m/%d %H:%M')
                    except:
                        pub_date = e.get('published', '')[:10]
                elif e.get('published'):
                    pub_date = e.get('published', '')[:16]

                articles.append({'source': src, 'title': title, 'link': link, 'date': pub_date})
                if len(articles) >= 30:
                    break
        except:
            pass

    # 제목 일괄 한국어 번역
    translated = []
    for art in articles[:30]:
        title_ko = translate_ko(art['title'])
        translated.append({**art, 'title': title_ko, 'title_orig': art['title']})
    return translated


@st.cache_data(ttl=60)
def fetch_btc_history():
    try:
        r = requests.get(
            'https://api.coingecko.com/api/v3/coins/bitcoin/market_chart',
            params={'vs_currency':'usd','days':'7','interval':'hourly'},
            timeout=10)
        data = r.json().get('prices', [])
        df = pd.DataFrame(data, columns=['ts','price'])
        df['ts'] = pd.to_datetime(df['ts'], unit='ms')
        return df
    except:
        return pd.DataFrame()


def get_risk_scenarios():
    """25개+ 리스크 시나리오 — 자산별 충격 범위 (역사적 데이터 기반)"""
    # 형식: {자산: (최소%, 최대%)}
    return {
        "🏦 금리 인상 +0.5% (매파적 Fed)": {
            "설명": "연준이 예상보다 공격적으로 기준금리 0.5% 인상 결정",
            "선행사례": "2022년 연속 자이언트스텝",
            "S&P500": (-5, -8), "나스닥": (-7, -12), "KOSPI": (-5, -9),
            "BTC": (-10, -18), "금": (-3, -6), "장기채(TLT)": (-6, -10),
            "달러(DXY)": (2, 4), "원유": (-2, -5), "신흥국": (-6, -10),
        },
        "🏦 금리 인상 +1% (초긴축)": {
            "설명": "글로벌 인플레이션 재점화로 1%p 급격한 금리 인상",
            "선행사례": "1994년 연준 긴축, 2022년 자이언트스텝 4회 연속",
            "S&P500": (-10, -15), "나스닥": (-15, -22), "KOSPI": (-10, -16),
            "BTC": (-20, -35), "금": (-5, -10), "장기채(TLT)": (-12, -18),
            "달러(DXY)": (4, 8), "원유": (-3, -8), "신흥국": (-12, -18),
        },
        "🏦 금리 인상 +2% (충격 긴축)": {
            "설명": "극단적 인플레이션 대응, 1980년 볼커쇼크 수준",
            "선행사례": "1980년 폴 볼커 Fed 의장, 금리 20% 인상",
            "S&P500": (-20, -30), "나스닥": (-30, -45), "KOSPI": (-18, -28),
            "BTC": (-40, -60), "금": (-8, -15), "장기채(TLT)": (-20, -30),
            "달러(DXY)": (8, 15), "원유": (-5, -15), "신흥국": (-20, -35),
        },
        "✂️ 금리 인하 -0.5% (완화적 피벗)": {
            "설명": "연준이 경기 방어를 위해 금리 인하 시작",
            "선행사례": "2019년 보험성 금리 인하",
            "S&P500": (3, 8), "나스닥": (5, 12), "KOSPI": (3, 7),
            "BTC": (10, 25), "금": (2, 6), "장기채(TLT)": (4, 8),
            "달러(DXY)": (-2, -5), "원유": (2, 5), "신흥국": (4, 9),
        },
        "✂️ 금리 인하 -1% (공격적 완화)": {
            "설명": "경기침체 예방을 위한 대규모 금리 인하",
            "선행사례": "2020년 코로나 긴급 인하, 2008년 금융위기",
            "S&P500": (8, 18), "나스닥": (12, 25), "KOSPI": (7, 15),
            "BTC": (25, 50), "금": (5, 12), "장기채(TLT)": (8, 15),
            "달러(DXY)": (-5, -10), "원유": (5, 10), "신흥국": (8, 18),
        },
        "📉 경미한 경기침체 (-20%)": {
            "설명": "기술적 침체(2분기 연속 GDP 감소), 실업률 소폭 상승",
            "선행사례": "2001년 닷컴 버블 초기, 1990년 걸프전 침체",
            "S&P500": (-15, -25), "나스닥": (-20, -35), "KOSPI": (-15, -22),
            "BTC": (-30, -50), "금": (5, 15), "장기채(TLT)": (8, 15),
            "달러(DXY)": (2, 6), "원유": (-15, -30), "신흥국": (-18, -28),
        },
        "📉 심각한 경기침체 (-40%)": {
            "설명": "금융시스템 위기 동반, 실업률 급등, 신용경색",
            "선행사례": "2008~2009 금융위기, S&P500 -57%",
            "S&P500": (-35, -50), "나스닥": (-45, -65), "KOSPI": (-35, -50),
            "BTC": (-60, -80), "금": (15, 30), "장기채(TLT)": (20, 35),
            "달러(DXY)": (5, 12), "원유": (-40, -65), "신흥국": (-40, -60),
        },
        "🏦 SVB형 은행 위기": {
            "설명": "지역은행 연쇄 파산, 예금 인출 사태, 신용 경색",
            "선행사례": "2023년 SVB·크레디트스위스 사태",
            "S&P500": (-8, -15), "나스닥": (-8, -14), "KOSPI": (-7, -13),
            "BTC": (-15, -25), "금": (5, 12), "장기채(TLT)": (5, 12),
            "달러(DXY)": (-2, -5), "원유": (-8, -15), "신흥국": (-10, -18),
        },
        "💣 2008형 글로벌 금융위기": {
            "설명": "시스템 리스크, 파생상품 붕괴, 글로벌 신용동결",
            "선행사례": "2008 리먼브라더스 파산",
            "S&P500": (-40, -57), "나스닥": (-45, -60), "KOSPI": (-50, -65),
            "BTC": (-70, -85), "금": (10, 25), "장기채(TLT)": (15, 30),
            "달러(DXY)": (8, 15), "원유": (-50, -70), "신흥국": (-50, -70),
        },
        "₿ BTC 급락 -30%": {
            "설명": "규제 이슈 또는 대형 거래소 해킹으로 급락",
            "선행사례": "2021년 중국 채굴 금지, 2022년 FTX 사태 초기",
            "S&P500": (-2, -5), "나스닥": (-3, -7), "KOSPI": (-2, -4),
            "BTC": (-28, -35), "금": (0, 3), "장기채(TLT)": (0, 2),
            "달러(DXY)": (0, 2), "원유": (-1, -3), "신흥국": (-2, -5),
        },
        "₿ BTC 폭락 -50%": {
            "설명": "기관 대규모 매도, ETF 환매 폭증, 시장 공황",
            "선행사례": "2021년 5월 -53%, 2022년 LUNA 붕괴",
            "S&P500": (-3, -8), "나스닥": (-5, -10), "KOSPI": (-3, -7),
            "BTC": (-48, -55), "금": (2, 6), "장기채(TLT)": (1, 4),
            "달러(DXY)": (1, 3), "원유": (-2, -5), "신흥국": (-4, -8),
        },
        "₿ BTC 대폭락 -80% (크립토 겨울)": {
            "설명": "규제 전면금지 또는 기술적 결함 발견으로 붕괴",
            "선행사례": "2018년 크립토 겨울 -84%, 2022년 -77%",
            "S&P500": (-5, -12), "나스닥": (-8, -15), "KOSPI": (-5, -10),
            "BTC": (-75, -85), "금": (3, 8), "장기채(TLT)": (2, 6),
            "달러(DXY)": (2, 5), "원유": (-3, -7), "신흥국": (-6, -12),
        },
        "₿ BTC 대호황 (ETF 대규모 유입)": {
            "설명": "기관 ETF 통한 대규모 자금 유입, 반감기 효과",
            "선행사례": "2024년 현물 ETF 승인 후 랠리",
            "S&P500": (3, 8), "나스닥": (5, 12), "KOSPI": (2, 6),
            "BTC": (50, 150), "금": (2, 5), "장기채(TLT)": (-2, -5),
            "달러(DXY)": (-1, -3), "원유": (1, 4), "신흥국": (3, 8),
        },
        "💵 달러 강세 (DXY +5%)": {
            "설명": "미국 경제 상대적 우위, 안전자산 달러 수요 급증",
            "선행사례": "2022년 달러 인덱스 114 돌파",
            "S&P500": (-3, -7), "나스닥": (-4, -8), "KOSPI": (-7, -12),
            "BTC": (-5, -10), "금": (-5, -9), "장기채(TLT)": (-3, -6),
            "달러(DXY)": (4, 6), "원유": (-5, -9), "신흥국": (-10, -16),
        },
        "💵 달러 강세 (DXY +10%)": {
            "설명": "글로벌 달러 부족, 신흥국 외채위기 촉발",
            "선행사례": "1997년 아시아 외환위기",
            "S&P500": (-6, -12), "나스닥": (-8, -15), "KOSPI": (-15, -25),
            "BTC": (-10, -20), "금": (-8, -15), "장기채(TLT)": (-5, -10),
            "달러(DXY)": (9, 11), "원유": (-10, -18), "신흥국": (-20, -35),
        },
        "💸 달러 약세 (DXY -10%)": {
            "설명": "미국 재정적자 우려, 달러 기축통화 지위 흔들",
            "선행사례": "2020년 코로나 부양책 이후 달러 약세",
            "S&P500": (5, 12), "나스닥": (6, 14), "KOSPI": (8, 15),
            "BTC": (15, 30), "금": (8, 15), "장기채(TLT)": (3, 8),
            "달러(DXY)": (-9, -11), "원유": (8, 15), "신흥국": (10, 20),
        },
        "⚔️ 러시아-우크라이나 확전": {
            "설명": "NATO 직접 개입 또는 핵 위협 고조",
            "선행사례": "2022년 2월 침공 초기 충격",
            "S&P500": (-8, -15), "나스닥": (-8, -14), "KOSPI": (-8, -13),
            "BTC": (-15, -25), "금": (8, 18), "장기채(TLT)": (2, 6),
            "달러(DXY)": (3, 7), "원유": (20, 45), "신흥국": (-12, -20),
        },
        "⚔️ 중동 전쟁 확산 (이란 참전)": {
            "설명": "호르무즈 해협 봉쇄, 원유 공급 30% 차단",
            "선행사례": "1973년 오일쇼크, 1990년 걸프전",
            "S&P500": (-10, -18), "나스닥": (-10, -16), "KOSPI": (-10, -17),
            "BTC": (-15, -25), "금": (12, 25), "장기채(TLT)": (3, 8),
            "달러(DXY)": (4, 8), "원유": (30, 80), "신흥국": (-12, -22),
        },
        "🇨🇳 대만 침공 위기": {
            "설명": "중국 대만 해협 봉쇄, 반도체 공급망 붕괴",
            "선행사례": "1996년 대만해협 위기",
            "S&P500": (-15, -25), "나스닥": (-20, -35), "KOSPI": (-20, -35),
            "BTC": (-25, -40), "금": (10, 20), "장기채(TLT)": (3, 8),
            "달러(DXY)": (5, 10), "원유": (15, 35), "신흥국": (-20, -35),
        },
        "🇨🇳 중국 경제 위기 (부동산 붕괴)": {
            "설명": "헝다 사태 재발, 중국 부동산 버블 전면 붕괴",
            "선행사례": "2021년 헝다 디폴트, 일본 1990년대 잃어버린 10년",
            "S&P500": (-8, -15), "나스닥": (-10, -18), "KOSPI": (-15, -25),
            "BTC": (-15, -28), "금": (5, 12), "장기채(TLT)": (5, 10),
            "달러(DXY)": (3, 7), "원유": (-10, -20), "신흥국": (-20, -35),
        },
        "🛢️ 유가 폭등 +50% (공급 위기)": {
            "설명": "OPEC 극단적 감산 + 지정학적 공급 차단",
            "선행사례": "1973년 오일쇼크, 1979년 이란혁명",
            "S&P500": (-8, -15), "나스닥": (-10, -18), "KOSPI": (-8, -14),
            "BTC": (-10, -20), "금": (8, 15), "장기채(TLT)": (-5, -10),
            "달러(DXY)": (2, 5), "원유": (45, 60), "신흥국": (-10, -18),
        },
        "🛢️ 유가 폭락 -50% (수요 붕괴)": {
            "설명": "글로벌 경기침체 + EV 전환 가속으로 수요 급감",
            "선행사례": "2020년 코로나 -77%, 2014년 셰일혁명",
            "S&P500": (-3, -8), "나스닥": (-2, -6), "KOSPI": (-4, -8),
            "BTC": (-5, -12), "금": (3, 8), "장기채(TLT)": (3, 7),
            "달러(DXY)": (-1, -3), "원유": (-48, -55), "신흥국": (-8, -15),
        },
        "🤖 AI 버블 붕괴": {
            "설명": "AI 수익성 의구심, 빅테크 실적 실망으로 나스닥 급락",
            "선행사례": "2000년 닷컴 버블 붕괴, 나스닥 -78%",
            "S&P500": (-15, -25), "나스닥": (-35, -55), "KOSPI": (-15, -25),
            "BTC": (-20, -35), "금": (5, 12), "장기채(TLT)": (8, 15),
            "달러(DXY)": (2, 5), "원유": (-5, -12), "신흥국": (-12, -20),
        },
        "🤖 AI 랠리 지속 (슈퍼사이클)": {
            "설명": "AGI 개발 성과 발표, 생산성 혁명으로 주식 급등",
            "선행사례": "1990년대 닷컴 버블 상승기, 나스닥 +1000%",
            "S&P500": (15, 35), "나스닥": (25, 60), "KOSPI": (10, 20),
            "BTC": (30, 80), "금": (-3, -8), "장기채(TLT)": (-8, -15),
            "달러(DXY)": (2, 5), "원유": (5, 12), "신흥국": (8, 18),
        },
        "🌐 달러 기축통화 위기": {
            "설명": "BRICS 기축통화 도입, 달러 준비통화 비중 급감",
            "선행사례": "1971년 닉슨쇼크, 브레턴우즈 체제 붕괴",
            "S&P500": (-10, -20), "나스닥": (-12, -22), "KOSPI": (2, 8),
            "BTC": (30, 70), "금": (20, 40), "장기채(TLT)": (-15, -25),
            "달러(DXY)": (-15, -25), "원유": (10, 25), "신흥국": (5, 15),
        },
    }


@st.cache_data(ttl=3600)
def run_monte_carlo(ticker_symbol: str, days: int, n_sim: int = 100_000):
    """기하브라운운동(GBM) 기반 몬테카를로 시뮬레이션"""
    try:
        hist = yf.Ticker(ticker_symbol).history(period='1y')['Close'].dropna()
        if len(hist) < 30:
            return None
        returns = hist.pct_change().dropna()
        mu    = float(returns.mean())
        sigma = float(returns.std())
        S0    = float(hist.iloc[-1])
        dt    = 1 / 252

        # 10만 경로 한번에 계산 (numpy 벡터화)
        Z = np.random.standard_normal((days, n_sim))
        daily_r = np.exp((mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * Z)
        paths = S0 * np.cumprod(daily_r, axis=0)

        final = paths[-1]
        return {
            'S0': S0, 'mu': mu, 'sigma': sigma,
            'paths_sample': paths[:, :200],   # 차트용 200개 샘플
            'final': final,
            'p5':  float(np.percentile(final, 5)),
            'p25': float(np.percentile(final, 25)),
            'p50': float(np.percentile(final, 50)),
            'p75': float(np.percentile(final, 75)),
            'p95': float(np.percentile(final, 95)),
            'prob_up10':  float((final > S0 * 1.10).mean() * 100),
            'prob_up25':  float((final > S0 * 1.25).mean() * 100),
            'prob_up50':  float((final > S0 * 1.50).mean() * 100),
            'prob_down10': float((final < S0 * 0.90).mean() * 100),
            'prob_down25': float((final < S0 * 0.75).mean() * 100),
            'prob_down50': float((final < S0 * 0.50).mean() * 100),
        }
    except:
        return None


def get_economic_calendar():
    """주요 경제 이벤트 캘린더 — 2026년 일정"""
    events = [
        # (날짜, 이름, 중요도, 예상영향, 아이콘)
        ("2026-05-13", "미국 CPI 발표",        "🔴", "인플레이션 핵심 지표 — 금리 방향 결정", "📊"),
        ("2026-05-15", "미국 소매판매",          "🟡", "소비 경기 가늠자",                    "🛍️"),
        ("2026-05-22", "FOMC 회의록 공개",       "🔴", "Fed 향후 금리 힌트",                   "🏦"),
        ("2026-06-05", "미국 NFP 고용지표",      "🔴", "고용 = 금리 결정의 핵심",              "👷"),
        ("2026-06-10", "미국 CPI 발표",         "🔴", "인플레이션 핵심 지표",                  "📊"),
        ("2026-06-17", "FOMC 금리 결정",        "🔴 🔴", "금리 인하/동결/인상 결정",           "🏛️"),
        ("2026-06-25", "미국 GDP (1분기 최종)",  "🟡", "경기침체 여부 판단 기준",               "📈"),
        ("2026-07-02", "미국 NFP 고용지표",      "🔴", "고용 = 금리 결정의 핵심",              "👷"),
        ("2026-07-14", "미국 CPI 발표",         "🔴", "인플레이션 핵심 지표",                  "📊"),
        ("2026-07-28", "FOMC 금리 결정",        "🔴 🔴", "금리 인하/동결/인상 결정",           "🏛️"),
        ("2026-08-06", "미국 NFP 고용지표",      "🔴", "고용 = 금리 결정의 핵심",              "👷"),
        ("2026-08-12", "미국 CPI 발표",         "🔴", "인플레이션 핵심 지표",                  "📊"),
        ("2026-09-15", "FOMC 금리 결정",        "🔴 🔴", "금리 인하/동결/인상 결정",           "🏛️"),
    ]
    today = datetime.now().date()
    result = []
    for date_str, name, importance, desc, icon in events:
        event_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        days_left = (event_date - today).days
        if days_left >= 0:
            result.append({
                'date': date_str,
                'name': name,
                'importance': importance,
                'desc': desc,
                'icon': icon,
                'days_left': days_left,
            })
    return sorted(result, key=lambda x: x['days_left'])[:7]


def load_briefing():
    paths = [
        Path(os.environ.get('BRIEFING_PATH', '/nonexistent')),
        Path(__file__).parent.parent / '보고자' / 'latest_briefing.json',
        Path(__file__).parent / 'latest_briefing.json',
    ]
    for p in paths:
        if p and p.exists():
            try:
                with open(p, encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
    return None


# ══════════════════════════════════════════════════════════════════════════════
# 헬퍼
# ══════════════════════════════════════════════════════════════════════════════
def fmt(v, dec=2):
    if v == 0: return '—'
    if abs(v) >= 1_000_000_000: return f'{v/1e9:.1f}B'
    if abs(v) >= 1_000_000:     return f'{v/1e6:.1f}M'
    if abs(v) >= 10000:         return f'{v:,.0f}'
    return f'{v:,.{dec}f}'

def chg_str(c):
    if c > 0:  return f'▲ +{c:.2f}%', 'green'
    if c < 0:  return f'▼ {c:.2f}%',  'red'
    return '→ 0.00%', 'gray'

def flow_arrow(c):
    if c > 0.5:  return '⬆️ 강한 유입'
    if c > 0.1:  return '↗️ 소폭 유입'
    if c < -0.5: return '⬇️ 강한 유출'
    if c < -0.1: return '↘️ 소폭 유출'
    return '➡️ 중립'


# ══════════════════════════════════════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════════════════════════════════════
def main():
    now = datetime.now()

    # ── 헤더 ──────────────────────────────────────────────────────────────────
    c1, c2 = st.columns([5, 1])
    with c1:
        st.markdown("# 🔮 알라딘 v2.0 — 전세계 돈의 흐름")
        st.caption(f"글로벌 기관 자금 추적 대시보드 | {now.strftime('%Y-%m-%d %H:%M:%S')} | ⏱️ 1분 자동 갱신")
    with c2:
        if st.button("🔄 새로고침", use_container_width=True):
            st.cache_data.clear(); st.rerun()

    # 1분 자동 갱신 (JS)
    st.components.v1.html(
        '<script>setTimeout(function(){window.parent.location.reload();}, 60000);</script>',
        height=0
    )

    # ── 경제 캘린더 (최상단) ────────────────────────────────────────────────────
    calendar = get_economic_calendar()
    if calendar:
        st.markdown("### 📅 주요 경제 일정")
        cols_cal = st.columns(len(calendar))
        for col, ev in zip(cols_cal, calendar):
            d = ev['days_left']
            if d == 0:
                badge_color = "#ff4e6a"; badge_txt = "🔔 오늘!"
            elif d <= 3:
                badge_color = "#ff9800"; badge_txt = f"D-{d}"
            elif d <= 7:
                badge_color = "#ffb300"; badge_txt = f"D-{d}"
            else:
                badge_color = "#3b5bdb"; badge_txt = f"D-{d}"
            with col:
                st.markdown(f"""<div class="card" style="text-align:center;padding:12px 8px;">
                    <p style="font-size:1.3rem;margin:0">{ev['icon']}</p>
                    <p style="font-size:0.72rem;color:#9aa5c0;margin:2px 0">{ev['date']}</p>
                    <p style="font-size:0.78rem;font-weight:700;color:#c8d0e7;margin:4px 0;line-height:1.3">{ev['name']}</p>
                    <div style="margin:6px 0;">
                        <span style="background:{badge_color}22;color:{badge_color};border:1px solid {badge_color};
                            padding:2px 10px;border-radius:20px;font-weight:700;font-size:0.85rem;">{badge_txt}</span>
                    </div>
                    <p style="font-size:0.68rem;color:#6b7a99;margin:0;line-height:1.4">{ev['importance']} {ev['desc']}</p>
                </div>""", unsafe_allow_html=True)
        st.markdown("---")

    # ── 데이터 로딩 ────────────────────────────────────────────────────────────
    with st.spinner("전세계 시장 + 기관 ETF 데이터 수집 중..."):
        mkt    = fetch_market()
        etfs   = fetch_etfs()
        crypto = fetch_crypto()
        cg     = fetch_crypto_global()
        fg     = fetch_fear_greed()
        brief  = load_briefing()
        btc_df = fetch_btc_history()
        news   = fetch_institution_news()

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 1: 돈의 흐름 총괄 신호
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown("---")
    st.markdown("### 📡 전세계 돈의 흐름 총괄")

    sp_c   = mkt.get('sp500',{}).get('change',0)
    btc_c  = crypto.get('bitcoin',{}).get('usd_24h_change',0)
    gold_c = mkt.get('gold',{}).get('change',0)
    dxy_c  = mkt.get('dxy',{}).get('change',0)
    us10y  = mkt.get('us10y',{}).get('price',0)
    fg_val = fg.get('value',50)
    ibit_c = etfs.get('코인 ETF (기관)',{}).get('IBIT',{}).get('change',0)

    signals = [
        ("🏦 주식",    sp_c>0,   f"{sp_c:+.1f}%",     "유입" if sp_c>0 else "유출"),
        ("💵 달러",    dxy_c<0,  f"DXY {mkt.get('dxy',{}).get('price',0):.1f}", "약세→위험선호" if dxy_c<0 else "강세→위험회피"),
        ("₿ BTC ETF", ibit_c>0, f"IBIT {ibit_c:+.1f}%","기관 유입" if ibit_c>0 else "기관 유출"),
        ("🥇 금",      gold_c>0, f"{gold_c:+.1f}%",    "안전자산 선호" if gold_c>0 else "위험선호"),
        ("📊 채권",    us10y<4.0,f"10Y {us10y:.2f}%",  "완화적" if us10y<4.0 else "긴축적"),
        ("😱 시장심리",fg_val>50,f"{fg_val}/100",       fg.get('label','중립')),
    ]
    cols = st.columns(len(signals))
    for col,(label,good,val,desc) in zip(cols,signals):
        color = "#00e676" if good else "#ff4e6a"
        icon  = "▲" if good else "▼"
        with col:
            st.markdown(f"""<div class="card" style="text-align:center;">
                <p class="label">{label}</p>
                <p class="big-num" style="color:{color}">{icon} {val}</p>
                <p class="label">{desc}</p>
            </div>""", unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 2: AI 브리핑
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown("---")
    st.markdown("### 🤖 AI 시장 브리핑")

    if brief:
        direction = brief.get('market_direction','NEUTRAL')
        dir_map = {
            'RISK_ON': ('tag-on',  '🟢 RISK ON — 위험자산 선호'),
            'RISK_OFF':('tag-off', '🔴 RISK OFF — 안전자산 선호'),
            'NEUTRAL': ('tag-neu', '🟡 NEUTRAL — 관망 구간'),
        }
        tag_cls, tag_txt = dir_map.get(direction, dir_map['NEUTRAL'])

        c1, c2 = st.columns([1,3])
        with c1:
            sc = brief.get('sector_counts',{})
            st.markdown(f"""<div class="card" style="text-align:center;padding:24px 14px;">
                <p class="label">시장 방향성</p>
                <div style="margin:10px 0;"><span class="{tag_cls}">{tag_txt}</span></div>
                <p class="label" style="margin-top:14px;">{brief.get('date','')} 기준</p>
                <hr style="border-color:#2a3555;margin:10px 0;">
                <p class="label">수집 기사</p>
                <p style="font-size:1.3rem;font-weight:700;color:#fff">{brief.get('total_articles',0)}건</p>
            </div>""", unsafe_allow_html=True)
            if sc:
                for sec, cnt in sorted(sc.items(), key=lambda x:-x[1])[:5]:
                    bar_w = int(cnt/max(sc.values())*100)
                    st.markdown(f"""<div style="margin:3px 0;font-size:0.76rem;">
                        <span style="color:#9aa5c0">{sec[:10]}</span>
                        <div style="background:#1e2535;border-radius:3px;height:5px;margin-top:2px;">
                            <div style="background:#3b5bdb;width:{bar_w}%;height:5px;border-radius:3px;"></div>
                        </div></div>""", unsafe_allow_html=True)
        with c2:
            tabs = st.tabs(["📊 시장 동향","🔥 주요 이슈","🚨 리스크","💡 인사이트"])
            with tabs[0]:
                st.markdown(f"<div class='card'><p style='line-height:1.8;color:#c8d0e7'>{brief.get('market_summary','—')}</p></div>", unsafe_allow_html=True)
            with tabs[1]:
                for iss in brief.get('key_issues',[]):
                    st.markdown(f"<div style='background:#111827;border-left:3px solid #3b5bdb;border-radius:0 8px 8px 0;padding:9px 14px;margin:5px 0;color:#c8d0e7'>{iss}</div>", unsafe_allow_html=True)
            with tabs[2]:
                for r in brief.get('risk_factors',[]):
                    st.markdown(f"<div style='background:#1a0c10;border-left:3px solid #ff4e6a;border-radius:0 8px 8px 0;padding:9px 14px;margin:5px 0;color:#c8d0e7'>⚠️ {r}</div>", unsafe_allow_html=True)
            with tabs[3]:
                st.markdown(f"<div class='card' style='border-left:4px solid #00e676;'><p style='font-size:1.05rem;color:#fff;line-height:1.8;'>💡 {brief.get('key_insight','—')}</p></div>", unsafe_allow_html=True)
    else:
        st.info("📭 오늘 브리핑 없음 — daily_report.py 실행 후 자동 표시됩니다.")

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 3: 글로벌 증시
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown("---")
    st.markdown("### 🌍 글로벌 증시")
    stock_list = [('S&P 500','sp500'),('NASDAQ','nasdaq'),('DOW','dow'),
                  ('KOSPI','kospi'),('닛케이','nikkei'),('항셍','hangseng'),('DAX','dax')]
    cols = st.columns(len(stock_list))
    for col,(name,key) in zip(cols,stock_list):
        d = mkt.get(key,{}); p,c = d.get('price',0), d.get('change',0)
        with col: st.metric(name, fmt(p,0), f"{c:+.2f}%")

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 4: 달러 & 환율
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown("---")
    st.markdown("### 💵 달러 인덱스 & 환율")
    c1,c2,c3,c4 = st.columns(4)
    dxy_p = mkt.get('dxy',{}).get('price',0)
    dxy_c = mkt.get('dxy',{}).get('change',0)

    with c1:
        dxy_signal = "강달러 → 위험자산 압박" if dxy_p>104 else "약달러 → 위험자산 우호" if dxy_p<100 else "중립"
        st.metric("🇺🇸 DXY 달러지수", f"{dxy_p:.2f}", f"{dxy_c:+.2f}%", help=dxy_signal)
    with c2: st.metric("EUR/USD", fmt(mkt.get('eurusd',{}).get('price',0)), f"{mkt.get('eurusd',{}).get('change',0):+.2f}%")
    with c3: st.metric("USD/JPY", fmt(mkt.get('usdjpy',{}).get('price',0)), f"{mkt.get('usdjpy',{}).get('change',0):+.2f}%")
    with c4: st.metric("USD/KRW", fmt(mkt.get('usdkrw',{}).get('price',0),0), f"{mkt.get('usdkrw',{}).get('change',0):+.2f}%")

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 5: 기관 ETF 자금 흐름 (핵심!)
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown("---")
    st.markdown("### 🏦 기관 ETF 자금 흐름 추적")
    st.caption("주요 자산운용사(BlackRock·Vanguard·Fidelity·SPDR)의 ETF를 통한 글로벌 자금 이동")

    etf_tabs = st.tabs(["📈 주식 ETF","📉 채권 ETF","₿ 코인 ETF (기관)","🥇 원자재 ETF","🔄 섹터 로테이션"])

    def etf_table(group_name):
        grp = etfs.get(group_name, {})
        if not grp:
            st.info("데이터 로딩 중...")
            return
        for sym, d in grp.items():
            c = d.get('change', 0)
            color = "#00e676" if c > 0.3 else "#ff4e6a" if c < -0.3 else "#ffb300"
            icon  = "⬆️" if c > 0.3 else "⬇️" if c < -0.3 else "➡️"
            aum_str = f"AUM ${d.get('aum',0)/1e9:.1f}B" if d.get('aum',0) > 0 else ""
            vol_r = d.get('vol_ratio', 1.0)
            vol_str = f"거래량 {vol_r:.1f}x" if vol_r > 0 else ""
            st.markdown(f"""
            <div style="display:flex;align-items:center;background:#111827;border-radius:10px;
                        padding:10px 16px;margin:4px 0;gap:12px;">
                <div style="width:60px;font-weight:700;color:#fff;font-size:0.9rem;">{sym}</div>
                <div style="flex:1;">
                    <p style="margin:0;font-size:0.82rem;color:#c8d0e7">{d.get('name','')}</p>
                    <p style="margin:0;font-size:0.72rem;color:#6b7a99">{d.get('issuer','')} &nbsp;|&nbsp; {aum_str} &nbsp;|&nbsp; {vol_str}</p>
                </div>
                <div style="text-align:right;min-width:120px;">
                    <p style="margin:0;font-weight:700;color:{color};font-size:0.95rem;">{icon} {c:+.2f}%</p>
                    <p style="margin:0;font-size:0.72rem;color:#6b7a99">${d.get('price',0):.2f}</p>
                </div>
            </div>""", unsafe_allow_html=True)

    with etf_tabs[0]: etf_table('주식 ETF')
    with etf_tabs[1]: etf_table('채권 ETF')
    with etf_tabs[2]:
        # 코인 ETF 특별 섹션 — IBIT 강조
        ibit = etfs.get('코인 ETF (기관)',{}).get('IBIT',{})
        ibit_aum = ibit.get('aum',0)
        btc_usd = crypto.get('bitcoin',{}).get('usd',0)
        ibit_btc = ibit_aum / btc_usd if btc_usd > 0 and ibit_aum > 0 else 0

        st.markdown(f"""<div class="card" style="border:2px solid #f7931a;margin-bottom:12px;">
            <p style="color:#f7931a;font-weight:700;font-size:1rem;margin:0 0 8px 0;">
                ⭐ BlackRock IBIT — 세계 최대 BTC ETF</p>
            <div style="display:flex;gap:24px;flex-wrap:wrap;">
                <div><p class="label">가격</p><p class="big-num">${ibit.get('price',0):.2f}</p></div>
                <div><p class="label">일간 변동</p><p class="big-num" style="color:{'#00e676' if ibit.get('change',0)>0 else '#ff4e6a'}">{ibit.get('change',0):+.2f}%</p></div>
                <div><p class="label">AUM</p><p class="big-num">${ibit_aum/1e9:.1f}B</p></div>
                <div><p class="label">추정 BTC 보유량</p><p class="big-num">{ibit_btc:,.0f} BTC</p></div>
                <div><p class="label">거래량</p><p class="big-num">{ibit.get('vol_ratio',1.0):.1f}x 평균</p></div>
            </div>
        </div>""", unsafe_allow_html=True)
        etf_table('코인 ETF (기관)')
    with etf_tabs[3]: etf_table('원자재 ETF')
    with etf_tabs[4]:
        # 섹터 로테이션 히트맵
        st.markdown("**돈이 어느 섹터로 흐르는가**")
        sec_grp = etfs.get('섹터 ETF', {})
        if sec_grp:
            items = sorted(sec_grp.items(), key=lambda x: -x[1].get('change',0))
            cols2 = st.columns(4)
            for i, (sym, d) in enumerate(items):
                c = d.get('change',0)
                color  = "#00e676" if c>0.5 else "#69db7c" if c>0 else "#ff8787" if c>-0.5 else "#ff4e6a"
                bg     = "#0d2a1a" if c>0 else "#2a0d12"
                with cols2[i % 4]:
                    st.markdown(f"""<div class="card" style="text-align:center;background:{bg};border-color:{color}40;">
                        <p style="margin:0;font-size:0.75rem;color:#9aa5c0">{sym}</p>
                        <p style="margin:2px 0;font-size:0.8rem;color:#c8d0e7">{d.get('name','')}</p>
                        <p style="margin:0;font-weight:700;color:{color};font-size:1.1rem;">{c:+.2f}%</p>
                    </div>""", unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 6: 코인 + 채권/원자재 (좌우)
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown("---")
    col_l, col_r = st.columns(2)

    with col_l:
        st.markdown("### ⛓️ 코인 시장")
        btc  = crypto.get('bitcoin',{})
        xrp  = crypto.get('ripple',{})
        eth  = crypto.get('ethereum',{})
        btc_dom = cg.get('market_cap_percentage',{}).get('btc',0)

        c1,c2 = st.columns(2)
        with c1:
            st.metric("₿ BTC",f"₩{btc.get('krw',0):,.0f}",f"{btc.get('usd_24h_change',0):+.2f}%")
            st.metric("✕ XRP",f"₩{xrp.get('krw',0):,.0f}",f"{xrp.get('usd_24h_change',0):+.2f}%")
        with c2:
            st.metric("◆ ETH",f"₩{eth.get('krw',0):,.0f}",f"{eth.get('usd_24h_change',0):+.2f}%")
            fg_icon = '😱' if fg_val<25 else '😨' if fg_val<45 else '😐' if fg_val<55 else '🤑' if fg_val<75 else '😈'
            st.metric(f"공포탐욕 {fg_icon}",str(fg_val),fg.get('label','중립'))

        st.markdown(f"""<div class="card">
            <p class="label">BTC 도미넌스</p>
            <div style="background:#1e2535;border-radius:6px;height:12px;margin:6px 0;">
                <div style="background:#f7931a;width:{btc_dom:.0f}%;height:12px;border-radius:6px;"></div>
            </div>
            <p style="font-size:0.8rem;color:#9aa5c0">{btc_dom:.1f}% {'— BTC 집중 (알트 약세)' if btc_dom>58 else '— 알트코인 시즌 가능성' if btc_dom<50 else '— 중립'}</p>
        </div>""", unsafe_allow_html=True)

        if not btc_df.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=btc_df['ts'], y=btc_df['price'],
                mode='lines', line=dict(color='#f7931a',width=2),
                fill='tozeroy', fillcolor='rgba(247,147,26,0.07)'))
            fig.update_layout(
                height=150, margin=dict(l=0,r=0,t=4,b=0),
                plot_bgcolor='#111827', paper_bgcolor='#111827',
                xaxis=dict(showgrid=False,showticklabels=False),
                yaxis=dict(showgrid=False,tickfont=dict(color='#6b7a99',size=8)),
                showlegend=False)
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar':False})

    with col_r:
        st.markdown("### 📊 채권 & 원자재")
        r10 = mkt.get('us10y',{}).get('price',0)
        r3m = mkt.get('us3m',{}).get('price',0)
        spread = r10 - r3m

        c1,c2,c3 = st.columns(3)
        with c1: st.metric("10년물",f"{r10:.2f}%",f"{mkt.get('us10y',{}).get('change',0):+.2f}%")
        with c2: st.metric("3개월물",f"{r3m:.2f}%",f"{mkt.get('us3m',{}).get('change',0):+.2f}%")
        with c3: st.metric("스프레드",f"{spread:+.2f}%","⚠️ 역전" if spread<0 else "✅ 정상")
        if spread < 0:
            st.warning("수익률 곡선 역전 — 역사적 침체 선행 신호")

        gold_p = mkt.get('gold',{}).get('price',0)
        c1,c2,c3 = st.columns(3)
        with c1: st.metric("🥇 금",f"${gold_p:,.0f}",f"{mkt.get('gold',{}).get('change',0):+.2f}%")
        with c2: st.metric("🛢️ 원유",f"${mkt.get('oil',{}).get('price',0):.1f}",f"{mkt.get('oil',{}).get('change',0):+.2f}%")
        with c3: st.metric("🥈 은",f"${mkt.get('silver',{}).get('price',0):.2f}",f"{mkt.get('silver',{}).get('change',0):+.2f}%")

        gold_c2 = mkt.get('gold',{}).get('change',0)
        oil_c   = mkt.get('oil',{}).get('change',0)
        st.markdown(f"""<div class="card" style="margin-top:8px;">
            <p class="label" style="margin-bottom:6px;">원자재 시장 신호</p>
            <p style="font-size:0.82rem;color:#c8d0e7;line-height:1.8;">
            {'🔴 원유 급락 — 경기 둔화 우려' if oil_c < -2 else '🟢 원유 상승 — 경기 회복 기대' if oil_c > 2 else '🟡 원유 보합 — 방향성 탐색'}<br>
            {'⚠️ 금↑ + 주식↓ — 전형적 RISK OFF' if gold_c2>0 and sp_c<0 else '✅ 금↓ + 주식↑ — 전형적 RISK ON' if gold_c2<0 and sp_c>0 else '🟡 혼조세 — 복합 신호'}
            {'<br>🚨 금값 $3000 돌파 — 안전자산 선호 극심' if gold_p > 3000 else ''}
            </p>
        </div>""", unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 7: 기관투자 최신 뉴스
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown("---")
    st.markdown("### 📰 기관투자 & 글로벌 자금 최신 뉴스")
    st.caption("Bloomberg · Reuters · ZeroHedge 실시간 피드")

    if news:
        src_filter = list(set(a['source'] for a in news))
        selected = st.multiselect("소스 필터", src_filter, default=src_filter, label_visibility='collapsed')
        filtered = [a for a in news if a['source'] in selected]

        cols2 = st.columns(2)
        for i, art in enumerate(filtered[:20]):
            with cols2[i % 2]:
                link  = art.get('link','')
                title = art.get('title','')
                src   = art.get('source','')
                date  = art.get('date','')
                meta  = f"{src}"
                if date:
                    meta = f"{src} &nbsp;·&nbsp; 🕐 {date}"
                if link:
                    st.markdown(f"""<div class="news-item">
                        <p class="news-src">{meta}</p>
                        <a href="{link}" target="_blank" style="text-decoration:none;">
                            <p class="news-title">{title}</p>
                        </a>
                    </div>""", unsafe_allow_html=True)
                else:
                    st.markdown(f"""<div class="news-item">
                        <p class="news-src">{meta}</p>
                        <p class="news-title">{title}</p>
                    </div>""", unsafe_allow_html=True)
    else:
        st.info("뉴스 로딩 중... (feedparser 설치 필요: pip3 install feedparser)")

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 8: 리스크 시뮬레이션 — 블랙록 알라딘 스타일
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown("---")
    st.markdown("### 🎯 리스크 시뮬레이션 — 생존 중심 포트폴리오 분석")
    st.caption("블랙록 알라딘 철학: 수익 극대화가 아닌 생존 확률 극대화 | 25개 시나리오 + 10만 개의 미래 시뮬레이션")

    risk_tabs = st.tabs(["📋 25개 시나리오 분석", "📊 몬테카를로 (10만 시뮬레이션)"])

    # ── Tab 1: 시나리오 분석 ────────────────────────────────────────────────
    with risk_tabs[0]:
        scenarios = get_risk_scenarios()
        if scenarios:
            scenario_names = list(scenarios.keys())
            assets = ['S&P500', '나스닥', 'KOSPI', 'BTC', '금', '장기채(TLT)', '달러(DXY)', '원유', '신흥국']

            selected_scenario = st.selectbox(
                "시나리오 선택", scenario_names, index=0, label_visibility='collapsed'
            )
            sc = scenarios[selected_scenario]

            col_info, col_chart = st.columns([1, 2])

            with col_info:
                st.markdown(f"""<div class="card">
                    <p style="font-size:0.95rem;font-weight:700;color:#c8d0e7;margin-bottom:8px">{selected_scenario}</p>
                    <p style="font-size:0.82rem;color:#9aa5c0;line-height:1.6">{sc.get('설명','')}</p>
                    <hr style="border-color:#2a3555;margin:8px 0">
                    <p style="font-size:0.72rem;color:#6b7a99">📚 선행사례</p>
                    <p style="font-size:0.8rem;color:#ffb300">{sc.get('선행사례','')}</p>
                </div>""", unsafe_allow_html=True)

                valid_assets = [a for a in assets if a in sc and isinstance(sc[a], tuple)]
                if valid_assets:
                    worst = min(sc[a][0] for a in valid_assets)
                    best  = max(sc[a][1] for a in valid_assets)
                    st.markdown(f"""<div class="card" style="margin-top:8px;">
                        <div style="display:flex;gap:16px;text-align:center;">
                            <div style="flex:1">
                                <p class="label">최악 충격</p>
                                <p style="font-size:1.2rem;font-weight:700;color:#ff4e6a;margin:4px 0">{worst:+.0f}%</p>
                            </div>
                            <div style="flex:1">
                                <p class="label">최선 시나리오</p>
                                <p style="font-size:1.2rem;font-weight:700;color:#00e676;margin:4px 0">{best:+.0f}%</p>
                            </div>
                        </div>
                    </div>""", unsafe_allow_html=True)

            with col_chart:
                fig_sc = go.Figure()
                for asset in assets:
                    if asset not in sc or not isinstance(sc[asset], tuple):
                        continue
                    lo, hi = sc[asset]
                    mid = (lo + hi) / 2
                    color = '#00e676' if mid > 0 else '#ff4e6a'
                    fig_sc.add_trace(go.Bar(
                        name=asset, x=[asset], y=[hi - lo], base=[lo],
                        marker_color=color, marker_opacity=0.85,
                        text=f"{lo:+.0f}%~{hi:+.0f}%",
                        textposition='outside',
                        hovertemplate=f"<b>{asset}</b><br>범위: {lo:+.0f}% ~ {hi:+.0f}%<extra></extra>",
                    ))
                fig_sc.add_hline(y=0, line_color='#6b7a99', line_width=1)
                fig_sc.update_layout(
                    height=360, plot_bgcolor='#111827', paper_bgcolor='#111827',
                    font=dict(color='#c8d0e7', size=10),
                    xaxis=dict(showgrid=False, tickfont=dict(size=10)),
                    yaxis=dict(showgrid=True, gridcolor='#2a3555', zeroline=True,
                               zerolinecolor='#6b7a99', title='예상 변동폭 (%)'),
                    showlegend=False,
                    margin=dict(l=10, r=20, t=20, b=10),
                )
                st.plotly_chart(fig_sc, use_container_width=True, config={'displayModeBar': False})

            # 전체 25개 요약 테이블
            with st.expander("📊 전체 25개 시나리오 요약 보기"):
                summary_rows = []
                for name, sc_data in scenarios.items():
                    sp_r  = sc_data.get('S&P500', (0, 0))
                    btc_r = sc_data.get('BTC', (0, 0))
                    gld_r = sc_data.get('금', (0, 0))
                    tlt_r = sc_data.get('장기채(TLT)', (0, 0))
                    summary_rows.append({
                        '시나리오': name,
                        'S&P500': f"{sp_r[0]:+.0f}%~{sp_r[1]:+.0f}%",
                        'BTC': f"{btc_r[0]:+.0f}%~{btc_r[1]:+.0f}%",
                        '금(안전자산)': f"{gld_r[0]:+.0f}%~{gld_r[1]:+.0f}%",
                        '장기채': f"{tlt_r[0]:+.0f}%~{tlt_r[1]:+.0f}%",
                        '설명': sc_data.get('설명', '')[:35] + '…',
                    })
                df_sum = pd.DataFrame(summary_rows)
                st.dataframe(df_sum, use_container_width=True, hide_index=True)

    # ── Tab 2: 몬테카를로 시뮬레이션 ────────────────────────────────────────
    with risk_tabs[1]:
        st.markdown("**기하브라운운동(GBM) 기반 — 10만 개의 미래를 1초 안에 계산**")

        mc_assets_map = {
            'BTC-USD':  '₿ 비트코인',
            '^GSPC':    '📈 S&P 500',
            '^IXIC':    '💻 나스닥',
            'GC=F':     '🥇 금 선물',
            'IBIT':     '🏦 BlackRock BTC ETF',
            'QQQ':      '📊 QQQ ETF',
            'TLT':      '📉 미 장기채 ETF',
            'CL=F':     '🛢️ 원유 선물',
        }

        mc_col1, mc_col2, mc_col3 = st.columns([2, 1, 1])
        with mc_col1:
            mc_ticker = st.selectbox(
                "분석 자산", list(mc_assets_map.keys()),
                format_func=lambda x: mc_assets_map[x], key='mc_ticker'
            )
        with mc_col2:
            mc_days = st.selectbox(
                "기간", [30, 60, 90, 180, 252, 504],
                format_func=lambda x: {30:'30일(1개월)', 60:'60일(2개월)',
                                       90:'90일(3개월)', 180:'180일(6개월)',
                                       252:'252일(1년)', 504:'504일(2년)'}[x],
                index=2, key='mc_days'
            )
        with mc_col3:
            run_mc = st.button("🚀 10만 시뮬레이션 실행",
                               use_container_width=True, type="primary")

        # 실행 또는 캐시된 결과 표시
        mc_result = None
        if run_mc:
            with st.spinner(f"🔮 {mc_days}일 × 100,000경로 계산 중… (약 1~3초)"):
                mc_result = run_monte_carlo(mc_ticker, mc_days, 100_000)
            st.session_state['mc_result']  = mc_result
            st.session_state['mc_ticker_k'] = mc_ticker
            st.session_state['mc_days_k']   = mc_days
        elif 'mc_result' in st.session_state:
            mc_result  = st.session_state['mc_result']
            mc_ticker  = st.session_state.get('mc_ticker_k', mc_ticker)
            mc_days    = st.session_state.get('mc_days_k', mc_days)

        if mc_result:
            S0          = mc_result['S0']
            ticker_name = mc_assets_map.get(mc_ticker, mc_ticker)

            # ── 확률 요약 배지 6개 ────────────────────────────────────────
            p_cols = st.columns(6)
            prob_items = [
                (f"+10% 이상",  mc_result['prob_up10'],   '#00e676'),
                (f"+25% 이상",  mc_result['prob_up25'],   '#00c853'),
                (f"+50% 이상",  mc_result['prob_up50'],   '#64dd17'),
                (f"-10% 이하",  mc_result['prob_down10'], '#ff8a65'),
                (f"-25% 이하",  mc_result['prob_down25'], '#ff4e6a'),
                (f"-50% 이하",  mc_result['prob_down50'], '#d50000'),
            ]
            for col, (label, prob, color) in zip(p_cols, prob_items):
                with col:
                    st.markdown(f"""<div class="card" style="text-align:center;padding:10px 6px;">
                        <p style="font-size:0.7rem;color:#6b7a99;margin:0">{label}</p>
                        <p style="font-size:1.3rem;font-weight:700;color:{color};margin:4px 0">{prob:.1f}%</p>
                    </div>""", unsafe_allow_html=True)

            # ── 팬 차트 + 히스토그램 ─────────────────────────────────────
            fan_col, hist_col = st.columns([3, 2])

            with fan_col:
                fig_fan = go.Figure()
                paths_s = mc_result['paths_sample']
                x_ax    = list(range(mc_days))

                # 200개 샘플 경로
                for i in range(min(200, paths_s.shape[1])):
                    fig_fan.add_trace(go.Scatter(
                        x=x_ax, y=paths_s[:, i], mode='lines',
                        line=dict(width=0.3, color='rgba(59,91,219,0.12)'),
                        showlegend=False, hoverinfo='skip',
                    ))

                # 백분위 수평선
                pct_lines = [
                    (mc_result['p95'], 'P95 (상위5%)', '#00e676', 2),
                    (mc_result['p75'], 'P75',          '#69db7c', 1.5),
                    (mc_result['p50'], 'P50 중앙값',   '#ffb300', 2.5),
                    (mc_result['p25'], 'P25',          '#ff8a65', 1.5),
                    (mc_result['p5'],  'P5 (하위5%)',  '#ff4e6a', 2),
                ]
                for pval, plabel, pcolor, pw in pct_lines:
                    fig_fan.add_hline(
                        y=pval, line_color=pcolor, line_width=pw,
                        annotation_text=f"{plabel}: ${pval:,.0f}",
                        annotation_position="right",
                        annotation_font=dict(color=pcolor, size=9),
                    )

                fig_fan.add_hline(
                    y=S0, line_color='#ffffff', line_dash='dash', line_width=1.5,
                    annotation_text=f"현재: ${S0:,.0f}",
                    annotation_position="left",
                    annotation_font=dict(color='#ffffff', size=9),
                )
                fig_fan.update_layout(
                    title=dict(text=f"{ticker_name} — {mc_days}일 경로 (200샘플 / 전체 10만)",
                               font=dict(size=11, color='#c8d0e7')),
                    height=330, plot_bgcolor='#111827', paper_bgcolor='#111827',
                    font=dict(color='#c8d0e7'),
                    xaxis=dict(showgrid=False, title='거래일', tickfont=dict(size=9)),
                    yaxis=dict(showgrid=True, gridcolor='#2a3555',
                               title='가격 (USD)', tickfont=dict(size=9)),
                    margin=dict(l=10, r=90, t=40, b=30),
                    showlegend=False,
                )
                st.plotly_chart(fig_fan, use_container_width=True, config={'displayModeBar': False})

            with hist_col:
                final_arr = mc_result['final']
                # 히스토그램용 5000개 샘플
                idx_s  = np.random.choice(len(final_arr), min(5000, len(final_arr)), replace=False)
                f_samp = final_arr[idx_s]

                fig_hist = go.Figure()
                fig_hist.add_trace(go.Histogram(
                    x=f_samp, nbinsx=60,
                    marker_color='#3b5bdb', marker_opacity=0.8, name='분포'
                ))
                for pval, plabel, pcolor in [
                    (mc_result['p5'],  'P5',  '#ff4e6a'),
                    (mc_result['p50'], 'P50', '#ffb300'),
                    (mc_result['p95'], 'P95', '#00e676'),
                ]:
                    fig_hist.add_vline(
                        x=pval, line_color=pcolor, line_width=1.5,
                        annotation_text=plabel,
                        annotation_font=dict(color=pcolor, size=9),
                    )
                fig_hist.add_vline(
                    x=S0, line_color='white', line_dash='dash', line_width=1.5,
                    annotation_text="현재",
                    annotation_font=dict(color='white', size=9),
                )
                fig_hist.update_layout(
                    title=dict(text=f"{mc_days}일 후 최종 가격 분포",
                               font=dict(size=11, color='#c8d0e7')),
                    height=330, plot_bgcolor='#111827', paper_bgcolor='#111827',
                    font=dict(color='#c8d0e7'),
                    xaxis=dict(showgrid=False, title='최종 가격', tickfont=dict(size=9)),
                    yaxis=dict(showgrid=True, gridcolor='#2a3555', title='빈도', tickfont=dict(size=9)),
                    margin=dict(l=10, r=10, t=40, b=30),
                    showlegend=False, bargap=0.05,
                )
                st.plotly_chart(fig_hist, use_container_width=True, config={'displayModeBar': False})

            # ── 백분위 통계 카드 ─────────────────────────────────────────
            st.markdown(f"""<div class="card">
                <p style="font-weight:700;color:#c8d0e7;margin-bottom:8px">
                    📊 {mc_days}일 후 {ticker_name} 가격 예측 분포 &nbsp;|&nbsp;
                    현재: <span style="color:#ffb300">${S0:,.2f}</span>
                </p>
                <div style="display:flex;gap:12px;flex-wrap:wrap;text-align:center;">
                    <div style="flex:1;min-width:80px">
                        <p class="label">P5 (최악 5%)</p>
                        <p style="color:#ff4e6a;font-weight:700;margin:2px 0">${mc_result['p5']:,.0f}</p>
                        <p class="label">({(mc_result['p5']/S0-1)*100:+.1f}%)</p>
                    </div>
                    <div style="flex:1;min-width:80px">
                        <p class="label">P25</p>
                        <p style="color:#ff8a65;font-weight:700;margin:2px 0">${mc_result['p25']:,.0f}</p>
                        <p class="label">({(mc_result['p25']/S0-1)*100:+.1f}%)</p>
                    </div>
                    <div style="flex:1;min-width:80px">
                        <p class="label">P50 (중앙값)</p>
                        <p style="color:#ffb300;font-weight:700;margin:2px 0">${mc_result['p50']:,.0f}</p>
                        <p class="label">({(mc_result['p50']/S0-1)*100:+.1f}%)</p>
                    </div>
                    <div style="flex:1;min-width:80px">
                        <p class="label">P75</p>
                        <p style="color:#69db7c;font-weight:700;margin:2px 0">${mc_result['p75']:,.0f}</p>
                        <p class="label">({(mc_result['p75']/S0-1)*100:+.1f}%)</p>
                    </div>
                    <div style="flex:1;min-width:80px">
                        <p class="label">P95 (최선 5%)</p>
                        <p style="color:#00e676;font-weight:700;margin:2px 0">${mc_result['p95']:,.0f}</p>
                        <p class="label">({(mc_result['p95']/S0-1)*100:+.1f}%)</p>
                    </div>
                </div>
                <hr style="border-color:#2a3555;margin:8px 0">
                <p style="font-size:0.78rem;color:#6b7a99">
                    💡 추정 모수 — 일간 수익률: μ={mc_result['mu']*100:.4f}%, σ={mc_result['sigma']*100:.3f}%
                    &nbsp;|&nbsp; 연환산 변동성(σ×√252): {mc_result['sigma']*100*(252**0.5):.1f}%
                    &nbsp;|&nbsp; GBM: S(t) = S₀·exp((μ-σ²/2)t + σ√t·Z)
                </p>
            </div>""", unsafe_allow_html=True)

        else:
            st.markdown("""<div class="card" style="text-align:center;padding:48px 20px;">
                <p style="font-size:2.5rem;margin:0">🔮</p>
                <p style="color:#9aa5c0;font-size:1rem;margin:12px 0">
                    자산과 기간을 선택 후 <strong style="color:#fff">🚀 10만 시뮬레이션 실행</strong> 버튼을 클릭하세요</p>
                <p style="font-size:0.8rem;color:#6b7a99;margin:0">
                    GBM(기하브라운운동) | 1년치 실제 데이터로 μ·σ 추정 | numpy 벡터화 — 10만 경로 ≈ 1초</p>
            </div>""", unsafe_allow_html=True)

    # ── 푸터 ──────────────────────────────────────────────────────────────────
    st.markdown("---")
    st.caption("🔮 알라딘 v2.0 | 데이터: Yahoo Finance · CoinGecko · Alternative.me · Bloomberg RSS · Reuters RSS | 자산 1천억 프로젝트")


if __name__ == '__main__':
    main()
