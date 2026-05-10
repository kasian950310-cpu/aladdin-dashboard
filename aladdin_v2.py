"""
🔮 알라딘 v2.0 — 전세계 돈의 흐름 대시보드
자산 1천억 프로젝트 | 글로벌 기관 자금 흐름 추적

실행: python3 -m streamlit run aladdin_v2.py
"""

import os, json, requests, feedparser
import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
import pandas as pd
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
@st.cache_data(ttl=300)
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


@st.cache_data(ttl=300)
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
        st.caption(f"글로벌 기관 자금 추적 대시보드 | {now.strftime('%Y-%m-%d %H:%M:%S')} | 5분 자동 갱신")
    with c2:
        if st.button("🔄 새로고침", use_container_width=True):
            st.cache_data.clear(); st.rerun()

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

    # ── 푸터 ──────────────────────────────────────────────────────────────────
    st.markdown("---")
    st.caption("🔮 알라딘 v2.0 | 데이터: Yahoo Finance · CoinGecko · Alternative.me · Bloomberg RSS · Reuters RSS | 자산 1천억 프로젝트")


if __name__ == '__main__':
    main()
