# 舫纹滤层压差响应簿

舫纹过滤材料组的 12 位试验员把独立滤片的流速与压差整理成单调响应研究，并为下一档独立试验留下可审阅的说明。上游来自 `fw-pressure-1-202611.csv` 等试验文件，下游由负责人批准后交复验观察员下载 CSV。原来在表格里手工连均值的三个问题是：局部逆序没有解释、平滑曲线超出观测域、训练误差被当成新档预测误差。

本项目用按独立读数条数加权的非降 PAVA，配合观测域线性插值、目标压差逆集合和留一整档 LODO。三项研究各 12 档、每档 8 片，共 288 条固定 seed 合成观测：局部逆序、平台响应、恒定对照。数据不含真实滤片商业性能或身份。

## 启动与账号

```sh
cp .env.example .env
docker compose up --build -d --wait
docker compose exec -T backend python -m scripts.seed_demo
```

|入口|地址|
|---|---|
|浏览器|http://localhost:18232|
|API / Swagger|http://localhost:19232/docs|
|PostgreSQL|127.0.0.1:17732|

|账号 / 密码|页面、权限|典型动作|
|---|---|---|
|admin@fangwen.demo / Fangwen2026!|六页、写入、审批|批准或退回独立复验计划|
|analyst@fangwen.demo / Fangwen2026!|六页、底稿/配置/说明写入|导入独立滤片、修订、排队、提交说明；审批403|
|viewer@fangwen.demo / Fangwen2026!|六页只读、已批准CSV|核对结果并导出；所有写入403|

演示密码和 JWT_SECRET 仅供本地；部署须设置自己的值。`.env.example` 包括三个端口、POSTGRES_DB/USER/PASSWORD、JWT_SECRET、SEED_DEMO、RATE_LIMIT_WRITES（默认60）。首次启动也执行 seed，按自然键跳过已有记录，不覆盖用户改动。

Compose 恰好 frontend/backend/worker/db/redis 五服务，各自健康检查。Nginx `/api/` 移除前缀后转发，与 FastAPI 路由一致；前端探针用 IPv4 127.0.0.1。backend 等 DB/Redis，worker 再等 backend；真实 Celery 任务保存 JSON 与数据库结果，共享 artifacts 命名卷。停止并清空本题演示数据：`docker compose down -v --remove-orphans`。

## 一天的试验剧本

1. 09:00，压差试验员宋桥登录“响应总览”，先区分训练误差与整档预测误差。
2. 到“滤片与档位”选择 `FW-28A 局部逆序滤片`，核对 `fw-pressure-1-202611.csv`。12 档流速 10–120 mL/min，每档8片，滤片编号如 `FW1-F04-P01`。
3. 核对独立滤片来源；同片重复测量不能换个编号冒充独立重复。首次可整份导入带 levels/readings 的 JSON；同流速的多个命名档会合并。到货分批时改用“分批补传 / 更正”面板，按滤片编号并入原研究，不另建研究。
4. 在“拟合配置”预先固定物理非降方向，目标压差6.5 kPa，查询流速 `5,35,45,80,125`。送入 PAVA 与 LODO 队列，不从数据搜索方向。
5. “曲线与留档”显示 A 研究的40/50 mL/min两档合并，权重16、拟合压差6.52278638 kPa；共11个算法块。训练原始读数 MSE0.06315489567，LODO MSE0.67071027973，12次真实重拟合。
6. 目标6.5 kPa的域内线性逆解约39.84104945 mL/min；查询5和125都明确标端点夹持。夹持不构成外推能力。平台目标会返回整个区间，范围外无解。
7. 读每一折的留出流速、训练读数数、逐滤片残差；端点两折16片也计入总MSE，域内读数MSE另列0.51193266565。
8. 到“独立复验”提出45 mL/min的新档取样，写明另取独立滤片、核对原始压差。说明冻结整份结果，不把拟合响应当下一档保证。
9. 负责人许澜批准或退回，观察员叶衡下载批准快照 CSV；过程留痕记录导入、修订、队列、审批与导出。重复审批409，修改底稿不能改写既有批准快照。补传、更正、忽略与拒绝都进批次记录，旧版读数仍可在版本历史里读到；页面逐条给出新增、更正、忽略和拒绝原因。

