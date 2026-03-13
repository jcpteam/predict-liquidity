# ⚽ Prediction Market Liquidity Comparator 

实时对比 Polymarket、Kalshi、Betfair 等预测市场平台上足球事件的流动性（Order Book）。

## 功能

- 创建统一事件映射，将不同市场的同一足球事件关联
- 实时获取各市场 Order Book 数据（WebSocket 推送，5秒刷新）
- 并排对比展示 Bid/Ask 深度、价格、成交量
- 流动性汇总表（Bid Depth / Ask Depth / Spread）
- 支持动态添加新市场适配器

## 环境要求

- Python 3.11+
- Node.js 18+
- npm 9+

## 快速启动（本地开发）

### 后端
```bash
cd backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # 编辑 .env 填入 API keys
python main.py
```
API 运行在 http://localhost:8000

### 前端
```bash
cd frontend
npm install
npm run dev
```
UI 运行在 http://localhost:5173

## 部署

### 方式一：一键脚本部署

项目根目录提供了部署脚本，支持本地构建 + 启动：

```bash
chmod +x deploy.sh
./deploy.sh
```

脚本会自动完成：前端构建 → 后端依赖安装 → 使用 Gunicorn 启动服务（端口 8000）。

### 方式二：Docker 部署

```bash
docker build -t prediction-market-liquidity .
docker run -d \
  --name pm-liquidity \
  -p 8000:8000 \
  --env-file backend/.env \
  prediction-market-liquidity
```

### 方式三：Docker Compose

```bash
docker compose up -d
```

访问 http://localhost:8000

### 方式四：Conda 部署

适合已有 Anaconda / Miniconda 环境的用户，可以用 conda 管理 Python 和 Node.js 依赖。

#### 1. 创建 conda 环境
```bash
conda create -n pm-liquidity python=3.12 nodejs=18 -y
conda activate pm-liquidity
```

#### 2. 安装后端依赖
```bash
cd backend
pip install -r requirements.txt
pip install gunicorn uvloop httptools
cp .env.example .env   # 编辑 .env 填入 API keys
```

#### 3. 构建前端
```bash
cd frontend
npm ci
npm run build
```

#### 4. 启动服务

开发模式：
```bash
cd backend
python main.py
```

生产模式：
```bash
cd backend
gunicorn main:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers 2 \
  --bind 0.0.0.0:8000
```

#### 导出环境（可选）

导出 conda 环境供团队复用：
```bash
conda env export > environment.yml
```

其他人恢复环境：
```bash
conda env create -f environment.yml
conda activate pm-liquidity
```

### 方式五：手动部署到 VPS / 云服务器

#### 1. 构建前端
```bash
cd frontend
npm ci
npm run build
# 产物在 frontend/dist/
```

#### 2. 部署后端
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install gunicorn
```

#### 3. 配置环境变量
```bash
cp backend/.env.example backend/.env
# 编辑 backend/.env 填入各市场 API Key
```

#### 4. 使用 systemd 管理进程
```bash
sudo cp deploy/pm-liquidity.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable pm-liquidity
sudo systemctl start pm-liquidity
```

#### 5. Nginx 反向代理（推荐）
```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/pm-liquidity
sudo ln -s /etc/nginx/sites-available/pm-liquidity /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

## 架构

```
backend/
├── main.py          # FastAPI + WebSocket
├── models.py        # 数据模型（EventMapping, OrderBook 等）
├── mapping.py       # 事件映射存储 (JSON 文件持久化)
├── automatch.py     # 自动化事件映射（队名+时间匹配算法）
├── data/            # 映射数据存储目录
│   └── event_mappings.json
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
    ├── EventList.jsx       # 赛事列表
    ├── EventDetail.jsx     # 赛事详情 + 映射管理 + Order Book 对比
    └── OrderBookChart.jsx  # Order Book 可视化
```

## 事件映射（Event Mapping）

### 设计原则

系统以 **Polymarket 为基准市场**，所有足球赛事以 Polymarket 的事件列表为基础。其他市场（Kalshi、Betfair 等）的事件通过映射关联到对应的 Polymarket 事件上。

