import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz
import os
import requests # 新增：為了清空 yfinance 快取

# ==========================================
# 🎯 1. 中央控制面板
# ==========================================
MY_PORTFOLIO = {
    "TSM": {"entry_date": "2025-04-18", "entry_price": 163.33},
    "GOOGL": {"entry_date": "2026-06-12", "entry_price": 362.190},
}

TICKERS = [
     "QLD","AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "BRK-B", "LLY", "AVGO", "TSLA",
    "JPM", "WMT", "UNH", "V", "XOM", "MA", "PG", "JNJ", "COST", "HD",
    "ORCL", "MRK", "ABBV", "CVX", "CRM", "BAC", "KO", "NFLX", "PEP", "AMD",
    "LIN", "TMO", "WFC", "DIS", "CSCO", "MCD", "INTU", "QCOM", "AMAT", "IBM",
    "TXN", "NOW", "UBER", "GE", "CAT", "AXP", "ISRG", "PM", "GS", "BA"
]

STRATEGY_PARAMS = {
    'VIX_THRESHOLD': 30, 
    'BREADTH_THRESHOLD': 0.60, 
    'INIT_STOP_MULT': 1.5, 
    'TRAIL_STOP_MULT': 2.5, 
    'V6_KD_MAX': 60, 
    'V5_OVERSOLD_PCT': 0.7, 
    'V5_KD_MAX': 25 
}

# ==========================================
# ⚙️ 2. 底層引擎區 
# ==========================================
BREADTH_TICKERS = TICKERS.copy()
MARKET_TICKERS = ["SPY", "^VIX"] 
PERIOD = "2y"
DAYS_TO_SHOW = 5

# --- [強化點 1] 確保取得台灣現在時間，方便除錯 ---
tw_tz = pytz.timezone('Asia/Taipei')
current_tw_time = datetime.now(tw_tz).strftime('%Y-%m-%d %H:%M:%S')

def calculate_indicators(df):
    low_min = df['Low'].rolling(window=14).min()
    high_max = df['High'].rolling(window=14).max()
    df['K'] = (((df['Close'] - low_min) / (high_max - low_min)) * 100).rolling(window=3).mean()
    df['D'] = df['K'].rolling(window=3).mean()
    df['EMA_20'] = df['Close'].ewm(span=20, adjust=False).mean()
    df['MA_50'] = df['Close'].rolling(window=50).mean()
    df['MA_200'] = df['Close'].rolling(window=200).mean()
    
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(window=14).mean()
    return df

def track_my_holdings(df, symbol, entry_date, entry_price):
    held_df = df[df.index >= pd.to_datetime(entry_date)]
    if held_df.empty: return None
    
    highest_close = held_df['Close'].max()
    current_close = held_df['Close'].iloc[-1]
    current_atr = held_df['ATR'].iloc[-1] if not pd.isna(held_df['ATR'].iloc[-1]) else (current_close * 0.02)
    
    trailing_stop = highest_close - (STRATEGY_PARAMS['TRAIL_STOP_MULT'] * current_atr)
    profit_pct = ((current_close - entry_price) / entry_price) * 100
    
    status = "✅ 安全持股中"
    if current_close < trailing_stop:
        status = "🚨 已破防守線，建議賣出！"
        
    return {
        '股票': symbol, 
        '進場日': entry_date, 
        '成本': entry_price,
        '現價': round(current_close, 2), 
        '目前ATR': round(current_atr, 2),  
        '帳上損益(%)': round(profit_pct, 2),
        '創高價': round(highest_close, 2), 
        '目前防守線': round(trailing_stop, 2),
        '狀態': status
    }

print(f"🚀 啟動 V7 ({current_tw_time} 台灣時間) 讀取數據中...")

# --- [強化點 2] 強制建立全新的 yfinance Session 避免抓到舊快取 ---
# 增加 User-Agent 偽裝成真人瀏覽器，避免被 Yahoo Finance 阻擋 (解決「資料源異常」的核心)
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
})

data_dict = {}
env_dict = {}

# 抓取大盤資料並檢查
for symbol in MARKET_TICKERS:
    try:
        # 加入 session 強制重新請求
        df = yf.download(symbol, period=PERIOD, progress=False, session=session)
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        if symbol == "SPY" and not df.empty:
            df['MA_200'] = df['Close'].rolling(window=200).mean()
        env_dict[symbol] = df
    except Exception as e:
        print(f"⚠️ 無法抓取大盤 {symbol} 資料: {e}")

all_tickers_to_fetch = list(set(TICKERS + list(MY_PORTFOLIO.keys()) + BREADTH_TICKERS))
for symbol in all_tickers_to_fetch:
    try:
        df = yf.download(symbol, period=PERIOD, progress=False, session=session)
        if df.empty: 
            print(f"⚠️ {symbol} 回傳空資料")
            continue
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df = calculate_indicators(df)
        data_dict[symbol] = df
    except Exception as e:
        print(f"⚠️ 無法抓取個股 {symbol} 資料: {e}")
        pass