## 分批补传与版本合并

补传与更正都写进原研究，研究有递增的 `current_version`，档位与滤片各有自己的 `version`；历史写入 `dose_level_revisions` / `pressure_reading_revisions`，只追加不回滚。

- 识别重复：以 `specimen_ref` 为滤片身份，跨批次判重；同批内重复编号直接拒绝整批。补录新滤片用新编号，不靠改编号伪造独立重复。
- 正确与陈旧：批次带 `base_version`；研究已被其他批次或人工修订推进时，提交即 409 `stale_version`，不写入。单条更正必须显式给 `version=当前+1`；小于当前为陈旧、同版本但内容不同为 `version_conflict`、跳跃为 `version_gap`，均拒绝整批。人工修订同样带 `expected_version`，并发相撞时明确拒绝后提交的一方。
- 换档：档位提交更高 `version` 和新的 `flow`/`label` 即可换档；该档位下的滤片随之进入新流速参与聚合与权重。
- 整批原子：任一条重复编号、引用缺失（档位/滤片不存在）、版本不合法，或合并后的整份研究不满足分析条件（2–30档、≥2独特流速、每档1–30条、总计≤600等），整批都不入库；拒绝原因写入批次记录。
- 幂等重试：每个批次带 `idempotency_key`。网络重试用原键原样重发会返回首次结果并标 `replayed`，不再插入读数或重复计入权重；同一键换内容会被拒绝。被拒的批次未写任何数据，修正后可用同键重试。
- 幂等与并发：应用批次时对研究行加锁，唯一键冲突时回读既有结果而不二次应用。人工修订与补传都会推进研究版本，令对方基于旧版本的提交立即失效。
- 兼容既有：旧研究与既有 `MonotoneRun`/`ValidationNote` 不变；启动时为缺少历史的研究补 v1 基线记录。运行记录冻结 `source_version`，底稿推进后旧结果仍可读，worker 不会用新底稿重算排队中的旧版本任务。
- 页面：`滤片与档位` 显示当前版本、档位/读数版本、批次记录（新增/更正/忽略数量与拒绝原因）和版本历史；`RunList` 标注输入版本，底稿推进时提示旧结果仍按冻结输入可读。

## 数学口径

输入有命名档 DoseLevel 与每片 PressureReading。同一研究中的 specimen_ref 必须唯一；同一流速 x 先合并所有命名档，计算原始读数均值 μⱼ 和条数 nⱼ。PAVA 解 `min Σ nⱼ(μⱼ−θⱼ)²`，约束 `θ₁≤…≤θₖ`。权重是独立滤片数，不是任意可靠性评分。

按流速排序，用相邻块栈逐一合并违反非降的块，以加权均值更新。相等而未违反约束的相邻块可保留多个算法块；平台逆集合仍覆盖所有相等拟合节点，块数不代表物理变化次数。保存每块索引、权重和拟合值、完整节点均值/计数。数学操作使用 NumPy longdouble 以减少加权累计舍入，结果以 JSON 浮点保存。

观测域 `[min(x),max(x)]` 内连接相邻拟合节点，得到连续非降线性曲线。域外查询只返回最近端点值，并标记 left/right clamp，不称外推。逆集合指观测域内满足 `f(x)=目标压差` 的全部流速：严格上升处为一点，平台为闭区间，超出拟合压差范围无解；恒定曲线合法，目标等于常量时返回整个观测域。比较基于保存的浮点节点精确相等，没有人为扩成置信带。

LODO 每次去掉一个独特流速的全部原始读数（包括所有同x命名档），在剩余档位重新执行 PAVA，然后插值或端点夹持预测留出档。保存每折训练流速/读数数/拟合节点/块、留出预测、每片原始残差与平方误差。`总MSE=Σ所有留出原始读数误差² / 原始读数总数`，不是不等档数时对各折MSE简单平均；MSE单位为kPa²。端点夹持折计入总值，并另列夹持数和域内MSE。

