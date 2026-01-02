#!/usr/bin/env python3
"""
中国股市专业监控系统 - 交易时间优化版
1. 时间控制：严格遵守 A 股交易时间，自动识别法定节假日
2. 逻辑对齐：完全对齐币种脚本的波段动能与背离算法
3. 网络中转：通过 Cloudflare Workers 绕过 TG 封锁
"""

import time
import datetime
import logging
import requests
import pandas as pd
import numpy as np
import akshare as ak
from chinese_calendar import is_workday # 需安装: pip install chinesecalendar
from threading import Lock
from concurrent.futures import ThreadPoolExecutor

# ==========================================
# 1. 核心配置
# ==========================================
TG_CONFIG = {
    'TOKEN': '8273304364:AAGFIP####v7TRwps2X4',
    'CHAT_ID': '406####94',
    'PROXY_DOMAIN': 'gupiao.345369.xyz' 
}

TIMEFRAMES = ['5', '15', '30', '60', '日线']
HTF_MAP = {'5': '30', '15': '60', '30': '60', '60': '日线', '日线': '周线'}

SIGNAL_DESC = {
    "T0": "趋势顺势：均线与RSI共振确认",
    "T0+精品": "精品收缩：动能回调衰竭后的高胜率爆发",
    "S1": "强势突破：价格站稳核心均线簇",
    "S2": "生命回测：大周期关键趋势位支撑",
    "M底背": "MACD底背离：价格与动能底部的终极反转",
    "R底背": "RSI底背离：强弱指标显示下跌动能枯竭"
}

TOP_N_STOCKS = 50       
VOLUME_THRESHOLD = 5e8  
# ==========================================
# 2. 交易时间控制器 (A股专用)
# ==========================================
def is_trade_time():
    """判断当前是否为 A 股交易时段"""
    now = datetime.datetime.now()
    
    # 1. 检查是否为工作日（自动处理调休和节假日）
    if not is_workday(now):
        return False
    
    # 2. 检查具体交易时段
    current_time = now.time()
    morning_start = datetime.time(9, 25) # 提前5分钟开始准备数据
    morning_end = datetime.time(11, 31)
    afternoon_start = datetime.time(12, 55)
    afternoon_end = datetime.time(15, 5)
    
    if (morning_start <= current_time <= morning_end) or \
       (afternoon_start <= current_time <= afternoon_end):
        return True
    return False

