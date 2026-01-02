#!/usr/bin/env python3
"""
中国股市专业监控系统 - 动态币种逻辑对齐版
1. 信号逻辑：完全对齐《动态热门币种监控.py》的波段动能与背离算法
2. 运行环境：适配阿里云，通过 Cloudflare Workers 中转发送 TG 信号
"""

import time
import datetime
import logging
import requests
import pandas as pd
import numpy as np
import akshare as ak
from threading import Lock
from concurrent.futures import ThreadPoolExecutor

# ==========================================
# 1. 核心配置（对齐币种监控参数）
# ==========================================
TG_CONFIG = {
    'TOKEN': '8553821769:AAHysPPPMydLiF1A1l2ab8xRrrBWfSv-kno',
    'CHAT_ID': '406894294',
    'PROXY_DOMAIN': 'gupiao.345369.xyz'  # 你的 CF 中转地址
}

# 监控周期映射（对齐 HTF 过滤逻辑）
TIMEFRAMES = ['5', '15', '30', '60', '日线']
HTF_MAP = {
    '5': '30',
    '15': '60',
    '30': '60',
    '60': '日线',
    '日线': '周线'
}

SIGNAL_DESC = {
    "T0": "趋势顺势：均线与RSI共振确认",
    "T0+精品": "精品收缩：动能回调衰竭后的高胜率爆发",
    "S1": "强势突破：价格站稳核心均线簇",
    "S2": "生命回测：大周期关键趋势位支撑",
    "M底背": "MACD底背离：价格与动能底部的终极反转",
    "R底背": "RSI底背离：强弱指标显示下跌动能枯竭"
}

TOP_N_STOCKS = 50       # 监控成交额前50名
VOLUME_THRESHOLD = 5e8  # 5亿成交额门槛
RISK_RATIO = 0.8        # 风险系数（用于杠杆建议参考）

# ==========================================
# 2. 技术引擎（对齐币种监控算法）
# ==========================================
class MasterQuantEngine:
    def rma(self, series, period):
        """对齐 TradingView 的 RMA 算法"""
        return series.ewm(alpha=1/period, adjust=False).mean()

    def calc_indicators(self, df):
        """指标参数完全对齐币种监控"""
        if df is None or len(df) < 150: return None
        c, h, l = df['close'], df['high'], df['low']
        
        # 均线簇：55, 89, 144
        df['s55'] = c.rolling(55).mean()
        df['s89'] = c.rolling(89).mean()
        df['s144'] = c.rolling(144).mean()
        
        # MACD：34, 89, 13
        e1, e2 = c.ewm(span=34, adjust=False).mean(), c.ewm(span=89, adjust=False).mean()
        df['macd'] = e1 - e2
        df['sig'] = df['macd'].ewm(span=13, adjust=False).mean()
        df['hist'] = df['macd'] - df['sig']
        
        # RSI：21, 34, 89 (TradingView RMA版)
        def tv_rsi(s, p):
            diff = s.diff()
            up = self.rma(diff.where(diff > 0, 0), p)
            down = self.rma(-diff.where(diff < 0, 0), p)
            return 100 - (100 / (1 + up/down))

        df['rsi21'], df['r34'], df['r89'] = tv_rsi(c, 21), tv_rsi(c, 34), tv_rsi(c, 89)
        return df

    def analyze_wave_logic(self, df, htf_df):
        """核心波段逻辑：对齐 analyze_wave_logic"""
        if df is None or htf_df is None: return None
        idx = len(df) - 1 
        hist, high, low, close, rsi = df['hist'].values, df['high'].values, df['low'].values, df['close'].values, df['rsi21'].values
        
        # 提取波峰波谷
        def get_wave_peaks(h_list, p_h, p_l, r_list):
            waves = []
            cur = {'type': 0, 'peak_h': 0, 'price': 0, 'rsi': 50}
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

        # MACD 勾头检测 (仅监控做多信号)
        m_hook_up = (cur_w['type'] == -1 and hist[idx] > hist[idx-1]) 
        if not m_hook_up: return None

        # 大周期 HTF 过滤
        ht_h, ht_p = htf_df['hist'].iloc[-1], htf_df['hist'].iloc[-2]
        htf_bull_ok = (ht_h > 0) or (ht_h < 0 and ht_h > ht_p)
        if not htf_bull_ok: return None

        sigs = []
        s55, s89, s144 = df['s55'].iloc[idx], df['s89'].iloc[idx], df['s144'].iloc[idx]
        r34, r89 = df['r34'].iloc[idx], df['r89'].iloc[idx]
        is_contract = abs(cur_w['peak_h']) < abs(prev_oppo['peak_h']) if prev_oppo else False

        # 信号组合判定
        if prev_same and close[idx] < prev_same['price']:
            if cur_w['peak_h'] > prev_same['peak_h']: sigs.append("M底背")
            if cur_w['rsi'] > prev_same['rsi']: sigs.append("R底背")
        if s55 > s89 and r34 > r89: sigs.append("T0+精品" if is_contract else "T0")
        if r89 > 50 and r34 < r89 and close[idx] > s144: sigs.append("S1")
        if r89 < 50 and r34 < r89 and close[idx] > s144: sigs.append("S2")

        if not sigs: return None
        
        sl = low[idx-5:idx+1].min() # 简单支撑止损
        return {
            'time': df['datetime'].iloc[idx], 
            'price': close[idx], 
            'sl': sl, 
            'side': "LONG", 
            'types': list(set(sigs))
        }