手算例 x=[1,2,3]，均值=[3,1,2]，独立数=[1,3,1]，PAVA=[1.5,1.5,2]；目标1.5的逆集合[1,2]，目标1.75逆解2.5，LODO各折预测[1,2.5,1.5]，原始读数总MSE2.2。简单折均值约2.16667，与正确总MSE不同。浏览器实际导入也验证此例。

方向由试验前物理假设声明，不按测试误差选择。滤片独立、与新档采样机制可比是LODO解释的前提；同片相关重复会破坏独立读数权重解释。LODO与逆集合不提供置信区间、因果归因、材质合格或外推承诺。平滑和平台是约束模型的确定性结果，仍需独立复验。

## 校验、审阅和工程结构

每研究2–30命名档、至少2个不同流速，每档1–30读数，总计≤600；流速有限且0–1000，压差有限且0–1,000,000，查询≤30项。相同x合法并聚合；全同x、重复滤片编号、空档、非有限、负压差与错误方向拒绝。统一422错误不回显非法NaN输入，避免默认错误对象再次JSON编码失败。worker独立重验，历史坏任务标failed。

86个有职责的 Python/TS/TSX/CSS 文件（不含空包、依赖和dist；新增 batch/revision 模型、服务、store 与组件）。核心实体 FlowStudy → DoseLevel → PressureReading → MonotoneRun → ValidationNote 贯穿 ORM/schema/service/routes、前端API/store和六页，并附 DataBatch / DoseLevelRevision / PressureReadingRevision 记录版本化补传。六页为：响应总览、滤片与档位、拟合配置、曲线与留档、独立复验、过程留痕。

前端 `src/{api,stores,types,components/common,hooks,pages,router,utils,constants}`；后端 `src/{routes,controllers,services,models,schemas,middlewares,utils,constants,config}`，另 scripts/seed_demo.py 与 migrations/。共享组件 ResponsePlot、FitDigest、InverseSet、RunList 在多页复用，LodoTable与common组件提供一致解释；useTask/useRoute和format工具处理状态与格式。

Role、RunStatus、NoteStatus 后端位于 `backend/src/constants/enums.py`，前端对应 `frontend/src/constants/enums.ts`。JWT授权、审计、RequestID/Error/Redis写限流三个中间件形成横切链路。写配额按令牌摘要（无令牌时IP）与分钟计数，超限429含Retry-After，健康读取不计；限流存储不可用返回503。批准以数据库行锁保证 draft 只能审一次，冻结 result_snapshot 供CSV导出。

|层|实现|
|---|---|
|前端|React18 / TypeScript / Vite6.4.6，DM Sans+Noto Serif SC，真实SVG响应图|
|后端|Python3.11 / FastAPI / SQLAlchemy / PostgreSQL16|
|队列|Celery5.4 / Kombu5.4.2 / Redis7，worker并发1|
|数值|新写加权PAVA、线性插值/逆集合、逐整档重拟合LODO|

本地前端：`cd frontend && npm ci && npm run dev`；`npm run build` 执行tsc与Vite。后端安装 requirements.txt，设置 DATABASE_URL/REDIS_URL/JWT_SECRET 后启动 uvicorn。当前以 SQLAlchemy metadata create_all 初始化，并在启动时为既有库补齐 `current_version`/`version`/`source_version` 列（`ensure_version_columns`，幂等）；migrations 提供结构说明，未声称生产迁移链。许可证 MIT，见 LICENSE。

完整实际验收位于批次 `test-artifacts/gb-0028/TESTING.md`。本次分批补传/版本合并由 `backend/tests/test_batches.py`（服务层语义）与 `backend/tests/test_api.py`（路由/鉴权/422/409 契约）覆盖，均为本地可重复运行的断言脚本（SQLite + 桩限流，不依赖 Docker）。关键 JSON、CSV、测试脚本、真实截图与原始日志都在该题证据目录，不进入源码。当前未验证外部真实滤材或生产压力；令牌/IP分钟配额不是完整生产抗滥用体系，登录更换令牌可获得新计数。Google字体断网时退回本地字体。输入数值上限与固定非降模型只服务本题研究范围，不是设备运行参数建议。
