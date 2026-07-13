import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import webbrowser
import os
import pathlib

# ==========================================
# 🎯 1. 中央控制面板 (你每天只需要更新這裡！)
# ==========================================

# --- A. 我的真實持股區 ---
# 買進後請將股票代碼、進場日、成本價填入此處，系統會自動幫你計算每日移動防守線
MY_PORTFOLIO = {
    "TSM": {"entry_date": "2025-04-18", "entry_price": 163.33},
    "QLD": {"entry_date": "2026-07-10", "entry_price": 92.07},

    }

# --- B. 交易池 (你想尋找進場機會的雷達名單) ---
TICKERS = [
     "QLD","AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "BRK-B", "LLY", "AVGO", "TSLA",
    "JPM", "WMT", "UNH", "V", "XOM", "MA", "PG", "JNJ", "COST", "HD",
    "ORCL", "MRK", "ABBV", "CVX", "CRM", "BAC", "KO", "NFLX", "PEP", "AMD",
    "LIN", "TMO", "WFC", "DIS", "CSCO", "MCD", "INTU", "QCOM", "AMAT", "IBM",
    "TXN", "NOW", "UBER", "GE", "CAT", "AXP", "ISRG", "PM", "GS", "BA"
]

# --- C. 策略核心參數 (回測最佳化後的勝率甜蜜點) ---
STRATEGY_PARAMS = {
    # 大環境判定參數
    'VIX_THRESHOLD': 30,                # VIX 恐慌界線 
    'BREADTH_THRESHOLD': 0.60,          # 大盤寬度健康門檻 (0.50代表50%標的站上季線)
    
    # 風險與出場參數
    'INIT_STOP_MULT': 2.5,              # 買進時的初始停損 ATR 倍數 
    'TRAIL_STOP_MULT': 2.5,             # 獲利後的吊燈停利 ATR 倍數 
    
    # V6 順勢突破參數
    'V6_KD_MAX': 60,                    # V6 允許進場的 KD 數值上限 
    
    # V5 恐慌抄底參數
    'V5_OVERSOLD_PCT': 0.7,            # 跌破年線的極端乖離率 (0.78 代表跌破年線 22%)
    'V5_KD_MAX': 25                    # V5 抄底專用 KD 黃金交叉上限 
}


# ==========================================
# ⚙️ 2. 底層引擎區 (以下程式碼為系統核心，請勿更動)
# ==========================================

# 獨立的環境感測池 (專門用來計算大盤寬度的標普前 50 大，確保大盤判定客觀)
BREADTH_TICKERS = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "BRK-B", "LLY", "AVGO", "TSLA",
    "JPM", "WMT", "UNH", "V", "XOM", "MA", "PG", "JNJ", "COST", "HD",
    "ORCL", "MRK", "ABBV", "CVX", "CRM", "BAC", "KO", "NFLX", "PEP", "AMD",
    "LIN", "TMO", "WFC", "DIS", "CSCO", "MCD", "INTU", "QCOM", "AMAT", "IBM",
    "TXN", "NOW", "UBER", "GE", "CAT", "AXP", "ISRG", "PM", "GS", "BA"
]

MARKET_TICKERS = ["SPY", "^VIX"] 
PERIOD = "2y"
DAYS_TO_SHOW = 5

def calculate_indicators(df):
    low_min = df['Low'].rolling(window=14).min()
    high_max = df['High'].rolling(window=14).max()
    df['K'] = (((df['Close'] - low_min) / (high_max - low_min)) * 100).rolling(window=3).mean()
    df['D'] = df['K'].rolling(window=3).mean()
    df['EMA_20'] = df['Close'].ewm(span=20, adjust=False).mean()
    df['MA_50'] = df['Close'].rolling(window=50).mean()
    df['MA_200'] = df['Close'].rolling(window=200).mean()
    df['Rolling_Min_20'] = df['Low'].rolling(window=20).min()
    
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
    
    # 💡 讀取控制面板參數
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

# --- 執行主程式 ---
print("🚀 啟動 V7 雙劍合璧資產管家 (讀取大盤環境與個股數據中...)")

data_dict = {}
env_dict = {}

for symbol in MARKET_TICKERS:
    try:
        df = yf.download(symbol, period=PERIOD, progress=False)
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        if symbol == "SPY":
            df['MA_200'] = df['Close'].rolling(window=200).mean()
        env_dict[symbol] = df
    except Exception:
        pass

all_tickers_to_fetch = list(set(TICKERS + list(MY_PORTFOLIO.keys()) + BREADTH_TICKERS))
for symbol in all_tickers_to_fetch:
    try:
        df = yf.download(symbol, period=PERIOD, progress=False)
        if df.empty: continue
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df = calculate_indicators(df)
        data_dict[symbol] = df
    except Exception:
        pass

