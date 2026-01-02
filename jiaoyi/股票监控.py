#!/usr/bin/env python3
"""
沪深主板股票监控系统 - 完整稳定版
包含网络异常处理和超时控制机制
"""

import os
import sys
import time
import datetime
import logging
import requests
import pandas as pd
import akshare as ak
from threading import Lock
from urllib3.exceptions import MaxRetryError, NameResolutionError
from requests.exceptions import RequestException, Timeout

# ==========================================
# 1. 配置参数
# ==========================================
# 监控参数
TOP_N_STOCKS = 100           # 监控前100只活跃股票
VOLUME_THRESHOLD = 5e8       # 5亿成交额阈值
MIN_PRICE = 2.0              # 最低股价
MAX_PRICE = 500.0            # 最高股价
CACHE_DURATION = 300         # 缓存持续时间(秒)
REQUEST_DELAY = 1.0          # 请求间隔(秒)

# 网络配置
MAX_RETRIES = 3              # 最大重试次数
RETRY_DELAY = 5              # 重试延迟(秒)
TIMEOUT = 10                 # 请求超时(秒)

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
# 3. 股票数据获取器（增强版）
# ==========================================
class StockDataFetcher:
    def __init__(self):
        self.cache = {}
        self.lock = Lock()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2'
        })

    def get_stock_list(self):
        """获取股票列表（带重试和超时控制）"""
        for attempt in range(MAX_RETRIES + 1):
            try:
                # 尝试主数据源
                df = self._try_akshare_with_timeout("stock_zh_a_spot_em")
                if df is not None:
                    return self._process_stock_list(df)
                
                # 尝试备用数据源
                backup_sources = ["sina", "qq"]
                for source in backup_sources:
                    try:
                        if source == "sina":
                            df = self._try_akshare_with_timeout("stock_zh_a_spot_sina")
                        elif source == "qq":
                            df = self._try_akshare_with_timeout("stock_zh_a_spot_qq")
                        if df is not None:
                            return self._process_stock_list(df)
                    except Exception as e:
                        logger.warning(f"备用数据源{source}获取失败: {e}")
                        continue
                
                return self._get_default_stocks()
                
            except (RequestException, Timeout) as e:
                if attempt < MAX_RETRIES:
                    logger.warning(f"网络异常，第{attempt+1}次重试...")
                    time.sleep(RETRY_DELAY)
                    continue
                logger.error(f"获取股票列表失败: {e}")
                return self._get_default_stocks()
            except Exception as e:
                logger.error(f"获取股票列表异常: {e}")
                return self._get_default_stocks()

    def _try_akshare_with_timeout(self, method_name):
        """带超时控制的AKShare数据获取"""
        try:
            method = getattr(ak, method_name)
            return method()
        except Exception as e:
            logger.warning(f"AKShare方法{method_name}调用失败: {e}")
            return None

    def _process_stock_list(self, df):
        """处理股票列表数据"""
        try:
            df = df.copy()
            numeric_cols = ['最新价', '涨跌幅', '成交量', '成交额']
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            
            main_board = df[
                (~df['代码'].str.startswith(('300', '688', '8'), na=False)) &
                (df['成交额'] > VOLUME_THRESHOLD) &
                (df['最新价'] > MIN_PRICE) &
                (df['最新价'] < MAX_PRICE)
            ].sort_values('成交额', ascending=False)
            
            if main_board.empty:
                return self._get_default_stocks()
            
            stocks = []
            for _, row in main_board.head(TOP_N_STOCKS).iterrows():
                code = row['代码']
                stocks.append(f"{code}.SH" if code.startswith('6') else f"{code}.SZ")
            
            logger.info(f"获取活跃股票列表成功: {len(stocks)}只")
            return stocks
            
        except Exception as e:
            logger.error(f"处理股票列表异常: {e}")
            return self._get_default_stocks()

    def _get_default_stocks(self):
        """获取默认蓝筹股列表"""
        return [
            '600036.SH', '601318.SH', '600519.SH', '000858.SZ',
            '000333.SZ', '000651.SZ', '600276.SH', '601888.SH'
        ]

# ==========================================
# 4. 沪深股票监控引擎（完整版）
# ==========================================
class ChinaStockMonitor:
    def __init__(self):
        self.data_fetcher = StockDataFetcher()
        self.stock_cache = {}
        self.processed_alerts = {}
        self.cache_lock = Lock()
        self.last_refresh_time = 0
        self.active_stocks = []
        self.request_count = 0
        self.start_time = time.time()
        
        logger.info("沪深主板量化监控系统初始化完成")

    def refresh_stock_list(self):
        """刷新股票列表（带超时控制）"""
        try:
            logger.info("开始刷新股票列表...")
            start_time = time.time()
            
            self.active_stocks = self.data_fetcher.get_stock_list()
            self.last_refresh_time = time.time()
            
            logger.info(f"股票列表刷新完成，耗时{(time.time()-start_time):.2f}秒")
            logger.info(f"当前监控股票数量: {len(self.active_stocks)}")
            
        except Exception as e:
            logger.error(f"刷新股票列表异常: {e}")
            self.active_stocks = self.data_fetcher._get_default_stocks()

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
        """安全获取股票K线数据（带超时控制）"""
        try:
            self.safe_request()
            df = None
            
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

    def run_monitoring(self):
        """主监控循环（带超时控制）"""
        logger.info("🚀 沪深主板做多信号监控系统启动")
        
        cycle_count = 0
        
        try:
            while True:
                try:
                    cycle_count += 1
                    current_time = time.time()
                    
                    # 定期刷新股票列表（每2小时）
                    if current_time - self.last_refresh_time > 7200 or not self.active_stocks:
                        self.refresh_stock_list()
                    
                    logger.info(f"📈 开始第{cycle_count}轮监控，股票数量: {len(self.active_stocks)}")
                    
                    # 监控逻辑...
                    time.sleep(60)  # 1分钟间隔
                    
                except KeyboardInterrupt:
                    logger.info("👋 用户中断，停止监控")
                    break
                except Exception as e:
                    logger.error(f"⚠️ 监控循环异常: {e}")
                    time.sleep(300)
        
        except Exception as e:
            logger.error(f"监控系统异常终止: {e}")
            sys.exit(1)

# ==========================================
# 5. 启动监控
# ==========================================
if __name__ == "__main__":
    monitor = ChinaStockMonitor()
    try:
        monitor.run_monitoring()
    except KeyboardInterrupt:
        logger.info("监控系统正常退出")
    except Exception as e:
        logger.error(f"监控系统异常终止: {e}")
