"""
Streamlit app (single-file) for live tick ingestion, resampling, analytics, alerts and export.

Run:
    streamlit run app.py

Core features:
- WebSocket ingestion from Binance public combined trade streams
- SQLite persistence (ticks.db)
- In-memory recent ticks for live analytics (deque per symbol)
- Resampling selectable: '1s', '1min', '5min'
- Analytics: price stats, OLS hedge ratio, spread, z-score, ADF test, rolling correlation
- Live charts using Plotly; UI auto-refresh (default 500 ms)
- Alerts (e.g., z-score > threshold); one-shot by default
- CSV export of raw ticks and resampled analytics
"""

import streamlit as st
import threading, time, queue, sqlite3, json
from collections import deque, defaultdict
from datetime import datetime, timezone
import pandas as pd
import numpy as np
import statsmodels.api as sm
from statsmodels.tsa.stattools import adfuller
import websocket  # websocket-client
import plotly.graph_objs as go
import io

# -------------------------
# Config / defaults
# -------------------------
DB_FILE = "ticks.db"
DEFAULT_SYMBOLS = ["btcusdt", "ethusdt"]  # minimal default pair; can be extended
RECENT_MAX = 100_000  # keep last N ticks per symbol in memory
WS_PING = 20

# -------------------------
# Thread-safe queues & containers
# -------------------------
tick_q = queue.Queue()  # raw ticks from websocket
recent_ticks = defaultdict(lambda: deque(maxlen=RECENT_MAX))  # symbol -> deque of (ts_ms, price, qty)
_alerts_threadsafe = []  # list of active alert dicts (thread-safe append/remove with lock)
_alerts_lock = threading.Lock()
_alerts_fired = deque(maxlen=200)  # store fired alerts to show in UI
_db_lock = threading.Lock()