# --- [強化點 3] 確保取得最新日期邏輯更穩固 ---
latest_date = None
# 優先以 SPY (大盤) 的最後一天為主，如果沒有才找個股
if "SPY" in env_dict and not env_dict["SPY"].empty:
    latest_date = env_dict["SPY"].index[-1]
else:
    for sym in TICKERS:
        if sym in data_dict and not data_dict[sym].empty:
            latest_date = data_dict[sym].index[-1]
            break

if latest_date is None:
    print("❌ 嚴重錯誤：完全無法取得任何交易數據。")
    # 給予一個假日期讓 HTML 可以產出並顯示錯誤
    latest_date_str = "無法取得日期 (資料源異常)"
else:
    latest_date_str = latest_date.strftime('%Y-%m-%d')


# 預設大盤環境變數 (防呆機制)
is_spy_uptrend = False
is_vix_calm = False
spy_close = 0
vix_close = 0

if "SPY" in env_dict and not env_dict["SPY"].empty:
    spy_latest = env_dict["SPY"].iloc[-1]
    spy_close = spy_latest['Close']
    is_spy_uptrend = spy_latest['Close'] > spy_latest['MA_200']

if "^VIX" in env_dict and not env_dict["^VIX"].empty:
    vix_latest = env_dict["^VIX"].iloc[-1]
    vix_close = vix_latest['Close']
    is_vix_calm = vix_latest['Close'] < STRATEGY_PARAMS['VIX_THRESHOLD']

stocks_above_50ma = 0
valid_breadth_stocks = 0
for sym in BREADTH_TICKERS:
    if sym in data_dict and not data_dict[sym].empty:
        latest_row = data_dict[sym].iloc[-1]
        if not pd.isna(latest_row['MA_50']):
            valid_breadth_stocks += 1
            if latest_row['Close'] > latest_row['MA_50']:
                stocks_above_50ma += 1

breadth_pct = (stocks_above_50ma / valid_breadth_stocks) if valid_breadth_stocks > 0 else 0
is_breadth_healthy = breadth_pct >= STRATEGY_PARAMS['BREADTH_THRESHOLD']

if is_spy_uptrend and is_vix_calm and is_breadth_healthy:
    current_regime = "V6 (順勢動能)"
    regime_desc = "🌞 健康多頭期：水溫溫暖，適合尋找強勢股回檔突破"
else:
    current_regime = "V5 (恐慌抄底)"
    regime_desc = "⛈️ 震盪防禦期：大盤轉弱或外強中乾，只買極度超賣的龍頭"

cutoff_date = datetime.now() - timedelta(days=DAYS_TO_SHOW)
new_opportunities = []
my_portfolio_status = []

for symbol, my_data in MY_PORTFOLIO.items():
    if symbol in data_dict:
        status = track_my_holdings(data_dict[symbol], symbol, my_data['entry_date'], my_data['entry_price'])
        if status: my_portfolio_status.append(status)

for symbol in TICKERS:
    if symbol not in data_dict: continue
    df = data_dict[symbol]
    recent_df = df[df.index >= pd.to_datetime(cutoff_date)]
    if recent_df.empty: continue
    
    for i in range(1, len(recent_df)):
        row = recent_df.iloc[i]
        prev_row = df.loc[recent_df.index[i-1]]
        
        buy_signal = False
        signal_type = ""
        
        if current_regime == "V6 (順勢動能)":
            is_strong_uptrend = (row['MA_50'] > row['MA_200']) and (row['Close'] > row['MA_200'])
            is_kd_turning_up = (prev_row['K'] < prev_row['D']) and (row['K'] > row['D']) and (row['K'] < STRATEGY_PARAMS['V6_KD_MAX'])
            is_breakout_20ema = (prev_row['Close'] <= prev_row['EMA_20']) and (row['Close'] > row['EMA_20'])
            if is_strong_uptrend and is_kd_turning_up and is_breakout_20ema:
                buy_signal = True
                signal_type = "V6 強勢拉回表態"
        else:
            is_deep_oversold = row['Close'] < (row['MA_200'] * STRATEGY_PARAMS['V5_OVERSOLD_PCT']) 
            is_uptrend = row['Close'] > row['MA_200']
            is_kd_golden_cross = (prev_row['K'] < prev_row['D']) and (row['K'] > row['D']) and (row['K'] < STRATEGY_PARAMS['V5_KD_MAX'])
            
            if (is_uptrend or is_deep_oversold) and is_kd_golden_cross:
                buy_signal = True
                signal_type = "V5 極度超賣抄底"
                
        if buy_signal:
            atr_val = row['ATR'] if not pd.isna(row['ATR']) else (row['Close'] * 0.02)
            suggested_stop = row['Close'] - (STRATEGY_PARAMS['INIT_STOP_MULT'] * atr_val)
            new_opportunities.append({
                '股票': symbol, 
                '訊號日': recent_df.index[i].strftime('%Y-%m-%d'),
                '策略': signal_type, 
                '現價': round(row['Close'], 2), 
                '當前ATR': round(atr_val, 2),
                '建議防守線': round(suggested_stop, 2)
            })

# ==========================================
# 🌐 自動生成高質感 HTML 交易儀表板
# ==========================================
print("📸 正在為您生成專屬交易儀表板...")

