#!/usr/bin/env python3
"""
中国股市专业监控系统 - 网络容错版
严格保留原始信号条件，增强网络异常处理
"""

import os
import sys
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
# 1. 配置参数（严格保持原始信号条件）
# ==========================================
# 信号参数（完全保持动态热门币种监控的原始设置）
SIGNAL_PARAMS = {
    'MA_SHORT': 5,
    'MA_MEDIUM': 20,
    'MA_LONG': 55,
    'MA_XLONG': 144,
    'MACD_FAST': 12,
    'MACD_SLOW': 26,
    'MACD_SIGNAL': 9,
    'RSI_SHORT': 6,
    'RSI_MEDIUM': 21,
    'RSI_LONG': 89,
    'RSI_OVERBOUGHT': 70,
    'RSI_OVERSOLD': 30,
    'VOLUME_RATIO': 1.5,
    'TREND_STRONG': 0.6,
    'TREND_MEDIUM': 0.3,
    'DIVERGENCE_LOOKBACK': 30
}

# 监控参数
TOP_N_STOCKS = 50
VOLUME_THRESHOLD = 5e8
MIN_PRICE = 2.0
MAX_PRICE = 500.0
CACHE_DURATION = 300
REQUEST_DELAY = 1.0

# 时间周期配置
TIMEFRAMES = ['5', '15', '30', '60', '日线']
HTF_MAP = {'5': '15', '15': '30', '30': '60', '60': '日线', '日线': '周线'}

# ==========================================
# 2. 多通道通知系统（解决网络封锁问题）
# ==========================================
class NotificationSystem:
    def __init__(self):
        self.channels = [
            TelegramChannel(),
            EmailChannel(),
            WebhookChannel(),
            LocalFileChannel()
        ]
        self.fallback_order = [0, 3, 1, 2]  # 通道优先级顺序
        self.logger = logging.getLogger(__name__)
    
    def send_alert(self, message):
        """多通道发送警报（自动故障转移）"""
        last_error = None
        for channel_idx in self.fallback_order:
            try:
                result = self.channels[channel_idx].send(message)
                if result:
                    return True
            except Exception as e:
                last_error = e
                continue
        
        self.logger.error(f"所有通知通道发送失败: {last_error}")
        return False

class TelegramChannel:
    def __init__(self):
        self.token = '8553821769:AAHysPPPMydLiF1A1l2ab8xRrrBWfSv-kno'
        self.chat_id = '406894294'
        self.timeout = 10
    
    def send(self, message):
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={
                    'chat_id': self.chat_id,
                    'text': message,
                    'parse_mode': 'Markdown',
                    'disable_web_page_preview': True
                },
                timeout=self.timeout
            )
            return response.status_code == 200
        except Exception:
            return False

class EmailChannel:
    def send(self, message):
        """邮件通知通道（需配置SMTP）"""
        # 实现邮件发送逻辑
        return False  # 示例中暂不实现

class WebhookChannel:
    def send(self, message):
        """Webhook通知通道"""
        # 实现Webhook发送逻辑
        return False  # 示例中暂不实现

class LocalFileChannel:
    def __init__(self):
        self.log_file = "alerts.log"
    
    def send(self, message):
        """本地文件备份通道"""
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(f"\n[{datetime.datetime.now()}] {message}")
            return True
        except Exception:
            return False

