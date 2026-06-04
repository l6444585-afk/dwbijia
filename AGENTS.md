# 跨平台智能比价系统 (dwbijia)

多平台商品价格监控与比价系统，支持淘宝、得物等平台的实时价格采集与对比分析。

## 命令

```bash
# 开发
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 测试
pytest tests/ -v --cov=app --cov-report=term-missing

# Docker
docker-compose up -d

# 阿里云 CLI
aliyun ecs DescribeInstances --RegionId cn-hangzhou  # 查看ECS实例
aliyun oss ls                                         # 列出OSS存储桶
aliyun rds DescribeDBInstances --RegionId cn-hangzhou  # 查看RDS实例
```

## 架构

- **框架**: FastAPI + SQLAlchemy (async) + Redis
- **入口**: `app/main.py` → 路由在 `app/api/` 下按领域划分
- **分层**: API → Services → Repositories → Models（严格单向依赖）
- **爬虫引擎**: `app/scrapers/engine/` 含反检测、指纹、速率限制、代理池
- **定时任务**: APScheduler，配置在 `app/tasks/scheduler.py`

## 关键约定

### 编码风格
- Python 3.11+，所有函数必须有类型注解
- 使用 Pydantic models 做输入验证，不手动校验
- 异步优先：所有 I/O 操作使用 async/await
- 日志用 `loguru`，不用 `print` 或标准 `logging`
- 注释和文档字符串使用中文（代码本身用英文）

### 错误处理（项目特定）
- 爬虫错误必须包含：平台名、URL、HTTP 状态码、重试次数

### 数据库
- 所有数据库访问通过 Repository 模式（`app/repositories/`）
- 使用 SQLAlchemy async session，不写原始 SQL
- 迁移文件在 `migrations/` 目录

## 浏览器 MCP 使用规则（IMPORTANT）

- **默认使用 Chrome DevTools MCP**（保留登录态、Cookie、密码、历史记录）
- **爬虫/自动化测试使用 Playwright MCP**（隔离环境，避免真实账号被风控）
- NEVER 用 Chrome DevTools MCP 跑爬虫，防止日常账号被封

## 主动行为准则（CRITICAL）

- 发现 bug 必须主动修复，NEVER 等用户指出才改正
- 每次交付后主动提出改进意见，用户愿意倾听批评
- 元认知自审是强制习惯，不是可选动作
- NEVER 乱删除文件/配置来"解决"问题，一切以官方文档为准
- 部署/修改前 MUST 做全链路审查（前端代码→API调用→后端→数据库→配置文件→systemd服务），不能只改一处就宣布完成
- 改了源码还要检查所有引用该配置的地方（环境变量、systemd、nginx、docker-compose 等）
- 思考用户视角：用户从哪里进入系统？流程顺手吗？逻辑连贯吗？

## 部署验证铁律（CRITICAL — 来自实战教训）

部署前 MUST 完成以下检查，NEVER 跳过：

1. **代码审查先行** — 部署前先通读前后端关键流程（登录、权限、API调用），不能边部署边发现 bug
2. **全链路一致性** — 检查所有配置来源是否一致：
   - nuxt.config.ts 的 apiBase
   - systemd 服务的 Environment 变量
   - nginx 的 proxy_pass
   - 后端的 application.yml
3. **环境变量覆盖链** — Nuxt 运行时 env var > nuxt.config.ts 默认值。改了配置文件但忘了改 systemd Environment = 白改
4. **sudo 会清除环境变量** — 用 `sudo env VAR=val command` 或 `sudo -E` 传递变量
5. **密码/哈希验证** — 数据库里的密码哈希要在 MySQL 交互模式下操作，避免 shell 解析 `$` 符号
6. **端到端验证** — 改完后自己模拟用户操作验证，不能只看"Build complete"就宣布成功

