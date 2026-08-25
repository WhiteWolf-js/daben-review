# daban-review — 打板情绪复盘系统

A股 打板/短线的**情绪面 + 连板属性博弈**复盘与监控系统。产出不是评分,是"明日核心矛盾"的条件判断。
详细定位/功能/技术难点见 `README.md`(单一事实源),本文件只放**开发与运行必须知道的**。

## 路径与常驻服务

- 仓库:`~/daban-review`(git,分支 `main`)
- **前后端已配 launchd 常驻**(开机自启 + 崩溃重启 + `caffeinate -i` 防休眠),平时**不用手动启动**:
  - 后端 `com.tiger.daban-backend` → http://localhost:8000(uvicorn,**未开 --reload**)
  - 前端 `com.tiger.daban-frontend` → http://localhost:5173(vite,有热更新)
  - **飞书机器人 `com.tiger.daban-bot`**(WebSocket 长连接,全天在线,私聊查盘)
  - **盘中监控 `com.tiger.daban-watcher`** —— 与上面三个不同,它是
    **`StartCalendarInterval` 周一至五 09:20 定时拉起,`KeepAlive=false`**。
    原因:`watcher.run()` 到 15:00 会自己 break 退出(设计如此),配 KeepAlive 会变成
    收盘后整晚「拉起→立刻退出→再拉起」空转。9:20 起是因为 `_OPEN=9:25`,循环会 sleep 等到点。
    周末靠 `Weekday` 挡;**法定节假日挡不住**,由 `_is_trade_day()` 守卫自己退出
    (判据=通达信当日日线是否已生成;没有节假日日历可用,akshare 那个走 py_mini_racer,本机已坏)。
    守卫**在 9:35 后才生效**,更早判会把真交易日误杀(当日日线要开盘有成交才生成)。
  - plist:`~/Library/LaunchAgents/com.tiger.daban-{backend,frontend,bot,watcher}.plist`
  - 日志:`data/logs/{backend,frontend,bot,watcher}.log`

> 别在 launchd 之外再手动起一份 uvicorn:手动那份绑 `127.0.0.1:8000` 会**优先响应 localhost**,
> 导致你以为改的后端代码没生效(踩过,新接口一直 404)。查占用:`lsof -nP -iTCP:8000 -sTCP:LISTEN`。

运维(`U=$(id -u)`,**任何命令都不加 sudo**):

| 场景 | 命令 |
|---|---|
| 改后端代码后重启 | `launchctl kickstart -k gui/$U/com.tiger.daban-backend` |
| 改机器人代码后重启 | `launchctl kickstart -k gui/$U/com.tiger.daban-bot` |
| 改前端 | 不用重启(vite HMR) |
| 盘中监控立刻起一次(当天忘了/临时要) | `launchctl kickstart gui/$U/com.tiger.daban-watcher`(**不加 `-k`**:加了会杀掉正在跑的那个) |
| 确认监控在跑 | `curl -s localhost:8000/api/live \| grep -o '"running":[a-z]*'`(判活=快照 3 分钟内有更新) |
| 看状态 | `launchctl print gui/$U/com.tiger.daban-backend \| grep -E "state\|pid"` |
| 停 + 禁自启 | `launchctl bootout gui/$U/com.tiger.daban-<backend\|frontend>` |
| 重新加载 | `launchctl bootstrap gui/$U ~/Library/LaunchAgents/com.tiger.daban-*.plist` |
| 看日志 | `tail -f data/logs/backend.log` |

远程访问:前端 `api.ts` 的 BASE 跟随 `window.location.hostname` 自适应,后端 CORS 放开 `http://*:5173`;跨网络走 Tailscale(`100.x.x.x:5173`)。**合盖仍会睡**,caffeinate 挡不住。

## 飞书机器人(手机查盘)

私聊发指令:`复盘`(推海报图,可带 `复盘 20260723`)/ `候选` / `情绪` / `持仓` / `帮助`;**其余任何文本 → agent 自由提问**(1-2 分钟,先回执再发结果)。

- 代码:`monitor/bot_commands.py`(纯函数:文本→动作,可离线单测)+ `monitor/bot.py`(ws 长连接 + 发送)
- 离线自检**不用连飞书**:`PYTHONPATH=. python3 -m daban_review.monitor.bot --once "候选"`
- 开关:`.env` 的 `FEISHU_BOT_ENABLED=1`;白名单 `FEISHU_BOT_ALLOW`=**本应用下的 open_id**(`ou_` 开头)
- ⚠️ 白名单里的 open_id 与推送用的 `FEISHU_TARGET`(union_id,`on_` 开头)**不是一回事**。
  拿法:启动 bot → 手机发一条 → `tail data/logs/bot.log` 里打印了 sender open_id。**留空则只记日志不回复**(防裸奔)。