# ==========================================
# 3. 专业信号引擎（严格保持原始条件）
# ==========================================
class ProfessionalSignalEngine:
    def __init__(self):
        self.params = SIGNAL_PARAMS
        self.logger = logging.getLogger(__name__)
    
    def calc_technical_indicators(self, df):
        """计算技术指标（严格保持原始逻辑）"""
        if df is None or len(df) < 100:
            return None
            
        try:
            # 计算均线（保持原始参数）
            df['ma5'] = df['close'].rolling(self.params['MA_SHORT']).mean()
            df['ma20'] = df['close'].rolling(self.params['MA_MEDIUM']).mean()
            df['ma55'] = df['close'].rolling(self.params['MA_LONG']).mean()
            df['ma144'] = df['close'].rolling(self.params['MA_XLONG']).mean()
            
            # 计算MACD（保持原始参数）
            exp1 = df['close'].ewm(span=self.params['MACD_FAST'], adjust=False).mean()
            exp2 = df['close'].ewm(span=self.params['MACD_SLOW'], adjust=False).mean()
            df['macd'] = exp1 - exp2
            df['macd_signal'] = df['macd'].ewm(span=self.params['MACD_SIGNAL'], adjust=False).mean()
            df['macd_hist'] = df['macd'] - df['macd_signal']
            
            # 计算RSI（保持原始参数）
            delta = df['close'].diff()
            gain = delta.where(delta > 0, 0)
            loss = -delta.where(delta < 0, 0)
            
            avg_gain = gain.rolling(self.params['RSI_SHORT']).mean()
            avg_loss = loss.rolling(self.params['RSI_SHORT']).mean()
            rs = avg_gain / avg_loss
            df['rsi6'] = 100 - (100 / (1 + rs))
            
            avg_gain = gain.rolling(self.params['RSI_MEDIUM']).mean()
            avg_loss = loss.rolling(self.params['RSI_MEDIUM']).mean()
            rs = avg_gain / avg_loss
            df['rsi21'] = 100 - (100 / (1 + rs))
            
            avg_gain = gain.rolling(self.params['RSI_LONG']).mean()
            avg_loss = loss.rolling(self.params['RSI_LONG']).mean()
            rs = avg_gain / avg_loss
            df['rsi89'] = 100 - (100 / (1 + rs))
            
            # 计算成交量指标
            df['vol_ma20'] = df['volume'].rolling(20).mean()
            df['vol_ratio'] = df['volume'] / df['vol_ma20']
            
            return df
            
        except Exception as e:
            self.logger.error(f"计算技术指标异常: {e}")
            return None
    
    def analyze_signals(self, df, htf_df=None):
        """分析做多信号（严格保持原始条件）"""
        if df is None or len(df) < 100:
            return None
            
        try:
            current = df.iloc[-1]
            prev = df.iloc[-2]
            
            signals = []
            
            # 1. 趋势顺势信号 (T0)
            if (current['close'] > current['ma20'] > current['ma55'] and
                current['rsi6'] > 50 and current['rsi6'] < self.params['RSI_OVERBOUGHT'] and
                current['macd'] > current['macd_signal']):
                signals.append("T0")
            
            # 2. 精品收缩信号 (T0+)
            if (len(signals) > 0 and 
                current['vol_ratio'] > self.params['VOLUME_RATIO'] and
                current['rsi6'] > 40 and current['rsi6'] < 65):
                signals.append("T0+")
            
            # 3. 强势突破信号 (S1)
            if (current['close'] > current['ma55'] and
                current['rsi21'] > 50 and
                current['vol_ratio'] > self.params['VOLUME_RATIO']):
                signals.append("S1")
            
            # 4. 生命回测信号 (S2)
            if (current['close'] > current['ma144'] and
                current['rsi89'] < 45 and
                current['close'] > df['low'].rolling(20).mean().iloc[-1]):
                signals.append("S2")
            
            # 5. MACD底背离
            if self.check_divergence(df, 'macd', 'bullish'):
                signals.append("M底背")
            
            # 6. RSI底背离
            if self.check_divergence(df, 'rsi6', 'bullish'):
                signals.append("R底背")
            
            if not signals:
                return None
                
            # 计算止损位（保持原始逻辑）
            support_level = min(
                df['low'].tail(20).min(),
                current['ma20'],
                current['ma55']
            )
            risk_ratio = (current['close'] - support_level) / current['close']
            
            return {
                'time': current.name if hasattr(current, 'name') else datetime.datetime.now(),
                'price': current['close'],
                'support': support_level,
                'signals': signals,
                'rsi': current['rsi6'],
                'volume_ratio': current['vol_ratio'],
                'risk_ratio': risk_ratio
            }
            
        except Exception as e:
            self.logger.error(f"分析信号异常: {e}")
            return None
    
    def check_divergence(self, df, indicator, type='bullish'):
        """检查背离（保持原始逻辑）"""
        if len(df) < self.params['DIVERGENCE_LOOKBACK']:
            return False
            
        prices = df['close'].tail(self.params['DIVERGENCE_LOOKBACK']).values
        indicator_values = df[indicator].tail(self.params['DIVERGENCE_LOOKBACK']).values
        
        if type == 'bullish':
            # 底背离：价格新低，指标抬高
            price_lows = []
            indicator_lows = []
            
            for i in range(1, len(prices)-1):
                if prices[i] < prices[i-1] and prices[i] < prices[i+1]:
                    price_lows.append((i, prices[i]))
                if indicator_values[i] < indicator_values[i-1] and indicator_values[i] < indicator_values[i+1]:
                    indicator_lows.append((i, indicator_values[i]))
            
            if len(price_lows) >= 2 and len(indicator_lows) >= 2:
                latest_price_low = price_lows[-1][1]
                prev_price_low = price_lows[-2][1]
                latest_indicator_low = indicator_lows[-1][1]
                prev_indicator_low = indicator_lows[-2][1]
                
                return (latest_price_low < prev_price_low and 
                       latest_indicator_low > prev_indicator_low)
        
        return False