7. **共享 ECS NEVER 为救单个组件重启整机（2026-06-04 实战教训，最高优先级）** — 本项目 caiji（caiji.tianku.com）与**招商系统**（zhaoshang / fy.tianku.com，黄总 prod）**同在一台 ECS** `i-bp18zrqcsw2yuxmy6yd2`（47.99.195.159），同机还有 MySQL。**只为救某个挂掉的组件（阿里云助手 Agent、caiji、任意 service）NEVER 重启整台机器 / StopInstance / RebootInstance**——重启会把同机的**招商系统一起搞挂**（用户核心顾虑）。**正解**：阿里云控制台「远程连接」VNC 登进去 `sudo systemctl restart <组件>`（救 Agent = `sudo systemctl restart aliyun.service`；救 caiji = `systemctl restart caiji-mvp`；救招商 = `systemctl restart fengyun-backend`），同机其他服务零中断。**反例**：2026-06-04 为补 caiji 服务器侧 curl 证据去救掉线的 Agent，走了"重启整机"→fy.tianku.com 全挂（`ERR_TUNNEL_CONNECTION_FAILED`）+首轮重启被中途打断 unclean shutdown→`/var/log/journal` 损坏→开机卡 `systemd-tmpfiles-setup` 7min+（实查证伪"磁盘满"：磁盘仅 52%、/tmp 17 文件，真因=unclean-shutdown 自修复延迟），第二次干净重启才恢复。**无 agent 也能诊断**：`aliyun ecs GetInstanceConsoleOutput`（boot 日志 base64）+ `DescribeInstances ... Status`（Running=电源开≠OS启动完）+ `DescribeCloudAssistantStatus` + 用户 VNC。**口径分三档(GPT 2026-06-04 校准)**：已证（caiji sqlite integrity ok→未见数据丢失迹象，未做 MySQL 表级对账≠完整证明）/ 高概率（无 swap+Java 占 1.1G/3.4G 紧、6/2 有 OOM 杀 node 实锤，但今天 Agent 之死无对应 OOM 记录→不当定论）/ 线上封顶（靠代码+51测试证明，线上 `limit=99999` 返 200 但 count:0 只证部署版本含代码+接口可用+鉴权生效，NEVER 说"线上封顶实测OK"）。**根因隐患**：4GB 单机混部 Java 招商+Python caiji+MySQL 内存紧→建议配内存/磁盘告警+长远拆机或升配。**红线**：任何重启整机动作前 MUST 先确认同机有没有别人的 prod，有就改用 `systemctl restart <组件>`。

## 爬虫特别规则（IMPORTANT）

- 永远不要在代码中硬编码 Cookie 或 Token
- 爬虫请求必须经过 `rate_limiter` 和 `anti_detect` 模块
- 新增平台爬虫必须继承 `app/scrapers/platforms/base.py` 的基类
- 测试爬虫时使用 mock 数据，不发送真实请求
- 永远不要打开可见的浏览器窗口，所有 Playwright 操作必须 headless

## 工作流程

### 编码前
1. 需求不明确时先提问澄清，否则直接执行
2. 如果需要修改超过 3 个文件，先分解成更小的任务再逐一完成

### 编码后
3. 列出可能出问题的地方，建议测试用例覆盖
4. 发现 bug 时，先写一个能复现的测试，再修复直到测试通过

### 持续改进（CRITICAL — 禁止偷懒，必须严格执行）
5. 每次被纠正后，将新规则添加到本文件的相应章节
6. **每次学习到新知识、新模式、新经验教训时，必须立即更新本文件**。不允许"稍后再写"、"下次补上"。学到就写，写了才算完成。这是强制要求，不是建议。
7. 每次对话中产生的项目决策、架构变更、技术选型，必须实时同步到本文件对应章节
8. 如果本文件中的规则与实际代码不符，以实际代码为准并立即更新本文件

### 学习文档管理（IMPORTANT — 只更新不新建）

固定 4 个学习文档文件，每次学习到新内容时**同步更新所有 4 个文件**，永远不要新建文件：

| 文件 | 格式 | 路径 |
|------|------|------|
| Markdown | `.md` | `docs/learning.md` |
| PDF | `.pdf` | `docs/learning.pdf`（从 HTML 用 weasyprint 生成） |
| Word | `.docx` | `docs/learning.docx`（用 python-docx 生成） |
| HTML | `.html` | `docs/learning.html` |

更新规则：
- 学到新东西 → 4 个文件全部追加，保持内容一致
- 永远不要删除已有记录，只追加新行
- HTML 文件的 `最后更新` 日期必须同步修改
- PDF 每次从 HTML 重新生成：`weasyprint docs/learning.html docs/learning.pdf`

## 测试（项目特定）

- 爬虫测试：使用 mock HTTP 响应，不发真实请求
- 覆盖率命令用 `--cov=app`（不是 `--cov=src`）

