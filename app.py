"""
流動性枯渇予兆ダッシュボード - Streamlit版
neco v1  /  https://note.com/mofuneco
"""

import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta

# ============================================================
# ページ設定
# ============================================================
st.set_page_config(
    page_title="流動性枯渇予兆ダッシュボード",
    page_icon="⚠️",
    layout="wide",
)

# ============================================================
# 設定
# ============================================================
LOOKBACK_DAYS = 1825  # 5年

THRESHOLDS = {
    "rrp_warning":     500,    # Billions USD
    "rrp_danger":      100,
    "sofr_iorb_warn":  0.10,
    "sofr_iorb_alert": 0.20,
    "bbb_warn":        2.0,
    "bbb_alert":       3.0,
    "hy_warn":         4.0,
    "hy_alert":        6.0,
    "reserves_warn":   2.5,    # 兆ドル
    "reserves_danger": 2.0,
    "tga_warn":        200,    # Billions USD
    "tga_danger":      100,
    "vix_warn":        20,
    "vix_alert":       25,
}

COLORS = {
    "green":  "#3fb950",
    "yellow": "#d29922",
    "orange": "#ffa657",
    "red":    "#f85149",
    "blue":   "#58a6ff",
    "teal":   "#39d353",
    "purple": "#bc8cff",
    "bg":     "#0d1117",
    "panel":  "#161b22",
}

# ============================================================
# データ取得
# ============================================================
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