- 飞书侧前置:应用加「机器人」能力 + 事件订阅选**「长连接接收」**(不填回调地址)+ 订阅 `im.message.receive_v1`,**改完必须重新发布版本**。
- agent 提问有**单飞行锁**:同时只跑一个,忙时回「上一个还在分析」。

## 手动跑(调试/服务被停时)

```bash
cd ~/daban-review/backend                                    # 系统 python3.13,无 venv;只有 python3,没有 python
PYTHONPATH=. python3 -m uvicorn daban_review.app.main:app --port 8000 --reload
PYTHONPATH=. python3 -m daban_review.cli analyze 20260721     # CLI 单日复盘
PYTHONPATH=. python3 -m daban_review.cli backtest             # 评分回测(读库,不花 token)
PYTHONPATH=. python3 -m daban_review.monitor.watcher --once   # 盘中监控自检(跑一轮,写库+打印)
PYTHONPATH=. python3 -m pytest tests/ -v                      # 单测(164 passed)

cd ~/daban-review/frontend && npm run dev                     # :5173
```

> 前端要看 LiveBar 盘中实时条,需 uvicorn(读库)+ watcher(写库)同时在跑。

## 代码定位速查

```
backend/daban_review/
  config.py            DB 路径 / akshare 降频 / Claude 网关 / usd_cny
  cli.py               review | emotion | ladder | fetch | analyze | backtest
  data/                akshare_client.py(涨停池=akshare push2ex,分时/日线/指数=mootdx,
                       涨停原因+涨停板块榜=同花顺 dataapi)
                       store.py(SQLite WAL / live / usage) / fetch.py(拉取+列名归一+落库)
  metrics/             纯本地计算,不限频:emotion 情绪温度晋级率 / ladder 天梯+封单强度
                       sector 板块热度 / auction 竞价高开 / auction_live 盘前竞价决策台
                       candidate_pool 四风格候选池(纯规则) / kline 量价
                       score A+~D 分级+仓位 / backtest 评分回测
  agent/               claude-agent-sdk:prompt.py(方法论提示词=灵魂) / tools.py(in-process MCP)
                       runner.py(执行循环+流式回调) / pricing.py(单价·成本估算)
  app/                 service.py(报告/候选提取/次日验证回测/竞价/brief)
                       main.py(REST + SSE + APScheduler 9:25:30 与 15:30)
                       poster.py(Playwright 出图 + 推飞书)
  monitor/             signals.py(P0 判据:龙头炸板/炸板潮/指数急杀) / watcher.py(轮询循环)
                       notify.py(飞书 lark-oapi 私聊,文字 + 图片)
frontend/src/
  App.tsx              只管阶段 tab / 日期 / 全局 Dialog   main.tsx(?poster= 海报页路由)
  views/               PreMarketView / IntradayView / PostMarketView ← 三阶段容器
  hooks/               useReport.ts(复盘状态单一持有,别在子组件各自持有)
  utils/               phase.ts(阶段判定) / report.ts(extractConflict/stripJson)
  components/base/     SectionedPage(吸顶锚点 bar + section 平铺 + scrollspy)
                       PanelCard(常开卡,给不自带 Card 的裸内容用)
  components/          LiveBar 实时条 / EmotionPanel(compact) / EmotionTrend / LadderView
                       ThemePanel / AuctionPanel / CandidatePanel / ChatDrawer
                       ReportSummary(核心矛盾+导出) + ReportBody(SSE Markdown 正文)
                       HoldingsList + HoldingForm + HoldingAnalysis
                       PosterView + AuctionPoster(海报,前后端共用排版)
                       IntradayDialog(原生 echarts)
data/                  SQLite 库 + posters/ + logs/
```

数据流:`data(akshare/mootdx/同花顺) → metrics(客观骨架) → agent(Claude 推理) → app(REST/SSE) → 前端`,旁路 `monitor → 飞书`。

## 开发约定(踩过的坑,别再改回去)

