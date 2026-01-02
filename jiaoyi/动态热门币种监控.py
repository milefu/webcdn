import ccxt
import pandas as pd
import numpy as np
import time
import datetime
import requests
import warnings

warnings.filterwarnings('ignore')

# ==========================================
# 1. 核心大师配置
# ==========================================
TG_TOKEN = '8553821769:AAHysPPPMydLiF1A1l2ab8xRrrBWfSv-kno'
CHAT_ID = '406894294'

# 监控周期与上级周期映射
TIMEFRAMES = ['5m', '15m', '30m', '1h', '4h']
HTF_MAP = {
    '5m': '30m',
    '15m': '1h',
    '30m': '4h',
    '1h': '4h',
    '4h': '1d'
}

TOP_N_SYMBOLS = 50           
REFRESH_LIST_SEC = 3600      
RISK_RATIO = 0.8             
MAX_LEVERAGE = 20            

SIGNAL_DESC = {
    "T0": "趋势顺势：均线与RSI共振确认",
    "T0+": "精品收缩：动能回调衰竭后的高胜率爆发",
    "S1": "强势突破：价格站稳核心均线簇",
    "S2": "生命回测：大周期关键趋势位支撑",
    "M顶背": "MACD顶背离：价格与动能顶部的终极衰竭",
    "M底背": "MACD底背离：价格与动能底部的终极反转",
    "R顶背": "RSI顶背离：强弱指标显示上涨动能枯竭",
    "R底背": "RSI底背离：强弱指标显示下跌动能枯竭"
}

