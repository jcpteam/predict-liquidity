# ── Stage 1: 构建前端 ──
FROM node:18-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --silent
COPY frontend/ ./
RUN npm run build

# ── Stage 2: 运行后端 ──
FROM python:3.12-slim
WORKDIR /app

# 安装后端依赖
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt gunicorn uvloop httptools

# 复制后端代码
COPY backend/ ./

# 复制前端构建产物
COPY --from=frontend-build /app/frontend/dist ./frontend_dist/

# 数据目录
RUN mkdir -p /app/data

ENV PORT=8000
ENV WORKERS=2
EXPOSE 8000

CMD gunicorn main:app \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers ${WORKERS} \
    --bind 0.0.0.0:${PORT} \
    --access-logfile - \
    --error-logfile -