启动时自动从 Polymarket 拉取所有活跃足球赛事（tag_id=100350），写入本地映射表 `backend/data/event_mappings.json`。每条映射记录的结构：

```json
{
  "unified_id": "polymarket_event_id",
  "display_name": "Team A vs Team B",
  "event_time": "2026-03-15T20:00:00+00:00",
  "mappings": {
    "polymarket": "polymarket_event_id",
    "kalshi": "KXEPLGAME-26MAR15TEAMATEAMB",
    "betfair": "betfair_market_id"
  },
  "polymarket_data": { ... }
}
```

`mappings` 字段存储各市场的事件 ID，选中某个事件时系统会根据这些 ID 并发拉取各市场的 Order Book 进行对比。

### 映射方式

#### 1. 自动映射（推荐）

点击前端页面的 **🤖 Auto-Match Markets** 按钮，或调用 API：

```bash
# 对所有非 polymarket 市场执行自动映射
POST /api/automatch

# 对指定市场执行自动映射
POST /api/automatch/{market_name}
```

自动映射的匹配算法（`backend/automatch.py`）：

- **队名提取**：从事件标题中解析队名，支持 `Team A vs Team B`、`Team A at Team B`、`Will X win...` 等格式
- **队名标准化**：去除重音符号、移除俱乐部缩写后缀（FC、SC、AC 等）、应用别名表（如 `Man Utd` → `Manchester United`、`Barca` → `Barcelona`、`PSG` → `Paris Saint-Germain`）
- **匹配评分**：综合得分 = 队名相似度 × 70% + 时间接近度 × 30%
  - 队名相似度：基于 Jaccard 集合相似度 + 包含关系检测，双向匹配取平均
  - 时间接近度：48 小时内线性衰减，无时间信息时给 0.5 中性分
- **匹配阈值**：得分 ≥ 0.6 时建立映射，低于阈值的跳过

#### 2. 手动映射

通过 API 手动添加或移除映射关系：

```bash
# 添加映射
PUT /api/events/{unified_id}/mapping?market_name=kalshi&market_event_id=KXEPLGAME-xxx

# 移除映射（不允许移除 polymarket 基础映射）
DELETE /api/events/{unified_id}/mapping/{market_name}
```

### 各市场事件获取方式

| 市场 | 获取方式 | 说明 |
|------|----------|------|
| Polymarket | `GET /events?tag_id=100350` | 按 Soccer tag 分页拉取所有活跃事件 |
| Kalshi | `GET /series` → 筛选 soccer tag → `GET /events?series_ticker=xxx` | 先获取所有 soccer 系列，再逐系列拉取 open 事件，带限流和 429 重试 |
| Betfair | 按 Soccer event type 搜索 | 通过 Betfair Exchange API 获取 |

### 数据流

```
启动 → Polymarket 拉取所有足球赛事 → 写入映射表
     → 用户点击 Auto-Match → 拉取 Kalshi/Betfair 事件 → 队名+时间匹配 → 写入映射
     → 用户选中某赛事 → 根据 mappings 并发拉取各市场 Order Book → 前端对比展示
     → WebSocket 每 5 秒刷新选中事件的 Order Book
```

## 添加新市场

1. 在 `backend/markets/` 创建新适配器，继承 `BaseMarketAdapter`
2. 实现 `fetch_order_book`、`fetch_event`、`search_soccer_events`
3. 在 `registry.py` 的 `create_default` 中注册

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/events | 列出所有足球赛事（基于 Polymarket） |
| POST | /api/events/sync | 手动触发同步 Polymarket 事件 |
| GET | /api/events/{id}/mapping | 获取事件映射详情 |
| PUT | /api/events/{id}/mapping | 添加市场映射 |
| DELETE | /api/events/{id}/mapping/{name} | 移除市场映射 |
| GET | /api/events/{id}/orderbooks | 获取事件所有关联市场的 Order Book |
| GET | /api/markets | 列出可用市场 |
| GET | /api/markets/{name}/search | 搜索市场事件 |
| POST | /api/automatch | 对所有非 polymarket 市场执行自动映射 |
| POST | /api/automatch/{name} | 对指定市场执行自动映射 |
| WS | /ws/live/{id} | 实时推送选中事件的 Order Book |