# ==========================================
# 2. 交易引擎类
# ==========================================
class MasterQuant:
    def __init__(self):
        self.exchange = ccxt.binanceusdm({
            'enableRateLimit': True,
            'options': {'defaultType': 'future'}
        })
        self.processed_alerts = {}
        self.htf_cache = {}

    def get_active_symbols(self):
        """【修复版】解决 NoneType 报错，增强稳定性"""
        try:
            tickers = self.exchange.fetch_tickers()
            data = []
            for sym, t in tickers.items():
                # 只选 USDT 永续合约
                if '/USDT' in sym and (':' not in sym or ':USDT' in sym):
                    # 过滤杠杆代币和非标准品种
                    if any(x in sym for x in ['BULL', 'BEAR', 'UP', 'DOWN', '_']): continue
                    
                    # 安全提取数值，处理 None 值
                    qv = t.get('quoteVolume')
                    bv = t.get('baseVolume')
                    lp = t.get('last')
                    
                    vol = 0.0
                    try:
                        if qv is not None:
                            vol = float(qv)
                        elif bv is not None and lp is not None:
                            vol = float(bv) * float(lp)
                    except (ValueError, TypeError):
                        vol = 0.0

                    if vol > 0:
                        data.append({'symbol': sym, 'vol': vol})
            
            if not data:
                return ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT']
                
            df = pd.DataFrame(data).sort_values(by='vol', ascending=False)
            res = df.head(TOP_N_SYMBOLS)['symbol'].tolist()
            print(f"✅ 热门榜单刷新：锁定 {len(res)} 个活跃合约")
            return res
        except Exception as e:
            print(f"⚠️ 选币列表获取异常: {e}")
            return ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT']

    def rma(self, series, period):
        return series.ewm(alpha=1/period, adjust=False).mean()

    def calc_indicators(self, df):
        if df is None or len(df) < 150: return None
        c, h, l = df['close'], df['high'], df['low']
        
        df['s55'] = c.rolling(55).mean()
        df['s89'] = c.rolling(89).mean()
        df['s144'] = c.rolling(144).mean()
        
        e1, e2 = c.ewm(span=34, adjust=False).mean(), c.ewm(span=89, adjust=False).mean()
        df['macd'] = e1 - e2
        df['sig'] = df['macd'].ewm(span=13, adjust=False).mean()
        df['hist'] = df['macd'] - df['sig']
        
        def tv_rsi(s, p):
            diff = s.diff()
            up = self.rma(diff.where(diff > 0, 0), p)
            down = self.rma(-diff.where(diff < 0, 0), p)
            return 100 - (100 / (1 + up/down))

        df['rsi21'], df['r34'], df['r89'] = tv_rsi(c, 21), tv_rsi(c, 34), tv_rsi(c, 89)
        return df

    def analyze_wave_logic(self, df, htf_df):
        idx = len(df) - 2 
        hist, high, low, close, rsi = df['hist'].values, df['high'].values, df['low'].values, df['close'].values, df['rsi21'].values
        
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

        m_hook_up = (cur_w['type'] == -1 and hist[idx] > hist[idx-1]) 
        m_hook_dn = (cur_w['type'] == 1 and hist[idx] < hist[idx-1])  
        if not (m_hook_up or m_hook_dn): return None

        ht_h, ht_p = htf_df['hist'].iloc[-2], htf_df['hist'].iloc[-3]
        htf_bull_ok = (ht_h > 0) or (ht_h < 0 and ht_h > ht_p)
        htf_bear_ok = (ht_h < 0) or (ht_h > 0 and ht_h < ht_p)

        sigs, side, sl = [], "", 0
        s55, s89, s144 = df['s55'].iloc[idx], df['s89'].iloc[idx], df['s144'].iloc[idx]
        r34, r89 = df['r34'].iloc[idx], df['r89'].iloc[idx]
        is_contract = abs(cur_w['peak_h']) < abs(prev_oppo['peak_h']) if prev_oppo else False

        if m_hook_up and htf_bull_ok:
            side, sl = "LONG", low[idx]
            if prev_same and close[idx] < prev_same['price']:
                if cur_w['peak_h'] > prev_same['peak_h']: sigs.append("M底背")
                if cur_w['rsi'] > prev_same['rsi']: sigs.append("R底背")
            if s55 > s89 and r34 > r89: sigs.append("T0+精品" if is_contract else "T0")
            if r89 > 50 and r34 < r89 and close[idx] > s144: sigs.append("S1")
            if r89 < 50 and r34 < r89 and close[idx] > s144: sigs.append("S2")

        if m_hook_dn and htf_bear_ok:
            side, sl = "SHORT", high[idx]
            if prev_same and close[idx] > prev_same['price']:
                if cur_w['peak_h'] < prev_same['peak_h']: sigs.append("M顶背")
                if cur_w['rsi'] < prev_same['rsi']: sigs.append("R顶背")
            if s55 < s89 and r34 < r89: sigs.append("T0+精品" if is_contract else "T0")
            if r89 < 50 and r34 > r89 and close[idx] < s144: sigs.append("S1")
            if r89 > 50 and r34 > r89 and close[idx] < s144: sigs.append("S2")

        if not sigs: return None
        risk = abs(close[idx]-sl)/close[idx]
        lev = min(round((1/risk)*RISK_RATIO, 1), MAX_LEVERAGE) if risk > 0.001 else 5
        return {'time': df['timestamp'].iloc[idx], 'price': close[idx], 'sl': sl, 'lev': lev, 'side': side, 'types': list(set(sigs))}

    def send_tg(self, sym, tf, sig):
        bj = pd.to_datetime(sig['time']).tz_localize('UTC').tz_convert('Asia/Shanghai').strftime('%m-%d %H:%M')
        icon = "🟢【多单信号】" if sig['side'] == "LONG" else "🔴【空单信号】"
        details = "\n".join([f"• *{t}*: {SIGNAL_DESC.get(t, '共振确认')}" for t in sig['types']])
        msg = (f"{icon}\n━━━━━━━━━━━━━━\n🔥 品种: `{sym}` | 周期: `{tf}`\n💰 价格: `{sig['price']}`\n🛡️ 止损: `{sig['sl']}`\n⚙️ 建议杠杆: `{sig['lev']}x`\n"
               f"━━━━━━━━━━━━━━\n📊 信号详情:\n{details}\n━━━━━━━━━━━━━━\n⏰ 时间(BJ): {bj}")
        try:
            requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", 
                          json={'chat_id':TG_CHAT_ID, 'text':msg, 'parse_mode':'Markdown'}, timeout=10)
        except: pass

    def run(self):
        print(f"🚀 大师版量化监控已就绪 | 范围: 前 {TOP_N_SYMBOLS} 活跃币种")
        last_refresh, active_symbols = 0, []
        
        while True:
            try:
                if time.time() - last_refresh > REFRESH_LIST_SEC:
                    active_symbols = self.get_active_symbols()
                    last_refresh = time.time()
                
                self.htf_cache.clear()

                for sym in active_symbols:
                    for tf in TIMEFRAMES:
                        try:
                            time.sleep(0.15) 
                            raw = self.exchange.fetch_ohlcv(sym, tf, limit=160)
                            df = self.calc_indicators(pd.DataFrame(raw, columns=['timestamp','open','high','low','close','volume']))
                            
                            htf_tf = HTF_MAP.get(tf, '4h')
                            cache_key = f"{sym}_{htf_tf}"
                            if cache_key not in self.htf_cache:
                                h_raw = self.exchange.fetch_ohlcv(sym, htf_tf, limit=100)
                                self.htf_cache[cache_key] = self.calc_indicators(pd.DataFrame(h_raw, columns=['timestamp','open','high','low','close','volume']))
                            
                            htf_df = self.htf_cache[cache_key]
                            
                            res = self.analyze_wave_logic(df, htf_df)
                            if res:
                                alert_id = f"{sym}_{tf}_{res['time']}"
                                if alert_id not in self.processed_alerts:
                                    self.send_tg(sym, tf, res)
                                    self.processed_alerts[alert_id] = True
                                    print(f"🔔 发现共振: {sym} {tf} {res['types']}")
                        except Exception: continue
                
                print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 一轮扫描结束...")
                time.sleep(20) 
            except Exception as e:
                print(f"⚠️ 系统异常: {e}"); time.sleep(30)

if __name__ == "__main__":
    MasterQuant().run()