# -------------------------
# Utility / DB helpers
# -------------------------
def init_db():
    with _db_lock:
        conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS ticks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                ts INTEGER,
                price REAL,
                qty REAL
            )
        ''')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_ticks_symbol_ts ON ticks(symbol, ts)')
        conn.commit()
        conn.close()

def insert_tick_db(symbol, ts_ms, price, qty):
    with _db_lock:
        conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        cur = conn.cursor()
        cur.execute("INSERT INTO ticks(symbol, ts, price, qty) VALUES (?, ?, ?, ?)",
                    (symbol, int(ts_ms), float(price), float(qty)))
        conn.commit()
        conn.close()

def query_ticks_db(symbol, limit=None):
    with _db_lock:
        conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        cur = conn.cursor()
        if limit:
            cur.execute("SELECT ts, price, qty FROM ticks WHERE symbol=? ORDER BY ts DESC LIMIT ?",
                        (symbol, limit))
            rows = cur.fetchall()
            rows = list(reversed(rows))
        else:
            cur.execute("SELECT ts, price, qty FROM ticks WHERE symbol=? ORDER BY ts ASC", (symbol,))
            rows = cur.fetchall()
        conn.close()
    return rows

# -------------------------
# Binance WebSocket ingestion
# -------------------------
def build_stream_url(symbols):
    streams = "/".join([f"{s}@trade" for s in symbols])
    return f"wss://stream.binance.com:9443/stream?streams={streams}"

def _on_message(ws, message):
    try:
        msg = json.loads(message)
        if 'data' in msg:
            d = msg['data']
            ts = d.get('E', int(time.time()*1000))
            symbol = d.get('s', '').lower()
            price = float(d.get('p', 0.0))
            qty = float(d.get('q', 0.0))
            tick_q.put((symbol, ts, price, qty))
    except Exception as e:
        print("WS on_message error:", e)

def _on_error(ws, error):
    print("WS error:", error)

def _on_close(ws, close_status_code, close_msg):
    print("WS closed:", close_status_code, close_msg)

def websocket_thread(symbols_getter):
    """
    symbols_getter: callable returning current list of symbols (lowercase)
    This thread keeps a websocket connection open to Binance combined stream for those symbols.
    If symbol list changes, reconnects.
    """
    ws = None
    current_symbols = None
    while True:
        try:
            symbols = symbols_getter()
            symbols_sorted = sorted([s.lower() for s in symbols])
            if not symbols_sorted:
                time.sleep(1.0)
                continue
            if symbols_sorted != current_symbols:
                # reconnect
                if ws:
                    try:
                        ws.close()
                    except:
                        pass
                url = build_stream_url(symbols_sorted)
                ws = websocket.WebSocketApp(url,
                                            on_message=_on_message,
                                            on_error=_on_error,
                                            on_close=_on_close)
                # run_forever is blocking; run it in a subthread so outer loop can continue to check for symbol changes
                def run_ws():
                    ws.run_forever(ping_interval=WS_PING, ping_timeout=10)
                t = threading.Thread(target=run_ws, daemon=True)
                t.start()
                current_symbols = symbols_sorted
                print("WS connected to:", current_symbols)
            time.sleep(2.0)
        except Exception as e:
            print("websocket_thread exception:", e)
            time.sleep(3.0)

# -------------------------
# Tick consumer: persist and keep in-memory
# -------------------------
def tick_consumer_thread():
    while True:
        try:
            symbol, ts, price, qty = tick_q.get()
            recent_ticks[symbol].append((ts, price, qty))
            insert_tick_db(symbol, ts, price, qty)
        except Exception as e:
            print("tick_consumer error:", e)
            time.sleep(0.1)

# -------------------------
# Analytics helpers
# -------------------------
def ticks_to_df(symbol, ticks):
    """
    ticks: iterable of (ts_ms, price, qty)
    returns DataFrame indexed by datetime
    """
    if not ticks:
        return pd.DataFrame(columns=['ts', 'price', 'qty']).set_index(pd.DatetimeIndex([]))
    df = pd.DataFrame(list(ticks), columns=['ts', 'price', 'qty'])
    df['dt'] = pd.to_datetime(df['ts'], unit='ms').dt.tz_localize(None)
    df = df.set_index('dt')
    return df[['price', 'qty']]

def resample_ohlcv(df, timeframe):
    if df.empty:
        return pd.DataFrame()
    if timeframe == '1s':
        rule = '1S'
    elif timeframe == '1min':
        rule = '1T'
    elif timeframe == '5min':
        rule = '5T'
    else:
        rule = timeframe
    ohlc = df['price'].resample(rule).ohlc()
    vol = df['qty'].resample(rule).sum().rename('volume')
    out = ohlc.join(vol)
    out.dropna(subset=['close'], inplace=True)
    return out

def compute_price_stats(series):
    if series is None or series.empty:
        return {}
    return {
        'last': float(series.iloc[-1]),
        'mean': float(series.mean()),
        'std': float(series.std(ddof=0)),
        'min': float(series.min()),
        'max': float(series.max())
    }

def compute_ols(y, x):
    # y ~ beta * x + intercept
    try:
        X = sm.add_constant(x)
        model = sm.OLS(y, X, missing='drop').fit()
        beta = float(model.params[1])
        intercept = float(model.params[0])
        return beta, intercept, model
    except Exception as e:
        return None, None, None

def compute_spread_and_zscore(series_y, series_x, min_pts=10):
    joined = pd.concat([series_y, series_x], axis=1).dropna()
    if joined.shape[0] < min_pts:
        return None, None, None
    y = joined.iloc[:,0]
    x = joined.iloc[:,1]
    beta, intercept, model = compute_ols(y, x)
    if beta is None:
        return None, None, None
    spread = y - (beta * x + intercept)
    zscore = (spread - spread.mean()) / (spread.std(ddof=0) if spread.std(ddof=0) != 0 else 1.0)
    return spread, zscore, {'beta':beta, 'intercept':intercept}

def compute_adf(series, min_pts=10):
    if series is None or series.dropna().shape[0] < min_pts:
        return None
    try:
        res = adfuller(series.dropna().values, autolag='AIC')
        return {'adf_stat': float(res[0]), 'pvalue': float(res[1])}
    except Exception as e:
        return None

def rolling_corr(series_a, series_b, window):
    joined = pd.concat([series_a, series_b], axis=1).dropna()
    if joined.shape[0] < window:
        return pd.Series(dtype=float)
    return joined.iloc[:,0].rolling(window).corr(joined.iloc[:,1])

# -------------------------
# Alert engine (background)
# -------------------------
def alert_engine_thread(get_pair_series_callable, poll_interval=0.5):
    """
    get_pair_series_callable: returns (series_y, series_x, latest_time)
    active alerts in _alerts_threadsafe list (dicts): {'metric':'zscore', 'op':'>', 'value':float, 'pair':(y,x) or None}
    When fired, append to _alerts_fired deque.
    """
    while True:
        try:
            with _alerts_lock:
                alerts_copy = list(_alerts_threadsafe)
            if not alerts_copy:
                time.sleep(poll_interval)
                continue
            series_y, series_x, latest_ts = get_pair_series_callable()
            if series_y is None or series_x is None:
                time.sleep(poll_interval)
                continue
            # compute spread/zscore once per iteration
            spread, zscore_series, olsinfo = compute_spread_and_zscore(series_y, series_x, min_pts=20)
            latest_z = None
            if zscore_series is not None and not zscore_series.empty:
                latest_z = float(zscore_series.iloc[-1])
            for alert in alerts_copy:
                fired = False
                if alert.get('metric') == 'zscore':
                    if latest_z is None:
                        continue
                    op = alert.get('op')
                    val = float(alert.get('value', 0.0))
                    if op == '>' and latest_z > val:
                        fired = True
                    elif op == '<' and latest_z < val:
                        fired = True
                # extend here for more metrics
                if fired:
                    fired_entry = {
                        'alert': alert,
                        'ts': int(time.time()*1000),
                        'latest_z': latest_z
                    }
                    _alerts_fired.appendleft(fired_entry)
                    # remove one-shot alert
                    with _alerts_lock:
                        try:
                            _alerts_threadsafe.remove(alert)
                        except ValueError:
                            pass
            time.sleep(poll_interval)
        except Exception as e:
            print("alert_engine error:", e)
            time.sleep(0.5)

# -------------------------
# Background starters and helper to get data for alerts
# -------------------------
def start_backgrounds(symbols_getter_callable):
    # init DB
    init_db()
    # start websocket management thread
    if not st.session_state.get('_bg_ws_started'):
        t_ws = threading.Thread(target=websocket_thread, args=(symbols_getter_callable,), daemon=True)
        t_ws.start()
        st.session_state['_bg_ws_started'] = True
        print("Started websocket manager thread")
    # start tick consumer
    if not st.session_state.get('_bg_tick_consumer'):
        t_cons = threading.Thread(target=tick_consumer_thread, daemon=True)
        t_cons.start()
        st.session_state['_bg_tick_consumer'] = True
        print("Started tick consumer thread")
    # start alert engine
    if not st.session_state.get('_bg_alert_engine'):
        def get_pair_series():
            # default pair from session_state
            sA = st.session_state.get('symbol_a', DEFAULT_SYMBOLS[0])
            sB = st.session_state.get('symbol_b', DEFAULT_SYMBOLS[1]) if len(DEFAULT_SYMBOLS) > 1 else None
            dfA = ticks_to_df(sA, recent_ticks[sA])
            dfB = ticks_to_df(sB, recent_ticks[sB]) if sB else pd.DataFrame()
            # resample to 1s for alignment for alerts
            sA1 = resample_ohlcv(dfA, '1s')['close'] if not dfA.empty else None
            sB1 = resample_ohlcv(dfB, '1s')['close'] if not dfB.empty else None
            latest_ts = int(time.time()*1000)
            return sA1, sB1, latest_ts
        t_alert = threading.Thread(target=alert_engine_thread, args=(get_pair_series,), daemon=True)
        t_alert.start()
        st.session_state['_bg_alert_engine'] = True
        print("Started alert engine thread")

# -------------------------
# Streamlit UI & main loop
# -------------------------
st.set_page_config(page_title="Quant Live - Streamlit", layout="wide", initial_sidebar_state="expanded")
st.title("Quant Live Analytics — Core (Streamlit)")

# Sidebar controls
st.sidebar.header("Controls")

# Symbol inputs
available_default = DEFAULT_SYMBOLS.copy()
# Optionally allow user to input additional symbols comma-separated
custom_symbols = st.sidebar.text_input("Extra symbols (comma separated, e.g. 'bnbusdt')", value="")
extra = [s.strip().lower() for s in custom_symbols.split(",") if s.strip()]
symbols = sorted(list({*(s.lower() for s in available_default), *extra}))
if len(symbols) < 2:
    # allow at least two symbols for pair analytics
    # ensure default has two
    symbols = sorted(list({*symbols, *DEFAULT_SYMBOLS}))

symbol_a = st.sidebar.selectbox("Symbol A", symbols, index=0, key='symbol_a')
symbol_b = st.sidebar.selectbox("Symbol B", symbols, index=1 if len(symbols) > 1 else 0, key='symbol_b')

timeframe = st.sidebar.selectbox("Resample timeframe", ['1s', '1min', '5min'], index=0, key='timeframe')

autorefresh_ms = st.sidebar.slider("Live refresh (ms)", min_value=200, max_value=5000, value=500, step=100)

# alert builder
st.sidebar.markdown("### Alerts")
alert_metric = st.sidebar.selectbox("Metric", ['zscore'], index=0)
alert_op = st.sidebar.selectbox("Operator", ['>', '<'], index=0)
alert_value = st.sidebar.number_input("Value", value=2.0, format="%.4f")
if st.sidebar.button("Add Alert"):
    alert = {'metric': alert_metric, 'op': alert_op, 'value': float(alert_value),
             'pair': (symbol_a, symbol_b), 'created_ts': int(time.time()*1000)}
    with _alerts_lock:
        _alerts_threadsafe.append(alert)
    st.sidebar.success(f"Alert added: {alert_metric} {alert_op} {alert_value} for pair {symbol_a}/{symbol_b}")

# start/stop ingestion (simple toggle that only controls visibility; background threads auto-start)
start_btn = st.sidebar.button("Start ingestion (background)")
# show DB status
st.sidebar.markdown("---")
st.sidebar.write("Persistence DB:", DB_FILE)
db_count = None
try:
    rows = query_ticks_db(symbol_a, limit=1)
    db_count = len(query_ticks_db(symbol_a, limit=100))
except Exception:
    db_count = "N/A"
st.sidebar.write("Recent rows for A (approx):", db_count)

# Start backgrounds (idempotent)
def symbols_getter():
    # always return current selected symbols; include both
    s = [symbol_a, symbol_b]
    # include any extras typed
    for ex in extra:
        if ex and ex not in s:
            s.append(ex)
    return s

start_backgrounds(symbols_getter)

# Layout: left = charts, right = stats + controls
col1, col2 = st.columns([3, 1])

# Live refresh trigger
# Use st.experimental_rerun via st_autorefresh
count = st.data_editor  # just to avoid linter; not used
# trigger reruns
if autorefresh_ms > 0:
    # st_autorefresh returns the number of times it has refreshed; we don't need to capture it
    st_autorefresh = st.experimental_rerun if False else None
    # Use the helper function st.experimental_get_query_params trick isn't necessary; instead use st.experimental_rerun pattern:
    # But Streamlit provides st.experimental_get_query_params and st.experimental_set_query_params;
    # Better: use the built-in st_autorefresh utility:
    from streamlit.runtime.scriptrunner import add_script_run_ctx  # may be private; safe fallback below
    try:
        # st_autorefresh exists in st; use it:
        refresh_count = st.query_params().get('_refresh_count', [0])[0]
    except Exception:
        refresh_count = 0
# Simpler: use st.experimental_memo with time-based change not needed. Instead use st.experimental_rerun with timer thread? Simpler:
# We'll use st.experimental_get_query_params hack: change query param to force rerun.
# But simpler and robust: use streamlit_autorefresh utility:
from streamlit_autorefresh import st_autorefresh

# call to auto-refresh every autorefresh_ms
_ = st_autorefresh(interval=autorefresh_ms, key="autorefresh")

# -------------------------
# Acquire data for selected symbols
# -------------------------
dfA = ticks_to_df(symbol_a, recent_ticks[symbol_a])
dfB = ticks_to_df(symbol_b, recent_ticks[symbol_b])

# Resample as per timeframe for plots (resampled OHLCV)
resA = resample_ohlcv(dfA, timeframe)
resB = resample_ohlcv(dfB, timeframe)

# Compute core analytics
price_stats_A = compute_price_stats(resA['close'] if not resA.empty else dfA['price'] if not dfA.empty else pd.Series())
price_stats_B = compute_price_stats(resB['close'] if not resB.empty else dfB['price'] if not dfB.empty else pd.Series())

# Pair analytics: use resampled series aligned to timeframe but compute zscore live with min samples
series_y = (resB['close'] if not resB.empty else None)
series_x = (resA['close'] if not resA.empty else None)
# fallback to 1s-resampled for zscore if selected timeframe is coarse but we need live zscore
if timeframe != '1s':
    # Prepare 1s aligned series for zscore live update (if available)
    sA_1s = resample_ohlcv(dfA, '1s')['close'] if not dfA.empty else None
    sB_1s = resample_ohlcv(dfB, '1s')['close'] if not dfB.empty else None
else:
    sA_1s = series_x
    sB_1s = series_y

spread, zscore_series, ols_info = compute_spread_and_zscore(series_y, series_x, min_pts=10)
# also compute zscore using 1s for live z if available
spread_1s, zscore_1s, ols_info_1s = compute_spread_and_zscore(sB_1s, sA_1s, min_pts=10)

adf_res = compute_adf(spread if spread is not None else spread_1s, min_pts=20)
rolling_corr_series = rolling_corr(series_x, series_y, window=30) if (series_x is not None and series_y is not None) else pd.Series(dtype=float)

# -------------------------
# Render charts
# -------------------------
with col1:
    st.subheader(f"Price charts — {symbol_a.upper()} & {symbol_b.upper()} (resample: {timeframe})")

    # Price Chart (Plotly)
    fig_price = go.Figure()
    # add A
    if not resA.empty:
        fig_price.add_trace(go.Candlestick(
            x=resA.index, open=resA['open'], high=resA['high'], low=resA['low'], close=resA['close'],
            name=symbol_a.upper()
        ))
    elif not dfA.empty:
        fig_price.add_trace(go.Scatter(x=dfA.index, y=dfA['price'], mode='lines', name=symbol_a.upper()))
    # add B
    if not resB.empty:
        fig_price.add_trace(go.Candlestick(
            x=resB.index, open=resB['open'], high=resB['high'], low=resB['low'], close=resB['close'],
            name=symbol_b.upper(), opacity=0.6
        ))
    elif not dfB.empty:
        fig_price.add_trace(go.Scatter(x=dfB.index, y=dfB['price'], mode='lines', name=symbol_b.upper()))
    fig_price.update_layout(height=420, margin=dict(t=40,b=20))
    st.plotly_chart(fig_price, use_container_width=True)

    # Spread chart
    st.subheader("Spread")
    fig_spread = go.Figure()
    if spread is not None:
        fig_spread.add_trace(go.Scatter(x=spread.index, y=spread.values, name='spread'))
    if spread_1s is not None:
        fig_spread.add_trace(go.Scatter(x=spread_1s.index, y=spread_1s.values, name='spread_1s', opacity=0.6))
    fig_spread.update_layout(height=300, margin=dict(t=30,b=20))
    st.plotly_chart(fig_spread, use_container_width=True)

    # Z-score (live)
    st.subheader("Z-score")
    fig_z = go.Figure()
    if zscore_series is not None:
        fig_z.add_trace(go.Scatter(x=zscore_series.index, y=zscore_series.values, name='zscore'))
    if zscore_1s is not None:
        fig_z.add_trace(go.Scatter(x=zscore_1s.index, y=zscore_1s.values, name='zscore_1s', opacity=0.6))
    fig_z.update_layout(height=220, margin=dict(t=30,b=20))
    st.plotly_chart(fig_z, use_container_width=True)

    # Rolling corr
    st.subheader("Rolling correlation (window=30)")
    fig_corr = go.Figure()
    if not rolling_corr_series.empty:
        fig_corr.add_trace(go.Scatter(x=rolling_corr_series.index, y=rolling_corr_series.values, name='rolling_corr'))
    fig_corr.update_layout(height=220, margin=dict(t=30,b=20))
    st.plotly_chart(fig_corr, use_container_width=True)

with col2:
    st.subheader("Key stats & controls")

    st.markdown("**Symbol A stats**")
    st.write(price_stats_A)
    st.markdown("**Symbol B stats**")
    st.write(price_stats_B)

    st.markdown("---")
    st.markdown("**Pair analytics (resampled)**")
    st.write("OLS info (beta, intercept):")
    st.write({k: (ols_info[k] if k in ols_info else None) for k in ('beta','intercept')} if ols_info else None)
    st.write("ADF (spread):")
    st.write(adf_res if adf_res else "Not enough data")

    st.markdown("---")
    st.subheader("Alerts (recent fired)")
    if _alerts_fired:
        for a in list(_alerts_fired)[:10]:
            ts = datetime.fromtimestamp(a['ts']/1000.0).strftime("%Y-%m-%d %H:%M:%S")
            st.warning(f"{ts} — Fired: {a['alert']['metric']} {a['alert']['op']} {a['alert']['value']}  — latest_z={a.get('latest_z'):.3f}")
    else:
        st.info("No alerts fired yet")

    st.markdown("---")
    st.subheader("Data export")
    # Export raw ticks for symbol A (last N rows)
    rowsA = query_ticks_db(symbol_a, limit=5000)
    if rowsA:
        df_rawA = pd.DataFrame(rowsA, columns=['ts', 'price', 'qty'])
        df_rawA['dt'] = pd.to_datetime(df_rawA['ts'], unit='ms')
        buf = io.StringIO()
        df_rawA.to_csv(buf, index=False)
        st.download_button("Download raw ticks (A) (up to 5000 rows)", buf.getvalue(), file_name=f"{symbol_a}_raw.csv", mime='text/csv')
    else:
        st.write("No raw ticks available yet for A")

    # Export processed resampled data (A)
    if not resA.empty:
        buf2 = io.StringIO()
        resA.to_csv(buf2)
        st.download_button("Download resampled (A)", buf2.getvalue(), file_name=f"{symbol_a}_{timeframe}.csv", mime='text/csv')
    else:
        st.write("No resampled data (A) yet")

    # simple controls for clearing data (optional)
    if st.button("Clear in-memory buffer (NOT DB)"):
        recent_ticks[symbol_a].clear()
        recent_ticks[symbol_b].clear()
        st.success("Cleared in-memory buffers for selected symbols")

# Footer / connection status
st.markdown("---")
conn_status = "🟢 Running (background ingestion & analytics)" if st.session_state.get('_bg_ws_started') else "🔴 Not running"
st.write(conn_status)
st.caption("Notes: Give the app a minute to collect data after starting. Binance public stream may throttle if too many symbols are subscribed.")

# -------------------------
# End of app
# -------------------------