## Playwright 自动化经验（IMPORTANT）

### 大页面 token 超限问题
- freesound.org 等内容密集的网站，`browser_navigate` 和 `browser_snapshot` 返回结果经常超过 token 上限（93,000+ characters）
- **解决方案**：用 `browser_snapshot` 的 `filename` 参数保存到文件，再用 `grep` 提取关键信息（如搜索结果标题和评分）
- 示例：`grep -A 5 'heading.*level=5' snapshot.md | head -20`

### 批量下载策略
- 不要一次搜完所有关键词，一个一个搜+下载，避免 500 错误和 token 超限
- 下载大文件时设置 `timeout: 120000`（2分钟）
- 用 `page.waitForEvent('download')` + `download.saveAs(path)` 直接保存到指定路径
- 合并搜索+点击+下载为一个 `browser_run_code` 调用，减少来回交互

### 高效搜索模式（一步到位）
```javascript
async (page) => {
  await page.goto('https://freesound.org/search/?q=关键词&f=license%3A%22Creative+Commons+0%22');
  await page.waitForLoadState('networkidle');
  const firstResult = page.locator('main h5 a').first();
  const title = await firstResult.textContent();
  await firstResult.click();
  await page.waitForLoadState('networkidle');
  const downloadPromise = page.waitForEvent('download', { timeout: 120000 });
  await page.getByRole('link', { name: 'Download sound' }).click();
  const download = await downloadPromise;
  await download.saveAs('/path/to/file.wav');
  return title;
}
```

### 格式转换
- 下载后用 `ffmpeg` 统一转 mp3：`ffmpeg -i input.wav -codec:a libmp3lame -qscale:a 2 output.mp3 -y`
- 转完删除原始 wav/aiff 文件

## Chrome DevTools MCP 自动化经验（CRITICAL — 铁律）

### 官方最完美方案：插件化安装（MCP + Skills 一体）

**来源**：https://github.com/ChromeDevTools/chrome-devtools-mcp（官方 README 原话："Plugin installation provides MCP + Skills"，是官方推荐方式，优于手动配 `mcpServers`）。

**安装步骤（全部用官方 CLI，不手改任何配置文件）：**
```bash
# 1. 先清理所有旧的手动配置（关键，官方 README 明确要求）
Codex mcp remove chrome-devtools

# 2. 添加官方 marketplace
Codex plugin marketplace add ChromeDevTools/chrome-devtools-mcp

# 3. 安装插件（marketplace 名 = chrome-devtools-plugins，插件名 = chrome-devtools-mcp）
Codex plugin install chrome-devtools-mcp@chrome-devtools-plugins

# 4. 重启 Codex (/exit 后重进) 激活插件
```

**默认行为**：插件版 MCP 启动**独立 Chrome 实例**（缓存在 `$HOME/.cache/chrome-devtools-mcp/chrome-profile-stable`），和日常 Chrome 隔离。不会复用登录态，但更稳定，不会因日常 Chrome 标签页多而超时。

### 插件管理铁律（永久配置，2026-04-17 教训）

**NEVER 手改配置文件**：
- ❌ `~/.Codex.json`（全局 mcpServers）
- ❌ `~/.Codex/plugins/config.json`（enabledPlugins）
- ❌ 项目 `.mcp.json`（如果官方插件已覆盖）

**ALWAYS 用官方 CLI**：
| 操作 | 官方命令 |
|---|---|
| 列出插件 | `Codex plugin list` |
| 禁用插件 | `Codex plugin disable <plugin>@<marketplace>` |
| 启用插件 | `Codex plugin enable <plugin>@<marketplace>` |
| 卸载插件 | `Codex plugin uninstall <plugin>@<marketplace>` |
| 刷新 marketplace | `Codex plugin marketplace update <name>` |
| 移除 MCP | `Codex mcp remove <name>` |
| 查看 MCP 连接 | `Codex mcp list` |

