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

### autoConnect 连接用户已有 Chrome（必须步骤）
1. Chrome 版本 >= 144，打开 `chrome://inspect/#remote-debugging` 启用远程调试
2. MCP 配置必须包含 `--autoConnect`：
   ```json
   {
     "chrome-devtools": {
       "command": "npx",
       "args": ["chrome-devtools-mcp@latest", "--autoConnect", "--logFile=/tmp/chrome-devtools-mcp.log"]
     }
   }
   ```
3. **项目级 mcpServers 会覆盖全局配置**——两边都要加 `--autoConnect`
4. 修改配置后必须 `/exit` 重启 Claude Code 才生效
5. 首次连接时 Chrome 会弹出"允许远程调试"对话框，用户点允许
6. 连接成功后 `list_pages` 能看到用户所有已打开的标签页

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

### Claude Code 升级规则
- 用 `claude update` 升级，NEVER 用 `brew upgrade claude-code`（Homebrew stable channel 版本落后）
- 官方推荐安装方式：`curl -fsSL https://claude.ai/install.sh | bash`（原生安装，自动更新）

### claude-hud 插件布局修复（0.0.12 版本 bug）
- 更新 claude-hud 后 HUD 从横排变竖排，是 0.0.12 的 bug
- **根因**：`UNKNOWN_TERMINAL_WIDTH = 40` 太窄，Claude Code statusline 子进程检测不到终端宽度时回退到 40 字符，导致 Context+Usage 永远被拆成多行
- **修复**：`~/.claude/plugins/cache/claude-hud/claude-hud/0.0.12/dist/utils/terminal.js` 中 `UNKNOWN_TERMINAL_WIDTH` 从 40 改为 200
- **配置**：`~/.claude/plugins/claude-hud/config.json` 的 `lineLayout` 必须是 `"expanded"`（不是 `"compact"`，横排布局就是 expanded 模式）
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

## 环境变量

必需的环境变量在 `.env` 中配置，参考 `config/settings.py` 中的 Settings 类。
永远不要在代码中硬编码密钥、API Key 或数据库密码。
