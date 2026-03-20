# ⚽ Prediction Market Liquidity Comparator

实时对比 Polymarket、Kalshi、Betfair 等预测市场平台上足球事件的流动性（Order Book）。

## 功能

- 创建统一事件映射，将不同市场的同一足球事件关联
- 实时获取各市场 Order Book 数据
  - Polymarket: WebSocket 实时推送
  - Kalshi: 每 5 秒轮询
  - Betfair: 每 10 秒轮询（通过 The Odds API）
- 并排对比展示 Bid/Ask 深度、价格、成交量
- 流动性汇总表（Bid Depth / Ask Depth / Spread）
- 自动匹配不同市场的同一赛事（队名 + 时间算法）
- 支持动态添加新市场适配器

## 环境要求

- Python 3.12+ (推荐 Conda)
- Node.js 18+
- MySQL 8.0+ (AWS RDS 或本地)

## 快速启动

### 1. 创建 Conda 环境

```bash
conda env create -f environment.yml
conda activate pm-liquidity
```

如果 pip 依赖未自动安装，手动补充：

```bash
pip install "sqlalchemy[asyncio]>=2.0" aiomysql pymysql
```

### 2. 配置环境变量

```bash
cp backend/.env.example backend/.env
```

编辑 `backend/.env`，填入：

| 变量 | 说明 | 必填 |
|------|------|------|
| `db_host` | MySQL 数据库地址 | ✅ |
| `db_port` | MySQL 端口 (默认 3306) | ✅ |
| `db_user` | 数据库用户名 | ✅ |
| `db_passwd` | 数据库密码 | ✅ |
| `db_name` | 数据库名 | ✅ |
| `POLYMARKET_API_KEY` | Polymarket API key (公开数据无需) | ❌ |
| `KALSHI_API_KEY` | Kalshi API key (公开数据无需) | ❌ |
| `ODDS_API_KEY` | The Odds API key (Betfair 数据) | ⚠️ Betfair 需要 |

