#!/usr/bin/env python3
"""
沪深主板股票监控系统 - 专业修复版
修复属性缺失和变量未定义问题
"""

import os
import sys
import time
import datetime
import logging
import requests
import numpy as np
import pandas as pd
import akshare as ak
from threading import Lock

# ==========================================
# 1. 配置参数
# ==========================================
TG_TOKEN = '8553821769:AAHysPPPMydLiF1A1l2ab8xRrrBWfSv-kno'
CHAT_ID = '406894294'

# 监控参数
TOP_N_STOCKS = 100           # 监控前100只活跃股票
VOLUME_THRESHOLD = 5e8       # 5亿成交额阈值
MIN_PRICE = 2.0              # 最低股价
MAX_PRICE = 500.0            # 最高股价
CACHE_DURATION = 300         # 缓存持续时间(秒)
REQUEST_DELAY = 1.0          # 请求间隔(秒)

# 时间周期配置
TIMEFRAMES = ['60', '日线']
HTF_MAP = {'60': '日线', '日线': '周线'}

# ==========================================
# 2. 日志配置
# ==========================================
def setup_logging():
    """设置日志系统"""
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    log_file = os.path.join(log_dir, f"stock_monitor_{datetime.datetime.now().strftime('%Y%m%d')}.log")
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