# ==========================================
# 3. 股票数据与监控系统
# ==========================================
class ChinaStockMonitor:
    def __init__(self):
        self.engine = MasterQuantEngine()
        self.processed_alerts = {}
        self.logger = logging.getLogger("StockMaster")

    def send_tg_via_proxy(self, symbol, tf, sig):
        """通过 Cloudflare 中转发送信号"""
        bj = sig['time'].strftime('%m-%d %H:%M')
        details = "\n".join([f"• *{t}*: {SIGNAL_DESC.get(t, '共振确认')}" for t in sig['types']])
        msg = (f"🟢【A股多单共振】\n━━━━━━━━━━━━━━\n🔥 品种: `{symbol}` | 周期: `{tf}`\n💰 价格: `{sig['price']:.2f}`\n"
               f"🛡️ 止损: `{sig['sl']:.2f}`\n━━━━━━━━━━━━━━\n📊 信号详情:\n{details}\n━━━━━━━━━━━━━━\n⏰ 时间(BJ): {bj}")
        
        url = f"https://{TG_CONFIG['PROXY_DOMAIN']}/bot{TG_CONFIG['TOKEN']}/sendMessage"
        try:
            requests.post(url, json={'chat_id': TG_CONFIG['CHAT_ID'], 'text': msg, 'parse_mode': 'Markdown'}, timeout=10)
            return True
        except Exception as e:
            self.logger.error(f"发送失败: {e}")
            return False

    def get_data(self, symbol, tf):
        """适配 AKShare 的 K 线获取"""
        code = symbol.split('.')[0]
        try:
            if tf == '日线':
                df = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="hfq")
                df = df.rename(columns={'日期':'datetime','开盘':'open','收盘':'close','最高':'high','最低':'low','成交量':'volume'})
            elif tf == '周线':
                df = ak.stock_zh_a_hist(symbol=code, period="weekly", adjust="hfq")
                df = df.rename(columns={'日期':'datetime','开盘':'open','收盘':'close','最高':'high','最低':'low','成交量':'volume'})
            else:
                df = ak.stock_zh_a_hist_min_em(symbol=code, period=tf, adjust='hfq')
                df = df.rename(columns={'时间':'datetime','开盘':'open','收盘':'close','最高':'high','最低':'low','成交量':'volume'})
            
            if df is None or df.empty: return None
            df['datetime'] = pd.to_datetime(df['datetime'])
            return self.engine.calc_indicators(df)
        except: return None

    def run(self):
        self.logger.info("🚀 股市大师版监控启动 | 逻辑对齐币种热门脚本")
        while True:
            try:
                # 刷新热门榜单
                spot = ak.stock_zh_a_spot_em()
                spot['成交额'] = pd.to_numeric(spot['成交额'], errors='coerce')
                active_list = spot[spot['成交额'] > VOLUME_THRESHOLD].sort_values('成交额', ascending=False).head(TOP_N_STOCKS)
                symbols = [f"{c}.SH" if c.startswith('6') else f"{c}.SZ" for c in active_list['代码']]

                for sym in symbols:
                    for tf in TIMEFRAMES:
                        df = self.get_data(sym, tf)
                        htf_tf = HTF_MAP.get(tf, '日线')
                        htf_df = self.get_data(sym, htf_tf)
                        
                        res = self.engine.analyze_wave_logic(df, htf_df)
                        if res:
                            alert_id = f"{sym}_{tf}_{res['time']}"
                            if alert_id not in self.processed_alerts:
                                if self.send_tg_via_proxy(sym, tf, res):
                                    self.processed_alerts[alert_id] = True
                                    print(f"🔔 发现信号: {sym} {tf} {res['types']}")
                    time.sleep(0.5) # 防止请求过快
                
                print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 轮询结束，等待中...")
                time.sleep(60)
            except Exception as e:
                self.logger.error(f"系统循环异常: {e}")
                time.sleep(30)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ChinaStockMonitor().run()
