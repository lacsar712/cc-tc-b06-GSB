# 隧道收敛测缝台

测量员登记里程桩号与收敛毫米值。接口进程内后台线程认领待判行（不另起 worker 容器），按绝对值是否不超过 3.0 mm 给出合格或超限。页面是 Svelte。

测缝计带校准到期日：**到期后该铭牌不许再报**。页眉"校准到期专页"列出各号到期日与最近拦住的原因；测量员可改到期日、办理续期，巡检员只读。报送与续期在同一短事务内对测缝计行加锁（`SELECT … FOR UPDATE`），撞在同一瞬间也只有一种结局，不会既收下又显示过期。

## 校准到期规则

- 到期日只存 `meters` 一张表；报送拦截、改期、续期都锁这同一行后判定，不存第二份副本。
- 报送时若到期日早于当天：读数不进待认领队列，记为 `blocked` 并返回 423，提示"先续期以后再开"，同时把原因写回该号"最近拦住的原因"。
- 测量员可把到期日改到过去（改完该号再报即被拦）；续期默认顺延一年，且不能续到今天之前。每次改期/续期都在 `calibration_events` 留痕。
- 巡检员（reader）对改期、续期、报送一律 403。

### 接口

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/meters` | 登录 | 各号到期日、是否过期、最近拦住原因 |
| GET | `/api/calibration-events?meter_code=` | 登录 | 续期/改期痕迹 |
| PUT | `/api/meters/<code>/expiry` | 测量员 | 改到期日 `{expires_on: "YYYY-MM-DD"}` |
| POST | `/api/meters/<code>/renew` | 测量员 | 续期（可传 `expires_on`，默认 +365 天） |
| POST | `/api/logs` | 测量员 | 报送需带 `meter_code`；过期返回 423 |

## 技术栈

- 后端：Flask、Gunicorn、SQLAlchemy、进程内认领线程
- 前端：Svelte、Vite、nginx 反代 `/api`
- 数据库：PostgreSQL 16

## 端口

| 服务 | 地址 |
|------|------|
| 页面 | http://localhost:3201 |
| 接口 | http://localhost:8201 |
| PostgreSQL | localhost:54401（库名 `tunnelconv`） |

## 账号

| 用户 | 密码 | 权限 |
|------|------|------|
| surveyor | surv123456 | 可提交 |
| inspector | insp123456 | 只读 |

## 启动

```bash
cd projects/21-tunnel-convergence-desk
docker compose up --build
```

健康检查：`GET http://localhost:8201/api/health`

## 种子

| 桩号 | 收敛 | 结论 |
|------|------|------|
| K12+180 | 1.2 mm | 合格 |
| K18+040 | 5.6 mm | 超限 |

测缝计台账：

| 编号 | 名称 | 校准到期日 |
|------|------|-----------|
| JFJ-A | 甲号测缝计 | 建档日 +180 天（有效） |
| JFJ-B | 乙号测缝计 | 建档日 −1 天（已过期，专页可见过期态） |