# ==========================================
# 3. 沪深股票监控引擎（修复版）
# ==========================================
class ChinaStockMonitor:
    def __init__(self):
        """初始化所有必要属性"""
        self.stock_cache = {}
        self.htf_cache = {}
        self.processed_alerts = {}  # 修复缺失的属性
        self.score_cache = {}
        self.cache_lock = Lock()
        self.last_refresh_time = 0
        self.active_stocks = []
        self.request_count = 0
        self.start_time = time.time()
        
        logger.info("沪深主板量化监控系统初始化完成")

    def get_active_stocks(self):
        """新增方法：获取活跃股票列表"""
        try:
            logger.info("开始筛选活跃股票...")
            self.safe_request()
            
            # 获取A股实时数据
            spot_data = ak.stock_zh_a_spot_em()
            
            if spot_data is None or spot_data.empty:
                logger.warning("获取实时行情数据为空，使用默认股票")
                return self.get_default_stocks()
            
            # 数据清洗
            spot_data = spot_data.copy()
            numeric_cols = ['最新价', '涨跌幅', '成交量', '成交额']
            for col in numeric_cols:
                if col in spot_data.columns:
                    spot_data[col] = pd.to_numeric(spot_data[col], errors='coerce')
            
            # 过滤条件
            filtered = spot_data[
                (spot_data['成交额'] > VOLUME_THRESHOLD) &
                (spot_data['最新价'] > MIN_PRICE) &
                (spot_data['最新价'] < MAX_PRICE) &
                (~spot_data['代码'].str.startswith(('300', '688', '8')))  # 排除创业板、科创板和北交所
            ].sort_values('成交额', ascending=False)
            
            if filtered.empty:
                logger.warning("有效股票列表为空，使用默认股票")
                return self.get_default_stocks()
            
            # 格式化股票代码
            stocks = []
            for _, row in filtered.head(TOP_N_STOCKS).iterrows():
                code = row['代码']
                stocks.append(f"{code}.SH" if code.startswith('6') else f"{code}.SZ")
            
            logger.info(f"获取活跃股票列表成功: {len(stocks)}只")
            return stocks
            
        except Exception as e:
            logger.error(f"获取股票列表异常: {e}")
            return self.get_default_stocks()
    
    def get_default_stocks(self):
        """获取默认蓝筹股列表"""
        return [
            '600036.SH', '601318.SH', '600519.SH', '000858.SZ',
            '000333.SZ', '000651.SZ', '600276.SH', '601888.SH'
        ]

    def safe_request(self):
        """安全的请求控制"""
        current_time = time.time()
        elapsed = current_time - self.start_time
        
        # 控制请求频率（每分钟不超过30次）
        if self.request_count > 0 and elapsed < 60:
            time_to_wait = max(REQUEST_DELAY, (60 - elapsed) / self.request_count)
            time.sleep(time_to_wait)
        
        self.request_count += 1
        
        # 每小时重置计数器
        if elapsed > 3600:
            self.request_count = 0
            self.start_time = current_time

    def get_stock_data(self, symbol, period='日线', count=100):
        """安全获取股票K线数据（修复变量未定义问题）"""
        try:
            df = None  # 确保变量正确定义
            
            # 解析股票代码
            if '.' in symbol:
                code, exchange = symbol.split('.')
                stock_code = code
            else:
                stock_code = symbol
                code = symbol
            
            cache_key = f"{symbol}_{period}"
            current_time = time.time()
            
            # 检查缓存
            with self.cache_lock:
                if cache_key in self.stock_cache:
                    cached_data, cache_time = self.stock_cache[cache_key]
                    if current_time - cache_time < CACHE_DURATION:
                        return cached_data
            
            # 获取数据
            if period == '日线':
                df = ak.stock_zh_a_hist(
                    symbol=stock_code,
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
                try:
                    period_map = {'60': '60', '30': '30', '15': '15'}
                    if period in period_map:
                        df = ak.stock_zh_a_hist_min_em(
                            symbol=stock_code,
                            period=period_map[period],
                            adjust='hfq'
                        )
                        if df is not None and not df.empty:
                            df = df.rename(columns={
                                '时间': 'datetime', '开盘': 'open', '收盘': 'close',
                                '最高': 'high', '最低': 'low', '成交量': 'volume'
                            })
                except Exception as e:
                    logger.warning(f"获取{symbol} {period}分钟数据失败: {e}")
                    return None
            
            if df is None or df.empty:
                logger.warning(f"获取{symbol} {period}数据为空")
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
                logger.warning(f"{symbol} {period}数据量不足: {len(df)}条")
                return None
            
            # 更新缓存
            with self.cache_lock:
                self.stock_cache[cache_key] = (df.tail(count), current_time)
            
            return df.tail(count)
            
        except Exception as e:
            logger.error(f"获取{symbol}数据异常: {e}")
            return None

    def analyze_signals(self, df, htf_df):
        """分析做多信号（修复属性访问问题）"""
        if df is None or len(df) < 100:
            return None
            
        try:
            # 确保所有技术指标存在
            required_columns = ['close', 'sma20', 'sma55', 'sma89', 'sma144', 'rsi14', 'macd', 'volume', 'volume_sma20']
            if not all(col in df.columns for col in required_columns):
                logger.warning("技术指标数据不完整")
                return None
            
            current_idx = len(df) - 1
            current_close = df['close'].iloc[current_idx]
            current_rsi = df['rsi14'].iloc[current_idx]
            current_macd = df['macd'].iloc[current_idx]
            current_volume = df['volume'].iloc[current_idx]
            avg_volume = df['volume_sma20'].iloc[current_idx]
            
            # 信号分析逻辑...
            signals = []
            
            # 更新processed_alerts
            alert_id = f"{df['symbol'].iloc[0]}_{datetime.datetime.now().strftime('%Y%m%d%H%M')}"
            if alert_id not in self.processed_alerts:
                self.processed_alerts[alert_id] = time.time()
            
            return {
                'time': df['datetime'].iloc[current_idx],
                'price': current_close,
                'signals': signals,
                # 其他信号数据...
            }
            
        except Exception as e:
            logger.error(f"分析信号异常: {e}")
            return None

    def run_monitoring(self):
        """主监控循环（修复属性初始化问题）"""
        logger.info("🚀 沪深主板做多信号监控系统启动")
        
        # 确保所有属性已初始化
        if not hasattr(self, 'processed_alerts'):
            self.processed_alerts = {}
        
        cycle_count = 0
        
        while True:
            try:
                cycle_count += 1
                current_time = time.time()
                
                # 定期刷新股票列表（每2小时）
                if current_time - self.last_refresh_time > 7200 or not self.active_stocks:
                    logger.info("🔄 刷新股票监控列表...")
                    self.active_stocks = self.get_active_stocks()
                    self.last_refresh_time = current_time
                    self.stock_cache.clear()
                
                logger.info(f"📈 开始第{cycle_count}轮监控，股票数量: {len(self.active_stocks)}")
                
                # 监控逻辑...
                time.sleep(60)
                
            except KeyboardInterrupt:
                logger.info("👋 用户中断，停止监控")
                break
            except Exception as e:
                logger.error(f"⚠️ 监控系统异常: {e}")
                time.sleep(300)

# ==========================================
# 4. 启动监控
# ==========================================
if __name__ == "__main__":
    monitor = ChinaStockMonitor()
    monitor.run_monitoring()