### 插件错误诊断官方顺序（2026-04-17 教训）
1. 看 `/plugin` → **Errors** 标签页的精确报错
2. `Codex plugin marketplace update <marketplace>` 刷新 marketplace 缓存
3. 读 `~/.Codex/plugins/marketplaces/<name>/.Codex-plugin/marketplace.json` 完整定义（LSP 插件的真实配置在这里，不在缓存目录）
4. 检查二进制是否在 `$PATH`（LSP 插件依赖用户自备二进制，如 pyright-langserver、typescript-language-server、intelephense、jdtls）
5. **NEVER** 只看缓存目录内容就下结论"占位符"——LSP 插件的 `./plugins/<name>/` 源目录只有 LICENSE+README 是**设计如此**（配置全在 marketplace.json 的 `lspServers` 字段内联）

### 连日常 Chrome（autoConnect，本项目已启用，铁律，2026-04-17）

**当前状态（已验证）**：
- `plugin.json` 里 `mcpServers.chrome-devtools.args` = `["chrome-devtools-mcp@latest", "--autoConnect"]`
- 插件版本 0.21.0，Chrome 147（≥144 要求满足）
- 无项目级 `.mcp.json` / 无全局 `mcpServers` 覆盖，插件配置为唯一生效路径
- 用户诉求："保留登录态，不用一直输入账号密码"——所有需登录站点（得物/淘宝/Midjourney/知网）免重复登录

**配置路径（血泪教训 2026-04-17：真源头是 plugin.json 不是 .mcp.json）**：

Codex **插件**的 MCP 配置入口是 `.Codex-plugin/plugin.json` 的 `mcpServers` 字段，**不是** `.mcp.json`。`.mcp.json` 只是给 gemini-cli / codex 用的兼容副本，Codex 根本不读。

| 文件 | 作用 | 改这里生效吗 |
|---|---|---|
| `~/.Codex/plugins/marketplaces/chrome-devtools-plugins/.Codex-plugin/plugin.json` | **真源头，Codex 读这份** | ✅ **必改** |
| `~/.Codex/plugins/cache/chrome-devtools-plugins/chrome-devtools-mcp/<VERSION>/.Codex-plugin/plugin.json` | 从源头复制的缓存 | ✅ 建议同步改 |
| `~/.Codex/plugins/marketplaces/chrome-devtools-plugins/.mcp.json` | gemini-cli / codex 兼容副本 | ❌ Codex 不读 |
| `~/.Codex/plugins/cache/chrome-devtools-plugins/chrome-devtools-mcp/<VERSION>/.mcp.json` | 兼容副本的缓存 | ❌ Codex 不读 |

**正确流程**：
1. 编辑源头 `plugin.json`：`~/.Codex/plugins/marketplaces/chrome-devtools-plugins/.Codex-plugin/plugin.json`
2. 同步改 cache `plugin.json`：路径里 `<VERSION>` 换成实际版本号（`Codex plugin list | grep chrome-devtools` 查）
3. 在 `mcpServers.chrome-devtools.args` 数组末尾加 `"--autoConnect"`
4. 清理残留 MCP 进程：`pkill -f chrome-devtools-mcp`
5. `/exit` 重启 Codex

**诊断 autoConnect 是否真生效的办法**：
- ❌ `Codex mcp list` 显示 `✓ Connected` 不代表连到了日常 Chrome（只代表 MCP server 启动成功）
- ✅ 调用 `list_pages`，如果看到你日常 Chrome 的标签页标题（如"淘宝"、"得物"）= 连上了
- ❌ 如果只看到 `about:blank [selected]` = MCP 启了独立 Chrome，autoConnect 没生效

**Chrome 侧一次性配置**（用户自己做一次即可，官方 README 原文）：
1. 访问 `chrome://inspect/#remote-debugging`
2. Follow the dialog UI to allow incoming debugging connections
3. 首次 MCP 连接时 Chrome 弹窗点"允许"
4. **多 profile 注意事项**（官方 README 原文）：
   > "If the user has multiple active profiles, the MCP server will connect to the default profile (as determined by Chrome). The MCP server has access to all open windows for the selected profile."
   —— 如果日常 Chrome 开了多个用户身份（个人/工作/测试），autoConnect **只连默认 profile**。要操作非默认 profile 的登录态，必须先在 Chrome 里切到那个 profile 作为默认
5. **端口开启后的警示条**：Chrome 会一直显示顶部黄条 "Chrome 正受到自动测试软件的控制 / 在'设置'中关闭"——这是 Chrome 144+ 的安全提示，属正常现象，不用关闭
6. **安全警告（官方 README 原文）**：
   > "Make sure that you are not browsing any sensitive websites while the debugging port is open."