- **候选票的「选」必须留在代码层**(`metrics/candidate_pool.py`):四风格池由纯规则筛选 + 确定性排序
  (可打性 → score → 封流比 → 首封 → 代码),agent 只能在池内选、默认 rank1、越级须写数字理由。
  这是复现性的根本 —— 早期让 agent 从整个梯队自选,同日复跑会整批换人。**不要把选票权还给 agent**。
  排序里的 `_unplayable`(换手<1% 且无主线归属 → 沉池尾)、题材主线按「身位优先」重排(泛业绩标签
  涨停多但零连板,不是主线),都是把 agent 原本临场判断的东西固化成规则,别当成多余逻辑删掉。
- **正文的「选择权」也在代码层**:一段方向 = `theme_top` 前 4(顺序/题材名照抄)、二段画像 =
  `profile_targets` 的 4 个固定席位(市场高度/卡位板/主线龙头/次高身位)、四段矛盾主角 = 前两席。
  实测:放开让 agent 自选时,同日三次复盘的画像票和方向划分三次三样;锁定后三次完全一致。
- **prompt 的铁律段(门禁/挂数/禁用词/数值格式/选择权)不要精简**:6 工具全调是数据基础一致的前提,
  少调一个复盘就飘;"每句挂数字 + 禁用词清单"是专业性的来源;周期结论限定 6 词枚举
  (冰点/修复/发酵/分歧/高潮/退潮)是因为放开写会出现"高潮尾部""退潮初期""普涨劣质高潮"三种措辞。
- **改 prompt 或候选池后必须同日复跑 ≥2 次比对**:`python3 tools/cmp_reviews.py /tmp/r1.txt /tmp/r2.txt`
  (抽自检行/周期结论/方向/画像票/矛盾主角/候选做 diff,六项应全 ✅)。别只看候选,正文漂移是独立问题。