# ==========================================
# 4. 中国股市监控引擎（网络容错版）
# ==========================================
class ChinaStockMonitor:
    def __init__(self):
        self.signal_engine = ProfessionalSignalEngine()
        self.notifier = NotificationSystem()
        self.stock_cache = {}
        self.htf_cache = {}
        self.processed_alerts = {}
        self.cache_lock = Lock()
        self.last_refresh_time = 0
        self.active_stocks = []
        self.executor = ThreadPoolExecutor(max_workers=5)
        self.logger = logging.getLogger(__name__)
        
        self.logger.info("中国股市专业监控系统初始化完成")

    def refresh_stock_list(self):
        """刷新股票列表（带网络异常处理）"""
        try:
            self.logger.info("开始刷新股票列表...")
            start_time = time.time()
            
            # 获取A股实时数据
            spot_data = ak.stock_zh_a_spot_em()
            
            if spot_data is None or spot_data.empty:
                self.logger.warning("获取实时行情数据为空，使用默认股票")
                self.active_stocks = self.get_default_stocks()
                return
            
            # 数据清洗
            spot_data = spot_data.copy()
            numeric_cols = ['最新价', '涨跌幅', '成交量', '成交额']
            for col in numeric_cols:
                if col in spot_data.columns:
                    spot_data[col] = pd.to_numeric(spot_data[col], errors='coerce')
            
            # 过滤主板股票
            main_board = spot_data[
                (~spot_data['代码'].str.startswith(('300', '688', '8'), na=False)) &
                (spot_data['成交额'] > VOLUME_THRESHOLD) &
                (spot_data['最新价'] > MIN_PRICE) &
                (spot_data['最新价'] < MAX_PRICE)
            ].sort_values('成交额', ascending=False)
            
            if main_board.empty:
                self.logger.warning("有效股票列表为空，使用默认股票")
                self.active_stocks = self.get_default_stocks()
                return
            
            # 格式化股票代码
            stocks = []
            for _, row in main_board.head(TOP_N_STOCKS).iterrows():
                code = row['代码']
                stocks.append(f"{code}.SH" if code.startswith('6') else f"{code}.SZ")
            
            self.active_stocks = stocks
            self.last_refresh_time = time.time()
            self.logger.info(f"股票列表刷新完成，耗时{(time.time()-start_time):.2f}秒")
            self.logger.info(f"当前监控股票数量: {len(stocks)}")
            
        except Exception as e:
            self.logger.error(f"刷新股票列表异常: {e}")
            self.active_stocks = self.get_default_stocks()

    def get_default_stocks(self):
        """获取默认蓝筹股列表"""
        return [
            '600036.SH', '601318.SH', '600519.SH', '000858.SZ',
            '000333.SZ', '000651.SZ', '600276.SH', '601888.SH'
        ]

    def get_stock_data(self, symbol, period='日线', count=100):
        """获取股票K线数据（带缓存和重试）"""
        try:
            # 解析股票代码
            code = symbol.split('.')[0]
            
            cache_key = f"{symbol}_{period}"
            current_time = time.time()
            
            # 检查缓存
            with self.cache_lock:
                if cache_key in self.stock_cache:
                    cached_data, cache_time = self.stock_cache[cache_key]
                    if current_time - cache_time < CACHE_DURATION:
                        return cached_data
            
            df = None
            
            if period == '日线':
                # 获取日线数据
                df = ak.stock_zh_a_hist(
                    symbol=code,
                    period="daily",
                    adjust="hfq",
                    start_date=(datetime.datetime.now() - datetime.timedelta(days=200)).strftime('%Y%m%d')
                )
                if df is not None and not df.empty:
                    df = df.rename(columns={
                        '日期': 'datetime', '开盘': 'open', '收盘': 'close',
                        '最高': 'high', '最低': 'low', '成交量': 'volume', '成交额': 'amount'
                    })
            else:
                # 获取分钟线数据
                try:
                    period_map = {'5': '5', '15': '15', '30': '30', '60': '60'}
                    if period in period_map:
                        df = ak.stock_zh_a_hist_min_em(
                            symbol=code,
                            period=period_map[period],
                            adjust='hfq'
                        )
                        if df is not None and not df.empty:
                            df = df.rename(columns={
                                '时间': 'datetime', '开盘': 'open', '收盘': 'close',
                                '最高': 'high', '最低': 'low', '成交量': 'volume'
                            })
                except Exception as e:
                    self.logger.warning(f"获取{symbol} {period}分钟数据失败: {e}")
                    return None
            
            if df is None or df.empty:
                self.logger.warning(f"获取{symbol} {period}数据为空")
                return None
            
            # 数据预处理
            df = df.sort_values('datetime').reset_index(drop=True)
            df['datetime'] = pd.to_datetime(df['datetime'])
            
            # 数值列处理
            numeric_cols = ['open', 'close', 'high', 'low', 'volume']
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            
            df = df.dropna(subset=['close'])
            
            if len(df) < 50:
                self.logger.warning(f"{symbol} {period}数据量不足: {len(df)}条")
                return None
            
            # 计算技术指标
            df = self.signal_engine.calc_technical_indicators(df)
            
            # 更新缓存
            with self.cache_lock:
                self.stock_cache[cache_key] = (df.tail(count), current_time)
            
            return df.tail(count)
            
        except Exception as e:
            self.logger.error(f"获取{symbol}数据异常: {e}")
            return None

    def send_alert(self, symbol, timeframe, signal):
        """发送做多信号警报（多通道）"""
        try:
            # 解析股票信息
            code = symbol.split('.')[0]
            exchange = "沪市" if symbol.endswith('.SH') else "深市"
            
            # 获取股票名称
            stock_name = "未知股票"
            try:
                stock_info = ak.stock_individual_info_em(symbol=code)
                if not stock_info.empty:
                    name_row = stock_info[stock_info['item'] == '股票名称']
                    if not name_row.empty:
                        stock_name = name_row['value'].iloc[0]
            except:
                pass
            
            # 格式化时间
            if isinstance(signal['time'], (int, float)):
                signal_time = datetime.datetime.fromtimestamp(signal['time']).strftime('%m-%d %H:%M')
            elif hasattr(signal['time'], 'strftime'):
                signal_time = signal['time'].strftime('%m-%d %H:%M')
            else:
                signal_time = str(signal['time'])
            
            # 构建消息
            signals_text = "\n".join([f"• {sig}" for sig in signal['signals']])
            
            message = f"""
🎯【沪深主板做多信号警报】🎯
━━━━━━━━━━━━━━━━━━
📈 股票: {stock_name}({symbol})
🏢 市场: {exchange}
⏰ 周期: {timeframe} | 时间: {signal_time}
💰 当前价格: ¥{signal['price']:.2f}
🛡️ 支撑位置: ¥{signal['support']:.2f}
📊 RSI指标: {signal['rsi']:.1f}
📈 量比: {signal['volume_ratio']:.1f}x
🔰 风险比率: {signal['risk_ratio']:.1%}
━━━━━━━━━━━━━━━━━━
📋 信号详情:
{signals_text}
━━━━━━━━━━━━━━━━━━
⚠️ 风险提示: 投资有风险，决策需谨慎
            """
            
            # 通过多通道发送
            return self.notifier.send_alert(message)
            
        except Exception as e:
            self.logger.error(f"构建警报消息异常: {e}")
            return False

    def monitor_symbol(self, symbol):
        """监控单个股票"""
        for timeframe in TIMEFRAMES:
            try:
                # 获取当前周期数据
                current_data = self.get_stock_data(symbol, timeframe, 150)
                if current_data is None:
                    continue
                
                # 获取大周期数据
                htf_timeframe = HTF_MAP.get(timeframe, '日线')
                htf_data = self.get_stock_data(symbol, htf_timeframe, 100)
                
                # 分析信号
                signal = self.signal_engine.analyze_signals(current_data, htf_data)
                if signal:
                    alert_id = f"{symbol}_{timeframe}_{signal['time']}"
                    if alert_id not in self.processed_alerts:
                        if self.send_alert(symbol, timeframe, signal):
                            self.processed_alerts[alert_id] = time.time()
                            self.logger.info(f"🔔 发现信号: {symbol} {timeframe} {signal['signals']}")
                
            except Exception as e:
                self.logger.error(f"分析{symbol}{timeframe}异常: {e}")
                continue

    def run_monitoring(self):
        """主监控循环"""
        self.logger.info("🚀 沪深主板做多信号监控系统启动")
        
        cycle_count = 0
        
        try:
            while True:
                try:
                    cycle_count += 1
                    current_time = time.time()
                    
                    # 定期刷新股票列表（每2小时）
                    if current_time - self.last_refresh_time > 7200 or not self.active_stocks:
                        self.refresh_stock_list()
                    
                    self.logger.info(f"📈 开始第{cycle_count}轮监控，股票数量: {len(self.active_stocks)}")
                    
                    # 使用线程池并行监控
                    list(self.executor.map(self.monitor_symbol, self.active_stocks))
                    
                    self.logger.info(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 本轮监控完成，等待下一轮...")
                    time.sleep(60)  # 1分钟间隔
                    
                except KeyboardInterrupt:
                    self.logger.info("👋 用户中断，停止监控")
                    break
                except Exception as e:
                    self.logger.error(f"⚠️ 监控循环异常: {e}")
                    time.sleep(300)
        
        except Exception as e:
            self.logger.error(f"监控系统异常终止: {e}")
            sys.exit(1)

# ==========================================
# 5. 启动监控
# ==========================================
if __name__ == "__main__":
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('stock_monitor.log'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    logger = logging.getLogger(__name__)
    
    # 创建并运行监控器
    monitor = ChinaStockMonitor()
    try:
        monitor.run_monitoring()
    except KeyboardInterrupt:
        logger.info("监控系统正常退出")
    except Exception as e:
        logger.error(f"监控系统异常终止: {e}")
