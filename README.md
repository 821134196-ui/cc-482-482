# 陶艺教室 · 窑炉排期与烧制批次系统

小学陶艺教室的窑炉排期与烧制批次管理：作品登记 → 自然干燥 → 素烧/釉烧排期 → 装窑棚板分配 → 点火锁定 → 冷却计时 → 开窑清点 → 裂损补烧，全链路留痕。

零依赖实现（Node.js ≥ 22 内置 `node:sqlite` / `node:test` / `node:http`），无需 `npm install`。

## 一条命令启动

```bash
node run.js          # 或 npm start
```

首次启动自动建库并载入样例数据（含**釉料相冲、停电中断、补烧、开窑过早、装载超高、标签脱落、干燥不足、少件**等真实留痕），然后访问：

- 系统页面： http://localhost:8080
- 演示角色（页面右上角切换）：**教师** `tok-teacher` ｜ **管理员** `tok-admin`
- **学生端**：切换到“学生”，输入匿名代号（如 `S3-01`），只看作品进度与成品照片，不暴露任何设备控制

## 测试

```bash
npm test
```

覆盖五类边界：**排期互斥**（同窑时段重叠拒绝/相邻与异窑允许）、**装载约束**（釉料相冲分层、装载超高、棚板容量）、**开窑阻断**（未冷却教师 403、管理员提前开窑留痕）、**作品唯一**（同一作品不能进两个未结束批次）、**权限边界**（401/403、学生端只读），另附干燥/停电/补烧/清点链路测试（22 项）。

## 业务规则

| 规则 | 实现 |
| --- | --- |
| 干燥合格才能排素烧 | 登记时按泥料+尺寸计算 `dry_due_at`；提前确认拒绝并留痕 `dry_insufficient` |
| 窑炉时段互斥 | 同窑批次时段重叠返回 409 `SCHEDULE_OVERLAP`（已取消/已关闭不占时段） |
| 作品唯一 | 同一作品不能加入两个未结束批次，409 `WORK_BUSY` |
| 装窑约束 | 超高（>层间净高）409 `OVER_HEIGHT`；同层釉料相冲 409 `GLAZE_CONFLICT`；层容量/面积限制；均留痕 |
| 点火锁定 | 仅管理员可点火；点火后批次与程序锁定，作品状态联动 |
| 冷却开窑 | 进程内任务按程序曲线计算完全冷却时点 `cooled_until`；提前开窑仅管理员并留痕 `early_open` |
| 出窑清点 | 逐件登记 完好/裂损/少件；裂损留痕 `cracked`、少件留痕 `missing`，清点完批次关闭 |
| 补烧 | 必须引用原作品与失败原因，且原批次确有裂损记录；补烧作品同样受唯一约束 |

八类异常全部留痕于 `events` 表并在“留痕记录”页可查：标签脱落、干燥不足、釉料相冲、装载超高、停电中断、开窑过早、裂损、作品少件。

## 技术结构

```
run.js               一键启动（建库→种子→HTTP 服务→进程内计时任务）
src/
  db.js              SQLite schema（node:sqlite）
  services.js        全部业务规则与留痕
  kilnSim.js         窑温模拟适配器（程序阶梯曲线 + 停电降温），可替换为真实热电偶
  tasks.js           进程内任务：推进 firing→cooling→cooled
  auth.js            Bearer 令牌 + 角色（admin/teacher）
  server.js          HTTP 路由 + 静态托管 + 照片本地存储
  seed.js            样例数据（手动时钟“时间旅行”真实走完全链路）
public/              前端（陶土白/窑火橙/釉蓝；圆形棚板俯视 SVG；程序阶梯曲线 SVG）
photos/              装窑与成品照片（本地目录）
data/                SQLite 数据库文件
test/                node:test 测试（内存库 + 手动时钟）
```

## 主要 API

```
POST /api/works                      作品登记（教师）
POST /api/works/:id/confirm-dry      确认干燥合格（教师，未达标 409 留痕）
POST /api/batches                    批次排期（教师，时段互斥）
POST /api/batches/:id/items          作品入批（唯一约束）
POST /api/batches/:id/auto-assign    棚板自动排布（相冲自动分层）
POST /api/batches/:id/ignite         点火（仅管理员，锁定批次与程序）
POST /api/batches/:id/open           开窑（冷却完成教师可开；提前开仅管理员并留痕）
POST /api/batches/:id/count          出窑清点（完好/裂损/少件）
POST /api/refires                    补烧（引用原作品+失败原因）
POST /api/kilns/:id/power-outage     停电模拟（仅管理员，留痕）
GET  /api/kilns/:id/temperature      窑温读数（模拟适配器）
GET  /api/student/:code              学生端（无需令牌，只读进度+成品照片）
```