- **分时是 L1,不需要 L2**;可编程 L2 个人拿不到(通达信 L2 仅客户端可看无 API)。实时/分时/指数一律走 **mootdx**,别退回 akshare push2(限频即断)。
- agent 走自建的 Anthropic 兼容网关,凭证与地址都在 `backend/.env`(`ANTHROPIC_BASE_URL/API_KEY/CLAUDE_MODEL`),**不要提交 .env**;前端的 `frontend/.env.local` 放 MUI X 授权码与文档链接,同样不提交。
- **持仓截图识别(`agent/vision.py`)故意不走 claude-agent-sdk**:单轮 vision 任务,`requests` 直接
  POST `{BASE_URL}/v1/messages` 传 base64 图片就够(网关已实测支持 vision),不必引 anthropic 依赖。
  识别只吐「截图里有的」;买入板数(查当日涨停池)、买入日、是否已持仓由 `service.ocr_holdings` 补。
  用量按 `kind="ocr"` 落 usage_log(约 1.7k tokens ≈ ¥0.11/次),想省钱在 .env 配 `VISION_MODEL`。
  模型输出格式不稳(裹 ```json、前置寒暄、千分位、5 位代码),容错全在 `vision.parse_rows`,
  改 prompt 后跑 `tests/test_vision.py` 兜住。
- **`vision._norm_code` 只认恰好 6 位,短数字不补零**:模型实测会把行序号塞进 code(出现过 `"1"`),
  补零会变成 `000001`(平安银行)这种「合法但错」的代码。返回空串才能走名称反查/让用户手填。
- **券商持仓截图常常没有代码列** → `akshare_client.code_by_name` 按名称反查全 A 名录。
  取用三级:**进程内缓存 → SQLite `stock_names` 表 → 联网拉取(并落库)**;联网约 10s、读库 0.004s,
  一周过期才重拉,`main._warm_name_table` 再后台预热一次,所以用户点上传时不会等。
  源 mootdx 主 / akshare 兜底,两个源都挂时退回库里的旧名录(过期也比没有好)。
  只保留 A 股代码段(原始列表 5 万条含 ETF/可转债,不过滤会撞名,过滤后 6437 只)。
  **`stock_names` 主键必须是 name**:早期用 code 当主键,除权期的「XD兴业股份」与「兴业股份」
  指向同一 code 互相覆盖,6437 条落库只剩 6348 —— 名称变体正是反查最需要留的。
  **名称必须过 `_clean_name`**:通达信名称字段定长 8 字节、短名用 `\x00` 右填充
  (「好想你」→`好想你\x00\x00`),`.strip()` 去不掉,会让所有 3 字及更短的股票永远查不到。
  反查来的代码前端标「名称反查」提示核对,且**代码框始终可编辑**(早期识别到代码就变只读,
  认错了没法改)。自检:`PYTHONPATH=. python3 tools/probe_name_lookup.py [--force]`。
- 打板方法论只改 `agent/prompt.py`;客观分级/回测口径只改 `metrics/score.py` 与 `app/service.py`,两者必须**同口径**。
- **追问(`/api/chat`)必须用 `ASK_SYSTEM_PROMPT`,不能复用复盘的 `SYSTEM_PROMPT`**:后者带
  「6 工具全调门禁 + 五段结构 + 候选池选择权」,套到追问上会把一句问话答成一整篇复盘。
  追问同时收紧 `max_turns=12`。
- **`ClaudeAgentOptions` 必须带 `tools=[]`**:我们只用 in-process MCP 工具,Claude Code 的内置工具
  (Bash/Read/Edit/WebFetch…)定义白占约 26k tokens。实测 `cache_write` 139k→113k、首字节快 8s,
  且**不影响 MCP 工具调用**(实测 agent 仍能正常调 get_candidate_pool)。
- **成本结构要知道(改不了,别浪费时间调优)**:走 agent-sdk→CLI 每一轮往返都要重付约 110k tokens 的
  `cache_write`,而内部网关的 `cache_read` **恒为 0**(缓存不复用)。所以:不调工具的追问 ≈16s/¥8,
  调一次工具 ≈73s/¥18,复盘调 6 工具 ≈4min/¥14-20。要真降本只能绕开 CLI 直连 Messages API
  (像 `agent/vision.py`、`run_auction_brief` 那样),代价是失去工具循环。
- **持仓诊断是多选的**(`service.analyze_holdings(codes, ...)`):`runner.run_holding` 一直接受列表,
  多只一起跑只拉一次大盘上下文,还能产出「处置优先级/同质化风险/总仓位」——这是多选的意义,
  别退回逐只跑。一次分析产出**一篇** markdown,`_save_holding_analysis` 给参与的每只各存一行
  (markdown 重复、verdict 按 code 各取自己那项),这样 HoldingsList 的读取逻辑不用变。
  接口 `POST /api/holdings/analyze` 收 `codes: list[str]`,同时兼容老的单个 `code`。
- **改完海报组件必须 `npm run build`,否则飞书推的还是旧图**:后端 `poster.py` 用 Playwright 截的是
  `POSTER_BASE_URL`(默认 `127.0.0.1:8000`)—— `main.py` 把 **`frontend/dist` 构建产物**挂在 `/` 上,
  **不是** vite dev server 的 :5173。所以网页上看着已经改好、飞书推出来还是老样子。
  涉及的文件:`PosterView / LadderPoster / AuctionPoster / HoldingPoster` 以及它们共用的
  `LadderGrid / HoldingBoard`。自检:`PYTHONPATH=. python3 -c "from daban_review.app import poster;
  print(poster.render_poster('<date>', kind='holding'))"` 然后看 `data/posters/` 里那张图。
- **海报与网页面板共用一份排版**(`LadderGrid`、`HoldingBoard`):别写两套,改一处就好。
  海报侧没有 tooltip 兜底 —— 面板上截断后能 hover 看全的字段(如持仓触发价),海报上必须给够行数,
  否则信息永久丢失。
- ECharts 在 MUI Dialog 里用**原生 echarts** 手动 `init/setOption/resize`,`echarts-for-react` 会 stale 只画左半。
- 通达信协议偶发浮点垃圾(`5.87e-39`),量能一律 `<1e-6` 归零。
- 前端 MUI v7 + emotion,样式用 `sx`,不新增 `.scss`。
- **前端信息架构 = 顶部常显 + 吸顶锚点 + section 平铺**(`components/base/SectionedPage`),
  别再退回折叠流(原 `FoldCard` 已删)。裸内容才用 `PanelCard` 包;ThemePanel/LadderView/
  CandidatePanel/EmotionTrend/AuctionPanel 自带 Card + 标题,**直接进 section,别套两层壳**。
  scrollspy 的「触底强制高亮末段」必须先判 `scrollHeight > innerHeight + 8` —— 首屏数据没到齐时
  页面不足一屏会误判成已触底,高亮卡在末段;面板陆续加载会改高度,靠 `ResizeObserver(body)` 重算。

## 完成的定义

后端改动:`PYTHONPATH=. python3 -m pytest tests/ -v` + `launchctl kickstart -k` 后 `tail data/logs/backend.log` 无异常。
前端改动:`npx tsc -b --noEmit`(或 `npm run build`)+ 浏览器实看 :5173。
**动了海报组件**:额外 `npm run build`,再让后端出一次图核对(见上方约定),否则飞书还是旧图。
失败就贴输出说失败,不假装通过。