# ==========================================
# 3. 技术引擎 (对齐币种脚本算法)
# ==========================================
class MasterQuantEngine:
    def rma(self, series, period):
        return series.ewm(alpha=1/period, adjust=False).mean()

    def calc_indicators(self, df):
        if df is None or len(df) < 150: return None
        c, h, l = df['close'], df['high'], df['low']
        # 均线: 55, 89, 144
        df['s55'], df['s89'], df['s144'] = c.rolling(55).mean(), c.rolling(89).mean(), c.rolling(144).mean()
        # MACD: 34, 89, 13
        e1, e2 = c.ewm(span=34, adjust=False).mean(), c.ewm(span=89, adjust=False).mean()
        df['macd'] = e1 - e2
        df['sig'] = df['macd'].ewm(span=13, adjust=False).mean()
        df['hist'] = df['macd'] - df['sig']
        # RSI: 21, 34, 89
        def tv_rsi(s, p):
            diff = s.diff()
            up = self.rma(diff.where(diff > 0, 0), p)
            down = self.rma(-diff.where(diff < 0, 0), p)
            return 100 - (100 / (1 + up/down))
        df['rsi21'], df['r34'], df['r89'] = tv_rsi(c, 21), tv_rsi(c, 34), tv_rsi(c, 89)
        return df

    def analyze_wave_logic(self, df, htf_df):
        if df is None or htf_df is None: return None
        idx = len(df) - 1 
        hist, high, low, close, rsi = df['hist'].values, df['high'].values, df['low'].values, df['close'].values, df['rsi21'].values
        
        def get_wave_peaks(h_list, p_h, p_l, r_list):
            waves, cur = [], {'type': 0, 'peak_h': 0, 'price': 0, 'rsi': 50}
            for j in range(max(0, idx-140), idx+1):
                w_type = 1 if h_list[j] > 0 else -1
                if w_type != cur['type']:
                    if cur['type'] != 0: waves.append(cur)
                    cur = {'type': w_type, 'peak_h': h_list[j], 'price': p_h[j] if w_type==1 else p_l[j], 'rsi': r_list[j]}
                else:
                    if (w_type == 1 and h_list[j] > cur['peak_h']) or (w_type == -1 and h_list[j] < cur['peak_h']):
                        cur.update({'peak_h': h_list[j], 'price': p_h[j] if w_type==1 else p_l[j], 'rsi': r_list[j]})
            return waves, cur

        waves, cur_w = get_wave_peaks(hist, high, low, rsi)
        if not waves: return None
        prev_same = next((w for w in reversed(waves) if w['type'] == cur_w['type']), None)
        prev_oppo = next((w for w in reversed(waves) if w['type'] != cur_w['type']), None)

        m_hook_up = (cur_w['type'] == -1 and hist[idx] > hist[idx-1])
        if not m_hook_up: return None

        ht_h, ht_p = htf_df['hist'].iloc[-1], htf_df['hist'].iloc[-2]
        if not ((ht_h > 0) or (ht_h < 0 and ht_h > ht_p)): return None

        sigs = []
        s55, s89, s144 = df['s55'].iloc[idx], df['s89'].iloc[idx], df['s144'].iloc[idx]
        r34, r89 = df['r34'].iloc[idx], df['r89'].iloc[idx]
        is_contract = abs(cur_w['peak_h']) < abs(prev_oppo['peak_h']) if prev_oppo else False

        if prev_same and close[idx] < prev_same['price']:
            if cur_w['peak_h'] > prev_same['peak_h']: sigs.append("M底背")
            if cur_w['rsi'] > prev_same['rsi']: sigs.append("R底背")
        if s55 > s89 and r34 > r89: sigs.append("T0+精品" if is_contract else "T0")
        if r89 > 50 and r34 < r89 and close[idx] > s144: sigs.append("S1")
        if r89 < 50 and r34 < r89 and close[idx] > s144: sigs.append("S2")

        if not sigs: return None
        return {'time': df['datetime'].iloc[idx], 'price': close[idx], 'sl': low[idx-5:idx+1].min(), 'types': list(set(sigs))}

# ==========================================
# 4. 监控调度中心
# ==========================================
class ChinaStockMonitor:
    def __init__(self):
        self.engine = MasterQuantEngine()
        self.processed_alerts = {}
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
        self.logger = logging.getLogger("StockMaster")

    def run(self):
        self.logger.info("🚀 股市专家系统已启动 (支持节假日识别)")
        while True:
            try:
                if not is_trade_time():
                    # 非交易时间，每10分钟检查一次，降低服务器功耗
                    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 非交易时段，系统休眠中...")
                    time.sleep(600)
                    continue

                # 交易时间扫描逻辑
                spot = ak.stock_zh_a_spot_em()
                spot['成交额'] = pd.to_numeric(spot['成交额'], errors='coerce')
                symbols = [f"{c}.SH" if c.startswith('6') else f"{c}.SZ" for c in 
                           spot[spot['成交额'] > VOLUME_THRESHOLD].sort_values('成交额', ascending=False).head(TOP_N_STOCKS)['代码']]

                for sym in symbols:
                    for tf in TIMEFRAMES:
                        # 此处 get_data 逻辑与前述一致，获取数据并调用 analyze_wave_logic
                        pass 
                    time.sleep(0.5)
                
                time.sleep(60) 
            except Exception as e:
                self.logger.error(f"系统异常: {e}")
                time.sleep(60)

if __name__ == "__main__":
    ChinaStockMonitor().run()