@st.cache_data(ttl=3600)  # 1時間キャッシュ
def fetch_fred(series_id, api_key):
    start = (datetime.today() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    try:
        r = requests.get(FRED_BASE, params={
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "observation_start": start,
            "sort_order": "asc",
        }, timeout=15)
        r.raise_for_status()
        obs = r.json().get("observations", [])
        df = pd.DataFrame(obs)
        df = df[df["value"] != "."]
        df["date"] = pd.to_datetime(df["date"])
        df["value"] = df["value"].astype(float)
        return df.set_index("date")["value"]
    except Exception as e:
        st.warning(f"FRED取得エラー [{series_id}]: {e}")
        return pd.Series(dtype=float)

@st.cache_data(ttl=3600)
def fetch_cftc():
    url = "https://publicreporting.cftc.gov/resource/jun7-fc8e.json"
    start = (datetime.today() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%dT00:00:00.000")
    try:
        r = requests.get(url, params={
            "market_and_exchange_names": "JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE",
            "$limit": 200,
            "$order": "report_date_as_yyyy_mm_dd DESC",
            "$where": f"report_date_as_yyyy_mm_dd >= '{start}'",
        }, timeout=15)
        r.raise_for_status()
        data = r.json()
        if not data:
            return pd.Series(dtype=float)
        df = pd.DataFrame(data)
        df["date"] = pd.to_datetime(df["report_date_as_yyyy_mm_dd"])
        df["net"] = df["noncomm_positions_long_all"].astype(float) - df["noncomm_positions_short_all"].astype(float)
        return df.sort_values("date").set_index("date")["net"]
    except Exception as e:
        return pd.Series(dtype=float)

@st.cache_data(ttl=3600)
def fetch_all(api_key):
    sofr     = fetch_fred("SOFR",          api_key)
    iorb     = fetch_fred("IORB",          api_key)
    rrp      = fetch_fred("RRPONTSYD",     api_key)
    bbb      = fetch_fred("BAMLC0A4CBBB",  api_key)
    oas_hy   = fetch_fred("BAMLH0A0HYM2",  api_key)
    reserves = fetch_fred("WRESBAL",       api_key)
    tga      = fetch_fred("WTREGEN",       api_key)
    usdjpy   = fetch_fred("DEXJPUS",       api_key)
    vix      = fetch_fred("VIXCLS",        api_key)
    jpy_cot  = fetch_cftc()

    sofr_iorb = pd.Series(dtype=float)
    if not sofr.empty and not iorb.empty:
        c = pd.concat([sofr, iorb], axis=1).dropna()
        c.columns = ["sofr", "iorb"]
        sofr_iorb = c["sofr"] - c["iorb"]

    carry_risk = pd.Series(dtype=float)
    if not usdjpy.empty and not vix.empty:
        c = pd.concat([usdjpy, vix], axis=1).dropna()
        c.columns = ["usdjpy", "vix"]
        uz = (c["usdjpy"] - c["usdjpy"].mean()) / c["usdjpy"].std()
        vz = (c["vix"]    - c["vix"].mean())    / c["vix"].std()
        carry_risk = (-uz + vz)

    return {
        "sofr": sofr, "iorb": iorb, "rrp": rrp,
        "sofr_iorb": sofr_iorb,
        "bbb": bbb, "oas_hy": oas_hy,
        "reserves": reserves, "tga": tga,
        "usdjpy": usdjpy, "vix": vix,
        "jpy_cot": jpy_cot, "carry_risk": carry_risk,
    }

# ============================================================
# アラート判定
# ============================================================
def get_alert(data):
    score = 0
    reasons = []
    t = THRESHOLDS

    def check(series, key_danger, key_warn, label_d, label_w):
        nonlocal score
        if series.empty: return
        v = series.iloc[-1]
        if v < t[key_danger]:   score += 2; reasons.append(f"🔴 {label_d}")
        elif v < t[key_warn]:   score += 1; reasons.append(f"🟡 {label_w}")

    def check_high(series, key_alert, key_warn, label_a, label_w):
        nonlocal score
        if series.empty: return
        v = series.iloc[-1]
        if v > t[key_alert]:   score += 2; reasons.append(f"🔴 {label_a}")
        elif v > t[key_warn]:  score += 1; reasons.append(f"🟡 {label_w}")

    check(data["rrp"],      "rrp_danger",      "rrp_warning",    f"RRP {data['rrp'].iloc[-1]:.2f}B (危険)", f"RRP {data['rrp'].iloc[-1]:.2f}B (注意)")
    check_high(data["sofr_iorb"], "sofr_iorb_alert", "sofr_iorb_warn", "SOFR-IORB 急拡大 (危険)", "SOFR-IORB 拡大中 (注意)")
    check_high(data["bbb"],       "bbb_alert",        "bbb_warn",       "BBBスプレッド 3%超 (危険)", "BBBスプレッド 拡大 (注意)")
    check_high(data["oas_hy"],    "hy_alert",         "hy_warn",        "HYスプレッド 6%超 (危険)", "HYスプレッド 4%超 (注意)")
    check_high(data["vix"],       "vix_alert",        "vix_warn",       "VIX 25超 (警戒)", "VIX 20超 (注意)")

    if not data["reserves"].empty:
        v = data["reserves"].iloc[-1] / 1e6  # 百万→兆
        if v < t["reserves_danger"]: score += 2; reasons.append(f"🔴 準備預金 {v:.1f}T (危険)")
        elif v < t["reserves_warn"]: score += 1; reasons.append(f"🟡 準備預金 {v:.1f}T (注意)")

    level = min(score // 2, 3)
    return level, reasons

# ============================================================
# チャート生成
# ============================================================
def make_chart(s, title, yaxis_title, color, hlines=None, bar=False, zero_line=False):
    fig = go.Figure()
    if s.empty:
        fig.add_annotation(text="データなし", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
    else:
        if bar:
            colors = [COLORS["red"] if v < 0 else color for v in s]
            fig.add_trace(go.Bar(x=s.index, y=s.values, marker_color=colors, name=title))
        else:
            fig.add_trace(go.Scatter(x=s.index, y=s.values, mode="lines",
                                     line=dict(color=color, width=1.5),
                                     fill="tozeroy", fillcolor=color.replace(")", ",0.15)").replace("rgb", "rgba") if "rgb" in color else color + "26",
                                     name=title))
        if hlines:
            for y, c, label in hlines:
                fig.add_hline(y=y, line_color=c, line_dash="dash", line_width=1,
                              annotation_text=label, annotation_font_color=c)
        if zero_line:
            fig.add_hline(y=0, line_color="#555", line_width=1)

    fig.update_layout(
        title=dict(text=title, font=dict(size=12)),
        yaxis_title=yaxis_title,
        height=280,
        margin=dict(l=50, r=20, t=40, b=30),
        paper_bgcolor=COLORS["bg"],
        plot_bgcolor=COLORS["panel"],
        font=dict(color="#e6edf3"),
        showlegend=False,
        xaxis=dict(gridcolor="#21262d"),
        yaxis=dict(gridcolor="#21262d"),
    )
    return fig

# ============================================================
# メイン UI
# ============================================================
def main():
    # サイドバー：APIキー入力
    with st.sidebar:
        st.title("⚙️ 設定")
        api_key = st.text_input("FRED API キー", type="password",
                                help="https://fred.stlouisfed.org/docs/api/api_key.html")
        st.markdown("---")
        st.markdown("**データ更新**: 1時間キャッシュ")
        if st.button("🔄 今すぐ更新"):
            st.cache_data.clear()
            st.rerun()
        st.markdown("---")
        st.markdown("**作成**: [neco3](https://note.com/mofuneco)")

    # APIキー未設定
    if not api_key:
        st.title("流動性枯渇予兆ダッシュボード")
        st.info("👈 サイドバーにFRED APIキーを入力してください\n\n取得（無料）: https://fred.stlouisfed.org/docs/api/api_key.html")
        return

    # データ取得
    with st.spinner("データ取得中..."):
        data = fetch_all(api_key)

    # アラートレベル
    level, reasons = get_alert(data)
    alert_labels = ["🟢 平常", "🟡 注意", "🟠 警戒", "🔴 危機前夜"]
    alert_colors = ["#3fb950", "#d29922", "#ffa657", "#f85149"]
    alert_label  = alert_labels[level]
    alert_color  = alert_colors[level]

    # ヘッダー
    now = datetime.now().strftime("%Y/%m/%d %H:%M")
    st.markdown(f"""
    <h1 style='text-align:center; color:{alert_color};'>
        流動性枯渇予兆ダッシュボード
    </h1>
    <h3 style='text-align:center; color:#8b949e;'>
        {now} 更新　｜　総合アラート: {alert_label}
    </h3>
    """, unsafe_allow_html=True)

    # アラート理由
    if reasons:
        with st.expander("⚠️ アラート詳細", expanded=(level >= 2)):
            for r in reasons:
                st.markdown(f"- {r}")
    else:
        st.success("✓ 現時点でアラート条件なし")

    st.markdown("---")

    # ============================================================
    # 現在値サマリーカード
    # ============================================================
    def last_val(s, div=1, fmt="{:.2f}"):
        if s.empty: return "N/A"
        return fmt.format(s.iloc[-1] / div)

    cols = st.columns(4)
    metrics = [
        ("RRP残高",       last_val(data["rrp"],      1,    "{:.3f}B$"), "ほぼゼロ = 危険"),
        ("SOFR-IORB",     last_val(data["sofr_iorb"],1,    "{:.3f}%"),  "マイナス = 緩和"),
        ("BBBスプレッド", last_val(data["bbb"],       1,    "{:.2f}%"),  "2%超 = 注意"),
        ("HYスプレッド",  last_val(data["oas_hy"],    1,    "{:.2f}%"),  "4%超 = 注意"),
        ("準備預金",      last_val(data["reserves"],  1e6,  "{:.2f}T$"), "2T割れ = 危険"),
        ("TGA残高",       last_val(data["tga"],       1e3,  "{:.0f}B$"), "100B割れ = 危険"),
        ("ドル円",        last_val(data["usdjpy"],    1,    "{:.1f}"),   "155超 = 円安警戒"),
        ("VIX",           last_val(data["vix"],       1,    "{:.1f}"),   "25超 = 警戒"),
    ]
    for i, (label, val, hint) in enumerate(metrics):
        cols[i % 4].metric(label=label, value=val, help=hint)

    st.markdown("---")

    # ============================================================
    # チャート
    # ============================================================
    t = THRESHOLDS
    col1, col2 = st.columns(2)

    with col1:
        st.plotly_chart(make_chart(
            data["rrp"], "① RRP残高  流動性バッファ（ピーク2.5兆→現在ほぼゼロ）", "十億ドル",
            COLORS["blue"],
            hlines=[(t["rrp_warning"], COLORS["yellow"], "注意:500B"),
                    (t["rrp_danger"],  COLORS["red"],    "危険:100B")]
        ), use_container_width=True)

    with col2:
        st.plotly_chart(make_chart(
            data["sofr_iorb"], "② SOFR-IORBスプレッド  レポ逼迫の直接指標", "%",
            COLORS["blue"], bar=True, zero_line=True,
            hlines=[(t["sofr_iorb_warn"],  COLORS["yellow"], "注意:+10bp"),
                    (t["sofr_iorb_alert"], COLORS["red"],    "警戒:+20bp")]
        ), use_container_width=True)

    with col1:
        st.plotly_chart(make_chart(
            data["bbb"], "③ BBB社債スプレッド  信用ひび割れの初期シグナル", "%",
            COLORS["orange"],
            hlines=[(t["bbb_warn"],  COLORS["yellow"], "注意:2%"),
                    (t["bbb_alert"], COLORS["red"],    "警戒:3%")]
        ), use_container_width=True)

    with col2:
        st.plotly_chart(make_chart(
            data["oas_hy"], "④ HYスプレッド  クレジットストレス先行指標", "%",
            COLORS["red"],
            hlines=[(t["hy_warn"],  COLORS["yellow"], "注意:4%"),
                    (t["hy_alert"], COLORS["red"],    "警戒:6%")]
        ), use_container_width=True)

    with col1:
        reserves_t = data["reserves"] / 1e6 if not data["reserves"].empty else data["reserves"]
        st.plotly_chart(make_chart(
            reserves_t, "⑤ 銀行準備預金残高  2019レポショックの震源", "兆ドル",
            COLORS["teal"],
            hlines=[(t["reserves_warn"],   COLORS["yellow"], "注意:2.5T"),
                    (t["reserves_danger"],  COLORS["red"],    "危険:2.0T")]
        ), use_container_width=True)

    with col2:
        tga_b = data["tga"] / 1e3 if not data["tga"].empty else data["tga"]
        st.plotly_chart(make_chart(
            tga_b, "⑥ TGA残高  枯渇→流動性注入 / 補充→吸収", "十億ドル",
            COLORS["purple"],
            hlines=[(t["tga_warn"],   COLORS["yellow"], "注意:200B"),
                    (t["tga_danger"],  COLORS["red"],    "危険:100B")]
        ), use_container_width=True)

    with col1:
        st.plotly_chart(make_chart(
            data["usdjpy"], "⑦ ドル円", "円/ドル",
            COLORS["blue"],
            hlines=[(130, COLORS["green"],  "130円(円高圏)"),
                    (155, COLORS["yellow"], "155円(円安警戒)")]
        ), use_container_width=True)

    with col2:
        st.plotly_chart(make_chart(
            data["vix"], "⑧ VIX（恐怖指数）", "VIX",
            COLORS["blue"],
            hlines=[(t["vix_warn"],  COLORS["yellow"], "注意:20"),
                    (t["vix_alert"], COLORS["red"],    "警戒:25")]
        ), use_container_width=True)

    with col1:
        st.plotly_chart(make_chart(
            data["jpy_cot"], "⑨ 円先物COT  投機筋ネット（マイナス=円ショート）", "枚",
            COLORS["green"], bar=True, zero_line=True,
        ), use_container_width=True)

    with col2:
        st.plotly_chart(make_chart(
            data["carry_risk"], "⑩ 円キャリー逆流リスク（ドル円↓×VIX↑ 合成Z）", "Zスコア",
            COLORS["blue"], zero_line=True,
            hlines=[(1.0, COLORS["yellow"], "注意:Z=1"),
                    (2.0, COLORS["red"],    "警戒:Z=2")]
        ), use_container_width=True)

    st.markdown("---")
    st.caption("データ: FRED（セントルイス連銀）/ CFTC　｜　投資は自己責任でお願いします")

if __name__ == "__main__":
    main()