if my_portfolio_status:
    df_my = pd.DataFrame(my_portfolio_status)
    portfolio_html = df_my[['股票', '進場日', '成本', '現價', '目前ATR', '帳上損益(%)', '目前防守線', '狀態']].to_html(index=False, border=0, classes='styled-table')
    portfolio_html = portfolio_html.replace('✅ 安全持股中', '<span class="good">✅ 安全持股中</span>')
    portfolio_html = portfolio_html.replace('🚨 已破防守線，建議賣出！', '<span class="bad">🚨 已破防守線，建議賣出！</span>')
else:
    portfolio_html = "<p style='color: #888; text-align: center;'>目前 MY_PORTFOLIO 中沒有設定持股。</p>"

if new_opportunities:
    df_new = pd.DataFrame(new_opportunities).drop_duplicates(subset=['股票', '策略', '訊號日'], keep='last')
    # 按照訊號日反向排序，最新的排在最前面
    df_new = df_new.sort_values(by='訊號日', ascending=False)
    radar_html = df_new[['股票', '訊號日', '策略', '現價', '當前ATR', '建議防守線']].to_html(index=False, border=0, classes='styled-table')
else:
    radar_html = "<p style='color: #888; text-align: center;'>近期無符合條件的進場標的，請保留現金耐心等待。</p>"

spy_display = f"<span class='good'>🟢 站上200MA</span>" if is_spy_uptrend else f"<span class='bad'>🔴 跌破200MA</span>"
vix_display = f"<span class='good'>🟢 平靜</span>" if is_vix_calm else f"<span class='bad'>🔴 恐慌</span>"
breadth_display = f"<span class='good'>🟢 健康</span>" if is_breadth_healthy else f"<span class='bad'>🔴 外強中乾</span>"

html_template = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>V7 雙劍合璧資產管家</title>
    <style>
        body {{
            background-color: #0d1117;
            color: #c9d1d9;
            font-family: 'Consolas', 'Courier New', monospace, 'Microsoft JhengHei';
            padding: 20px;
            max-width: 1000px;
            margin: 0 auto;
        }}
        .update-time {{
            text-align: center;
            color: #8b949e;
            font-size: 0.9em;
            margin-top: -10px;
            margin-bottom: 20px;
        }}
        h1 {{ color: #58a6ff; text-align: center; border-bottom: 2px dashed #30363d; padding-bottom: 15px; }}
        h2 {{ color: #79c0ff; margin-top: 40px; font-size: 1.2em; }}
        .panel {{
            background-color: #161b22;
            border: 1px solid #30363d;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 4px 8px rgba(0,0,0,0.2);
        }}
        .good {{ color: #3fb950; font-weight: bold; }}
        .bad {{ color: #f85149; font-weight: bold; }}
        .highlight {{ color: #d2a8ff; font-weight: bold; }}
        
        .styled-table {{ width: 100%; border-collapse: collapse; font-size: 1em; text-align: center; }}
        .styled-table thead tr {{ background-color: #21262d; color: #8b949e; border-bottom: 2px solid #30363d; }}
        .styled-table th, .styled-table td {{ padding: 12px 15px; }}
        .styled-table tbody tr {{ border-bottom: 1px solid #21262d; }}
        .styled-table tbody tr:hover {{ background-color: #1c2128; }}
        
        /* 增加手機版適應性 */
        @media (max-width: 768px) {{
            body {{ padding: 10px; }}
            .styled-table {{ font-size: 0.85em; }}
            .styled-table th, .styled-table td {{ padding: 8px 5px; }}
        }}
    </style>
</head>
<body>
    <h1>🚀 V7 雙劍合璧資產管家 ({latest_date_str})</h1>
    <!-- 新增：網頁的更新時間標示，確保我們知道這是最新執行的結果 -->
    <div class="update-time">系統最後執行時間 (台灣)：{current_tw_time}</div>
    
    <div class="panel">
        <h2>🌍 【今日大環境測候站】</h2>
        <p>📊 標普500 (SPY)： {spy_display} (現價: {round(spy_close, 2)})</p>
        <p>😨 恐慌指數 (VIX)： {vix_display} (現價: {round(vix_close, 2)})</p>
        <p>📈 大盤寬度 (站上50MA比例)： {breadth_display} ({int(breadth_pct*100)}%)</p>
        <hr style="border-color: #30363d;">
        <p>🤖 系統判定今日採用策略： <span class="highlight">{current_regime}</span></p>
        <p>💡 說明：{regime_desc}</p>
    </div>
    <div class="panel">
        <h2>🛡️ 【我的真實持股追蹤】</h2>
        {portfolio_html}
    </div>
    <div class="panel">
        <h2>🎯 【市場最新進場雷達】 (近 {DAYS_TO_SHOW} 天內觸發)</h2>
        {radar_html}
    </div>
</body>
</html>
"""

# 將檔案存為 index.html，解決需輸入檔名的問題
file_path = os.path.abspath('index.html')
with open(file_path, 'w', encoding='utf-8') as f:
    f.write(html_template)

print(f"✅ 儀表板已生成完成！(存檔為 index.html)")