**改完必做**：`/exit` 重启 Codex 才生效（MCP server 只在启动时读 `.mcp.json`）

**插件升级后重新打补丁的流程**（3 步）：
```bash
# 1. 查新版本号
Codex plugin list | grep chrome-devtools
# 2. 编辑两份 plugin.json（marketplace 源头 + cache 新版本目录）
#    在 mcpServers.chrome-devtools.args 数组末尾加 "--autoConnect"
#    路径模板：
#      ~/.Codex/plugins/marketplaces/chrome-devtools-plugins/.Codex-plugin/plugin.json
#      ~/.Codex/plugins/cache/chrome-devtools-plugins/chrome-devtools-mcp/<X.Y.Z>/.Codex-plugin/plugin.json
# 3. 清理残留 + 重启：pkill -f chrome-devtools-mcp && /exit 后重进
```

**已知限制**：日常 Chrome 标签页 >10 个时，`list_pages` 触发 `Network.enable timed out`（Puppeteer 对每个 tab 激活 Network domain 的累积超时，官方 troubleshooting 无 workaround）。解决：临时关闭重负载标签页（视频网站 / Gmail / Midjourney 等）。

**使用铁律**：
- 已登录网站 MUST 用 `select_page` 选已有标签页，NEVER 用 `navigate_page`（会触发 Cloudflare 验证 + 丢登录态）
- 不要同时跑爬虫——爬虫用 Playwright MCP（隔离环境），避免日常账号被风控

**官方故障排查 4 条件清单**（autoConnect 连接失败时逐条检查，来源：官方 troubleshooting.md 原文）：
1. Chrome 144+ is **already** running.
2. Remote debugging is enabled in Chrome via `chrome://inspect/#remote-debugging`.
3. You have allowed the remote debugging connection prompt in the browser.
4. There is no other MCP server or tool trying to connect to the same debugging port.

**官方故障排查文档**：https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/docs/troubleshooting.md
**官方 README**：https://github.com/ChromeDevTools/chrome-devtools-mcp（所有配置描述以 README 为准，本节内容已逐条对照 2026-04-17 版 README 验证）

### React 应用输入框自动化（核心模式）
- **NEVER 用 `fill` + MCP `press_key Enter`**——对 React 应用不可靠，fill 不触发 React onChange
- **正确方式**（已验证，适用于 Midjourney 等所有 React 应用）：
  ```javascript
  // 1. 用 nativeInputValueSetter 设值（绕过 React 控制）
  const nativeSetter = Object.getOwnPropertyDescriptor(
    window.HTMLTextAreaElement.prototype, 'value'
  ).set;
  nativeSetter.call(textarea, promptText);
  
  // 2. 派发 input 事件触发 React 状态更新
  textarea.dispatchEvent(new Event('input', { bubbles: true }));
  
  // 3. 等待 React 处理
  await new Promise(r => setTimeout(r, 500));
  
  // 4. 派发 KeyboardEvent 提交（不是 MCP press_key）
  textarea.dispatchEvent(new KeyboardEvent('keydown', {
    key: 'Enter', code: 'Enter', bubbles: true
  }));
  ```
- 批量提交时每次间隔 2 秒，避免被限流
- 提交成功的标志：`textarea.value === ''`（输入框被清空）

### Midjourney 特定经验
- Midjourney 有 Cloudflare 反机器人验证，必须用 autoConnect 连接用户已有标签页
- NEVER 用 `navigate_page` 打开 Midjourney——会触发 Cloudflare 验证
- 直接用 `select_page` 选中用户已打开的 Midjourney 标签页
- 图片 CDN URL 格式：`https://cdn.midjourney.com/{job-id}/0_0.jpeg`（全尺寸）
- 每个 job 有 4 个变体（index 0-3）

### Codex 升级规则
- 用 `Codex update` 升级，NEVER 用 `brew upgrade Codex`（Homebrew stable channel 版本落后）
- 官方推荐安装方式：`curl -fsSL https://Codex.ai/install.sh | bash`（原生安装，自动更新）

