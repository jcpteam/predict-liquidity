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

### 方式四：手动部署到 VPS / 云服务器

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
