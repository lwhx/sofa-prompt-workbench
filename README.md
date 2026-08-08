# 沙发场景提示词工作台

基于 Vue 3、FastAPI、SQLite WAL、Redis/RQ、OneImg 和 OpenAI 兼容视觉接口的沙发场景提示词生产工作台。

## 当前能力

- 单管理员登录、HttpOnly Session、CSRF；
- 场景参考图和沙发白底图上传、验证、OneImg 后端代理；
- 任务行 CRUD、revision CAS、软删除；
- 不可变 Job 快照、事务 Outbox、确定性 RQ Job ID；
- 六模块视觉结果、正向/负向提示词、中性未知回退；
- stale-result CAS、结果历史、正式版本选择、人工方位确认；
- SQLite Backup API、Manifest、隔离恢复校验；
- Vue 工作台、登录页、双图上传和运行入口；
- Alembic、Docker Compose、Nginx、Redis AOF。

## 本地开发

### 后端

```bash
cd backend
uv sync --extra dev
env -u PYTHONPATH uv run alembic upgrade head
env -u PYTHONPATH uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 前端

```bash
cd frontend
npm ci
npm run dev
```

访问 `http://127.0.0.1:5173`。Vite 会把 `/api` 和 `/health` 代理到后端。

## 质量门禁

```bash
cd backend
uv run ruff check .
uv run mypy app
uv run python -m pytest -q

cd ../frontend
npm run lint
npm run typecheck
npm run test -- --run
npm run build
```

## Docker 部署

1. 复制 `.env.example` 为 `.env`，填写强随机 Session Secret、OneImg 和 AI 凭据；
2. 执行 `docker compose config` 检查；
3. 执行 `docker compose up -d --build`；
4. 访问 `http://localhost:8080/health/ready`。

只有 Nginx 暴露宿主机端口。SQLite、缓存、备份和 Redis AOF 使用持久卷。迁移成功后 API 与 Worker 才启动。

> 不得在真实数据项目上执行 `docker compose down -v`。

## 备份边界

数据库备份使用 `sqlite3.Connection.backup()`，并验证 SHA256、`integrity_check`、`foreign_key_check` 和隔离恢复。完整业务恢复还必须包含被任务、Job 快照和历史结果引用的 OneImg 对象或经过验证的图床独立备份清单。

## 安全

- `.env`、数据库、日志、缓存和备份不进入 Git；
- Token、Cookie、图片 Base64 不写普通日志；
- 浏览器永远不直接获得 OneImg/AI Token；
- 生产环境启用 HTTPS 和 Secure Cookie；
- 外部请求必须配置超时并执行 SSRF/重定向校验。

详细领域与可靠性契约见 `sofa_prompt_workbench_development_spec_v1_reliable_cn.md`。