### Codex-hud 插件布局修复（0.0.12 版本 bug）
- 更新 Codex-hud 后 HUD 从横排变竖排，是 0.0.12 的 bug
- **根因**：`UNKNOWN_TERMINAL_WIDTH = 40` 太窄，Codex statusline 子进程检测不到终端宽度时回退到 40 字符，导致 Context+Usage 永远被拆成多行
- **修复**：`~/.Codex/plugins/cache/Codex-hud/Codex-hud/0.0.12/dist/utils/terminal.js` 中 `UNKNOWN_TERMINAL_WIDTH` 从 40 改为 200
- **配置**：`~/.Codex/plugins/Codex-hud/config.json` 的 `lineLayout` 必须是 `"expanded"`（不是 `"compact"`，横排布局就是 expanded 模式）
- **注意**：插件更新会覆盖此补丁，如果又变竖排，重新改 `UNKNOWN_TERMINAL_WIDTH = 200` 即可

## 需求文档写法（IMPORTANT）

- 需求文档写简洁版，NEVER 用大厂冗长PRD模板
- 每个需求只写三部分：**问题**（一句话）→ **要做的事**（3-4条）→ **优先级**
- 不要写：用户故事、验收标准（AC）、名词解释、非功能需求、业务流程图、成功指标
- 末尾附"需要确认的问题"列表
- 目标：兵哥2-3分钟看完就知道要做什么

## 工具安装规则（IMPORTANT）

- 安装任何第三方工具、MCP、插件时，MUST 先查官方文档（GitHub README / npm 页面），NEVER 凭经验猜步骤
- 用 `npm view <pkg> homepage` 找到官方仓库，按 README 步骤执行
- 不添加官方文档之外的"优化"（如自定义 alias、手动配置端口等）
- 用户说"官方"时，必须提供有出处的步骤

## 前端设计规范（DESIGN.md）

- 做前端页面时 MUST 先读取项目根目录的 `DESIGN.md`，按其中的色板、字体、组件样式、布局规则生成 UI
- 设计素材库位于 `~/Projects/awesome-design-md/design-md/`，包含 58+ 个知名网站的设计系统
- 切换设计风格：`cp ~/Projects/awesome-design-md/design-md/<网站名>/DESIGN.md ./DESIGN.md`
- 如果项目根目录没有 DESIGN.md，提醒用户先选一个设计风格

## 阿里云 CLI 使用规则（IMPORTANT）

- 安装方式：`brew install aliyun-cli`，升级用 `brew upgrade aliyun-cli`
- 凭证配置在 `~/.aliyun/config.json`，NEVER 在代码中硬编码 AccessKey
- 默认 Region：`cn-hangzhou`，其他区域用 `--RegionId` 参数指定
- zsh 中调用含 `[]` 的参数必须加引号，如 `'rows=Regions.Region[]'`，否则 zsh 当 glob 解析报错
- 部署相关操作（ECS、SLB、RDS）MUST 先确认目标区域和实例 ID，避免误操作生产环境
- 查看帮助：`aliyun help`，查看某个产品：`aliyun ecs help`

## 爆品推同步登录态排查铁律（IMPORTANT，2026-05-25）

- `baopintui-sync` 批次停在某个时间点时，NEVER 只看 cookie 名称就断言“爆品推登录失效”或“launchd 没跑”。
- 必须按顺序核实：① `launchctl list | rg baopintui` 看 4 个 job 是否触发 ② tail 对应 job 日志看真实错误 ③ 用当前 Chrome cookies 对爆品推真实接口发一次只读请求，看是否 `code=200`。
- 2026-05-25 事故：脚本强制要求 `_identity + PHPSESSID`，但 Chrome 已不再保留 `_identity`；实测爆品推接口只靠 `PHPSESSID` 仍能返回 `code=200`。过度严格的前置校验误杀了订单、红包、渠道红包账单三个 job。
- 后续原则：`_identity` 视为易变辅助 cookie，不能作为硬门槛；登录态是否可用以真实接口响应为准。只有真实请求返回 302/401/code 非 200，才要求用户重新登录。
- 已修复参考：`/Users/tkag/Projects/baopintui-sync` commit `66e68ad`，`REQUIRED_COOKIES = {"PHPSESSID"}`，并增加 `_identity` 缺失但 session cookie 存在时允许初始化的回归测试。

## 环境变量

必需的环境变量在 `.env` 中配置，参考 `config/settings.py` 中的 Settings 类。
永远不要在代码中硬编码密钥、API Key 或数据库密码。