latest_date = None
for sym in TICKERS:
    if sym in data_dict and not data_dict[sym].empty:
        latest_date = data_dict[sym].index[-1]
        break

if latest_date is None:
    print("❌ 無法取得最新交易日期數據，請檢查網路連線。")
    exit()

spy_latest = env_dict["SPY"].iloc[-1]
vix_latest = env_dict["^VIX"].iloc[-1]

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

# 💡 讀取控制面板參數
is_spy_uptrend = spy_latest['Close'] > spy_latest['MA_200']
is_vix_calm = vix_latest['Close'] < STRATEGY_PARAMS['VIX_THRESHOLD']
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
            # 💡 讀取控制面板參數
            is_strong_uptrend = (row['MA_50'] > row['MA_200']) and (row['Close'] > row['MA_200'])
            is_kd_turning_up = (prev_row['K'] < prev_row['D']) and (row['K'] > row['D']) and (row['K'] < STRATEGY_PARAMS['V6_KD_MAX'])
            is_breakout_20ema = (prev_row['Close'] <= prev_row['EMA_20']) and (row['Close'] > row['EMA_20'])
            if is_strong_uptrend and is_kd_turning_up and is_breakout_20ema:
                buy_signal = True
                signal_type = "V6 強勢拉回表態"
        else:
            # 💡 讀取控制面板參數
            is_deep_oversold = row['Close'] < (row['MA_200'] * STRATEGY_PARAMS['V5_OVERSOLD_PCT']) 
            is_uptrend = row['Close'] > row['MA_200']
            is_kd_golden_cross = (prev_row['K'] < prev_row['D']) and (row['K'] > row['D']) and (row['K'] < STRATEGY_PARAMS['V5_KD_MAX'])
            
            if (is_uptrend or is_deep_oversold) and is_kd_golden_cross:
                buy_signal = True
                signal_type = "V5 極度超賣抄底"
                
        if buy_signal:
            atr_val = row['ATR'] if not pd.isna(row['ATR']) else (row['Close'] * 0.02)
            # 💡 讀取控制面板參數
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
print("📸 正在為您生成專屬交易儀表板，請稍候...")

if my_portfolio_status:
    df_my = pd.DataFrame(my_portfolio_status)
    portfolio_html = df_my[['股票', '進場日', '成本', '現價', '目前ATR', '帳上損益(%)', '目前防守線', '狀態']].to_html(index=False, border=0, classes='styled-table')
    portfolio_html = portfolio_html.replace('✅ 安全持股中', '<span class="good">✅ 安全持股中</span>')
    portfolio_html = portfolio_html.replace('🚨 已破防守線，建議賣出！', '<span class="bad">🚨 已破防守線，建議賣出！</span>')
else:
    portfolio_html = "<p style='color: #888; text-align: center;'>目前 MY_PORTFOLIO 中沒有設定持股。</p>"

if new_opportunities:
    df_new = pd.DataFrame(new_opportunities).drop_duplicates(subset=['股票', '策略', '訊號日'], keep='last')
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
            padding: 40px;
            max-width: 1000px;
            margin: 0 auto;
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
    </style>
</head>
<body>
    <h1>🚀 V7 雙劍合璧資產管家 ({latest_date.strftime('%Y-%m-%d')})</h1>
    <div class="panel">
        <h2>🌍 【今日大環境測候站】</h2>
        <p>📊 標普500 (SPY)： {spy_display} (現價: {round(spy_latest['Close'], 2)})</p>
        <p>😨 恐慌指數 (VIX)： {vix_display} (現價: {round(vix_latest['Close'], 2)})</p>
        <p>📈 大盤寬度 (站上50MA比例)： {breadth_display} ({int(breadth_pct*100)}%)</p>
        <hr style="border-color: #30363d;">
        <p>🤖 系統判定今日採用策略： <span class="highlight">{current_regime}</span></p>
        <p>💡 說明：{regime_desc}</p>
    </div>
    <div class="panel">
        <h2>🛡️ 【我的真實持股追蹤】 (每天請依照此防守線修改券商停損單)</h2>
        {portfolio_html}
    </div>
    <div class="panel">
        <h2>🎯 【市場最新進場雷達】 (近 {DAYS_TO_SHOW} 天內觸發)</h2>
        {radar_html}
    </div>
</body>
</html>
"""

file_path = os.path.abspath('Trading_Dashboard.html')
with open(file_path, 'w', encoding='utf-8') as f:
    f.write(html_template)

print(f"✅ 儀表板已生成！正在為您開啟瀏覽器...")
file_uri = pathlib.Path(file_path).as_uri()
webbrowser.open(file_uri)
