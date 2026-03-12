# ⚽ Prediction Market Liquidity Comparator

实时对比 Polymarket、Kalshi、Betfair 等预测市场平台上足球事件的流动性（Order Book）。

## 功能

- 创建统一事件映射，将不同市场的同一足球事件关联
- 实时获取各市场 Order Book 数据（WebSocket 推送，5秒刷新）
- 并排对比展示 Bid/Ask 深度、价格、成交量
- 流动性汇总表（Bid Depth / Ask Depth / Spread）
- 支持动态添加新市场适配器

## 快速启动

### 后端
```bash
cd prediction-market-liquidity/backend
pip install -r requirements.txt
python main.py
```
API 运行在 http://localhost:8000

### 前端
```bash
cd prediction-market-liquidity/frontend
npm install
npm run dev
```
UI 运行在 http://localhost:5173

## 架构

```
backend/
├── main.py          # FastAPI + WebSocket
├── models.py        # 数据模型
├── mapping.py       # 事件映射存储 (JSON文件)
└── markets/
    ├── base.py      # 适配器基类
    ├── polymarket.py
    ├── kalshi.py
    ├── betfair.py
    └── registry.py  # 市场注册中心

frontend/src/
├── App.jsx
├── api.js           # API 客户端
├── style.css
└── components/
    ├── MappingManager.jsx   # 映射管理
    ├── ComparisonView.jsx   # 对比展示 + WebSocket
    └── OrderBookChart.jsx   # Order Book 可视化
```

## 添加新市场

1. 在 `backend/markets/` 创建新适配器，继承 `BaseMarketAdapter`
2. 实现 `fetch_order_book`、`fetch_event`、`search_soccer_events`
3. 在 `registry.py` 的 `create_default` 中注册

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/mappings | 列出所有事件映射 |
| POST | /api/mappings | 创建映射 |
| PUT | /api/mappings/{id}/market | 添加市场到映射 |
| DELETE | /api/mappings/{id}/market/{name} | 移除市场 |
| GET | /api/markets | 列出可用市场 |
| GET | /api/markets/{name}/search | 搜索市场事件 |
| GET | /api/compare/{id} | 获取对比数据 |
| WS | /ws/live/{id} | 实时推送 |