Betfair 数据通过 [The Odds API](https://the-odds-api.com) 获取，免费 tier 500 requests/month。注册后获取 API key 填入 `ODDS_API_KEY`。

### 3. 初始化数据库（建表 + 数据同步）

首次运行需要先建表：

```bash
conda activate pm-liquidity
cd backend
python -c "
import asyncio
from database import engine, Base
async def create():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print('Tables created')
asyncio.run(create())
"
```

### 4. 数据同步（拉取赛事 + 自动匹配映射）

```bash
conda activate pm-liquidity
cd backend
python init_sync.py
```

`init_sync.py` 会依次执行：
1. 清理旧事件数据（保留已有的 kalshi/betfair 映射）
2. 从 Polymarket 拉取所有活跃足球赛事
3. 批量写入数据库（events + polymarket mappings）
4. 自动匹配 Kalshi 映射（通过队名 + 时间算法）
5. 自动匹配 Betfair 映射（需要 `ODDS_API_KEY`，未配置则跳过）
6. 输出汇总统计

后续可随时重新执行 `python init_sync.py` 刷新数据。

也可以通过 API 触发在线同步（不停服）：

```bash
curl -X POST http://localhost:8000/api/events/sync
```

### 5. 构建前端

```bash
cd frontend
npm install
npm run build
```

### 6. 启动服务

开发模式：
```bash
cd backend
conda activate pm-liquidity
python main.py
```

生产模式：
```bash
cd backend
conda activate pm-liquidity
gunicorn main:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers 2 \
  --bind 0.0.0.0:8000
```

访问 http://localhost:8000

### 7. 定时同步

服务启动后会自动每 6 小时同步一次 Polymarket 新赛事并清理已结束赛事。可通过环境变量调整：

```bash
export SYNC_INTERVAL_HOURS=6  # 默认 6 小时
```

## 数据同步机制

### 同步方式汇总

| 方式 | 命令 | 说明 |
|------|------|------|
| 初始化同步 | `python init_sync.py` | 全量同步，适合首次部署或数据重建 |
| API 在线同步 | `POST /api/events/sync` | 增量同步，不停服 |
| 自动定时同步 | 服务启动后自动执行 | 每 6 小时自动拉取 + 清理 + 匹配 |
| 单市场匹配 | `POST /api/automatch/{market}` | 对指定市场重新执行自动匹配 |
| 全市场匹配 | `POST /api/automatch` | 对所有非 polymarket 市场执行匹配 |
| 页面手动匹配 | 详情页 "Link Another Market" | 搜索或粘贴 event ID 手动关联 |

### 各市场数据源

| 市场 | 赛事来源 | Orderbook 来源 | 实时方式 |
|------|----------|----------------|----------|
| Polymarket | Gamma API (`tag_id=100350`) | CLOB WebSocket | WS 实时推送 |
| Kalshi | REST API (`/series` + `/events`) | REST API (`/orderbook`) | 5 秒轮询 |
| Betfair | The Odds API (`/events`) | The Odds API (`/odds`) | 10 秒轮询 |

## 架构

```
backend/
├── main.py          # FastAPI + WebSocket 实时推送
├── models.py        # Pydantic 数据模型
├── mapping.py       # 事件映射管理 (MySQL)
├── database.py      # SQLAlchemy async ORM
├── automatch.py     # 自动匹配算法（队名+时间）
├── init_sync.py     # 初始化同步脚本（pymysql 同步版）
├── init_data.py     # 数据初始化工具
└── markets/
    ├── base.py      # 适配器基类
    ├── polymarket.py # Polymarket CLOB API
    ├── kalshi.py    # Kalshi REST API
    ├── betfair.py   # Betfair via The Odds API
    └── registry.py  # 市场注册中心

frontend/src/
├── App.jsx          # 主应用（联赛侧边栏 + 事件列表 + 详情页）
├── api.js           # API + WebSocket 客户端
├── style.css
└── components/
    ├── LeagueSidebar.jsx   # 联赛分组侧边栏
    ├── EventDashboard.jsx  # 事件卡片网格
    ├── EventDetail.jsx     # 详情页 + 映射管理 + Order Book 对比
    ├── OrderBookChart.jsx  # Order Book 可视化
    └── ComparisonView.jsx  # 对比视图
```

## 数据库表结构

| 表 | 说明 |
|------|------|
| `events` | 赛事事件（以 Polymarket 为基准） |
| `leagues` | 联赛分组统计 |
| `market_mappings` | 跨市场映射（unified_id + market_name 唯一约束） |

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/leagues | 获取联赛列表 |
| GET | /api/leagues/{league}/events | 获取联赛下的赛事列表 |
| POST | /api/events/sync | 触发同步（拉取 + 清理 + 匹配） |
| GET | /api/events/{id}/mapping | 获取事件映射详情 |
| PUT | /api/events/{id}/mapping | 添加市场映射 |
| DELETE | /api/events/{id}/mapping/{name} | 移除市场映射 |
| GET | /api/events/{id}/orderbooks | REST 获取 Order Book |
| WS | /ws/orderbooks/{id} | WebSocket 实时 Order Book |
| GET | /api/markets | 列出可用市场 |
| GET | /api/markets/{name}/search | 搜索市场事件 |
| POST | /api/automatch | 全市场自动匹配 |
| POST | /api/automatch/{name} | 单市场自动匹配 |
| POST | /api/events/cleanup | 清理已结束事件 |

## 添加新市场

1. 在 `backend/markets/` 创建新适配器，继承 `BaseMarketAdapter`
2. 实现 `fetch_order_book`、`fetch_event`、`search_soccer_events`
3. 在 `registry.py` 的 `create_default` 中注册
4. 在 `main.py` 的 WebSocket 端点中添加轮询逻辑（参考 `_kalshi_poll_stream`）

## 部署

### Docker

```bash
docker compose up -d
```

### 手动部署

参考上方"快速启动"步骤，使用 systemd + nginx 管理：

```bash
sudo cp deploy/pm-liquidity.service /etc/systemd/system/
sudo systemctl enable --now pm-liquidity
sudo cp deploy/nginx.conf /etc/nginx/sites-available/pm-liquidity
sudo ln -s /etc/nginx/sites-available/pm-liquidity /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```
