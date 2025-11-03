# 🧠 Quant Live Analytics Dashboard

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.20+-red.svg)](https://streamlit.io/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

A real-time quantitative trading dashboard that streams live cryptocurrency data from Binance, performs statistical analysis, and visualizes market dynamics with interactive charts. Built to simulate a professional quant research platform with production-ready architecture.

![Dashboard Demo][(https://via.placeholder.com/800x400.png?text=Dashboard+Screenshot](https://github.com/akash-deepak-varma/quant-live-analytics-dashboard/blob/main/Dash-board.png))

## 🚀 Overview

This project delivers a complete real-time analytics pipeline for cryptocurrency markets, featuring:

- **Live Data Streaming**: WebSocket connection to Binance for sub-second tick data
- **Advanced Analytics**: Statistical modeling, cointegration tests, and time-series analysis
- **Interactive Visualization**: Real-time charts with candlesticks, spreads, z-scores, and correlations
- **Custom Alerts**: User-defined threshold monitoring with instant notifications
- **Modular Architecture**: Clean separation between backend analytics engine and frontend UI

Perfect for quant researchers, algorithmic traders, and data scientists exploring high-frequency financial data.

## ✨ Features

### 📊 Core Capabilities

| Feature | Description |
|---------|-------------|
| **Live Data Ingestion** | Continuously streams tick-level trade data from Binance WebSocket API for multiple symbols |
| **Multi-Timeframe Support** | Real-time resampling to 1s, 1min, and 5min OHLCV bars |
| **Quantitative Analytics** | OLS regression, spread calculation, z-score, ADF stationarity test, rolling correlation |
| **Interactive Dashboard** | Auto-refreshing Plotly charts with candlesticks, line plots, and statistical overlays |
| **Smart Alerts Engine** | Custom alert conditions (e.g., "z-score > 2") with background monitoring |
| **Data Export** | Download raw ticks or resampled data in CSV format |
| **Graceful UI** | Smooth symbol switching with loading states and error handling |
| **Persistent Storage** | SQLite database for tick history and analytics replay |

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  Streamlit Frontend                     │
│                   (frontend/app.py)                     │
├─────────────────────────────────────────────────────────┤
│  • Symbol Selection & Timeframe Controls               │
│  • Live Candlestick & Price Charts                     │
│  • Spread, Z-Score, Correlation Plots                  │
│  • Real-time Statistics & Alert Display                │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│                  Backend Engine                         │
│                   (backend/*)                           │
├─────────────────────────────────────────────────────────┤
│  Ingestion Thread (ingestion.py)                       │
│   → Binance WebSocket connection                       │
│   → Tick data buffering (deque)                        │
│   → SQLite persistence                                  │
│                                                         │
│  Analytics Engine (analytics.py)                       │
│   → OHLCV resampling                                   │
│   → OLS regression (hedge ratio)                       │
│   → Spread & Z-score computation                       │
│   → ADF stationarity test                              │
│   → Rolling correlation                                 │
│                                                         │
│  Alerts Engine (alerts.py)                            │
│   → Background monitoring thread                       │
│   → Condition evaluation                               │
│   → Alert triggering & display                         │
└─────────────────────────────────────────────────────────┘
```

## 🧮 Analytics Methodology

| Metric | Description |
|--------|-------------|
| **Hedge Ratio (β)** | Linear regression coefficient from OLS: `Y = α + βX` |
| **Spread** | Residual from hedge: `spread = Y - (βX + α)` |
| **Z-Score** | Standardized spread: `(spread - μ) / σ` |
| **ADF Test** | Augmented Dickey-Fuller test for spread stationarity (cointegration) |
| **Rolling Correlation** | Pearson correlation between asset returns over sliding window (default: 30 periods) |
| **OHLCV Resampling** | Aggregates tick data into open-high-low-close-volume bars per timeframe |

## 🛠️ Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Frontend** | Streamlit | Interactive web UI and controls |
| **Visualization** | Plotly | Live interactive charts (candlesticks, spreads, etc.) |
| **Backend** | Python (threading + queues) | Real-time data pipeline |
| **WebSocket** | websocket-client | Binance market data stream |
| **Database** | SQLite3 | Persistent tick storage |
| **Data Processing** | Pandas, NumPy | Time-series manipulation and analytics |
| **Statistics** | Statsmodels | OLS regression, ADF test |
| **Auto-refresh** | streamlit-autorefresh | Live dashboard updates |

## 📁 Project Structure

```
quant_streamlit_app/
├── backend/
│   ├── __init__.py
│   ├── database.py        # SQLite schema and tick storage
│   ├── ingestion.py       # WebSocket client and data buffering
│   ├── analytics.py       # Statistical computations (OLS, z-score, etc.)
│   └── alerts.py          # Alert engine and condition evaluation
│
├── frontend/
│   ├── __init__.py
│   └── app.py             # Streamlit UI, charts, and user controls
│
├── ticks.db               # Auto-generated SQLite database
├── requirements.txt       # Python dependencies
├── README.md              # This file
└── .gitignore
```

## 🚀 Quick Start

### Prerequisites

- Python 3.8 or higher
- pip package manager
- Internet connection (for Binance WebSocket)

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/quant-live-analytics-dashboard.git
   cd quant-live-analytics-dashboard
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   
   # Linux/Mac
   source venv/bin/activate
   
   # Windows
   venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the dashboard**
   ```bash
   streamlit run frontend/app.py
   ```

5. **Open your browser**
   
   Navigate to `http://localhost:8501` (opens automatically)

## 💡 Usage Example

### Basic Workflow

1. **Select Trading Pairs**
   - Choose symbols from sidebar (e.g., BTCUSDT, ETHUSDT)
   - Data ingestion starts automatically

2. **Choose Timeframe**
   - Select 1s, 1min, or 5min resampling
   - View OHLC candlestick charts

3. **Monitor Analytics**
   - Price statistics (mean, std dev, min/max)
   - Hedge ratio and spread dynamics
   - Z-score trends and rolling correlation

4. **Set Custom Alerts**
   - Add alert: `metric=zscore, operator=>, value=2`
   - System highlights when condition triggers

5. **Export Data**
   - Download raw ticks or resampled bars
   - CSV format for offline analysis

### Sample Output

```
📊 Real-time Statistics
─────────────────────────
BTCUSDT Mean:    $43,521.45
BTCUSDT Std Dev: $127.89

📈 Hedge Ratio (β): 18.234
📉 Current Spread:  -0.045
⚡ Z-Score:         1.87
🔗 Correlation:     0.924
✅ ADF p-value:     0.023 (Stationary)
```

## 🎯 Key Highlights

- ⚡ **Sub-second latency** streaming with WebSocket
- 📊 **Multi-symbol support** with independent analytics
- 🧩 **Modular design** for easy extension and maintenance
- 🔄 **Auto-reconnection** on symbol changes
- 📈 **Production-ready** code with error handling
- 🎨 **Beautiful UI** with responsive Plotly charts
- 💾 **Data persistence** for historical analysis

## 🔮 Future Enhancements

- [ ] **Advanced Analytics**: Kalman filter hedge ratios, volatility modeling
- [ ] **Machine Learning**: Train models on z-score/correlation features
- [ ] **Alert Persistence**: Email/webhook notifications via database storage
- [ ] **REST API**: FastAPI backend for external consumption
- [ ] **Backtesting Engine**: Simulate trading strategies on historical data
- [ ] **Docker Support**: Containerized deployment for cloud platforms
- [ ] **Multi-exchange**: Support for Coinbase, Kraken, etc.
- [ ] **Portfolio Analytics**: Multi-asset risk and return metrics

## 📚 What You'll Learn

By exploring this project, you'll gain hands-on experience with:

- ✅ Real-time WebSocket data ingestion patterns
- ✅ Multi-threaded Python application design
- ✅ Time-series analytics and statistical modeling
- ✅ Clean architecture with backend/frontend separation
- ✅ Financial econometrics (OLS, cointegration, ADF tests)
- ✅ SQLite for persistent data storage
- ✅ Reactive web applications with Streamlit
- ✅ Production-ready error handling and logging

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request. For major changes:

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request



## 🙏 Acknowledgments

- Binance for providing free WebSocket API access
- Streamlit community for excellent documentation
- Statsmodels contributors for robust statistical tools


Project Link: [https://github.com/akash-deepak-varma/quant-live-analytics-dashboard](https://github.com/akash-deepak-varma/quant-live-analytics-dashboard)

---

**⭐ If you find this project useful, please consider giving it a star!**


Made with ❤️ by Akash

