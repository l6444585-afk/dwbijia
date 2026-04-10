# 操控 Chrome DevTools MCP 指南

## 一、前置配置

### 1. Chrome 开启远程调试
在 Chrome 地址栏输入：
```
chrome://inspect/#remote-debugging
```
勾选 **"Allow remote debugging for this browser instance"**，页面会显示 `Server running at: 127.0.0.1:9222`。

### 2. MCP 配置（.claude.json）
```json
{
  "mcpServers": {
    "chrome-devtools": {
      "type": "stdio",
      "command": "npx",
      "args": [
        "chrome-devtools-mcp@latest",
        "--autoConnect",
        "--logFile=/tmp/chrome-devtools-mcp.log"
      ],
      "env": {}
    }
  }
}
```

### 3. 致命坑：项目级配置覆盖全局
`.claude.json` 中有两层 `mcpServers`：
- **全局**：顶层的 `"mcpServers": {}`
- **项目级**：`"projects"."/path/to/project"."mcpServers": {}`

**项目级会完全覆盖全局同名配置。** 如果全局加了 `--autoConnect` 但项目级没加，项目里就不生效。两边都要配。

### 4. 修改配置后必须重启
```bash
# 在 Claude Code 里
/exit
# 重新进入
claude
```
MCP 只在启动时读取配置。

---

## 二、连接流程

### 连接用户已有的 Chrome
```
1. 用户打开 Chrome，正常浏览（已登录各网站）
2. 启动 Claude Code（MCP 自动通过 autoConnect 连接）
3. Chrome 弹出对话框："允许远程调试？"→ 用户点允许
4. list_pages 能看到用户所有标签页
5. select_page 选中目标标签页
```

### 绝对禁止
- ❌ NEVER 用 `navigate_page` 打开已登录网站（触发 Cloudflare 验证、丢失登录态）
- ❌ NEVER 新开标签页访问 Midjourney、知网等需要登录的网站
- ✅ ALWAYS 用 `select_page` 选中用户已打开的标签页

---

## 三、常用操作

### 列出所有标签页
```
mcp__chrome-devtools__list_pages
```

### 选中标签页
```
mcp__chrome-devtools__select_page(pageId=10, bringToFront=true)
```

### 页面快照（推荐保存到文件避免 token 超限）
```
mcp__chrome-devtools__take_snapshot(filePath="/tmp/snapshot.md")
```
然后用 `Grep` 工具搜索关键元素的 uid。

### 点击元素
```
mcp__chrome-devtools__click(uid="1_98")
```

### 填写输入框（仅限非 React 应用）
```
mcp__chrome-devtools__fill(uid="1_98", value="搜索内容")
```

### 执行 JavaScript
```
mcp__chrome-devtools__evaluate_script(function="() => { return document.title }")
```

---

## 四、React 应用输入框自动化（核心）

### 为什么 fill + press_key 不行？
React 用虚拟 DOM 管理状态。MCP 的 `fill` 工具直接修改 DOM 值，但不触发 React 的 `onChange` 回调，导致 React 内部状态不更新。MCP 的 `press_key` 也不走 React 事件系统。

**结果：文本看似输入了，但提交时 React 读到的是空值。**

### 正确方式：evaluate_script
```javascript
// 单次提交
async () => {
  const textarea = document.querySelector('textarea');
  const nativeSetter = Object.getOwnPropertyDescriptor(
    window.HTMLTextAreaElement.prototype, 'value'
  ).set;
  
  // 1. 用原生 setter 设值（绕过 React 控制）
  nativeSetter.call(textarea, '你的 prompt 内容');
  
  // 2. 派发 input 事件让 React 感知变化
  textarea.dispatchEvent(new Event('input', { bubbles: true }));
  
  // 3. 等 React 处理
  await new Promise(r => setTimeout(r, 500));
  
  // 4. 派发 Enter 键提交
  textarea.dispatchEvent(new KeyboardEvent('keydown', {
    key: 'Enter',
    code: 'Enter',
    bubbles: true
  }));
  
  // 5. 验证提交成功
  await new Promise(r => setTimeout(r, 1000));
  return textarea.value === ''; // true = 成功
}
```

### 批量提交模板
```javascript
async () => {
  const prompts = [
    "prompt 1 --ar 4:3 --s 750",
    "prompt 2 --ar 4:3 --s 750",
    // ...更多
  ];
  
  const textarea = document.querySelector('textarea');
  const nativeSetter = Object.getOwnPropertyDescriptor(
    window.HTMLTextAreaElement.prototype, 'value'
  ).set;
  const results = [];
  
  for (let i = 0; i < prompts.length; i++) {
    textarea.focus();
    nativeSetter.call(textarea, prompts[i]);
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
    await new Promise(r => setTimeout(r, 500));
    
    textarea.dispatchEvent(new KeyboardEvent('keydown', {
      key: 'Enter', code: 'Enter', bubbles: true
    }));
    await new Promise(r => setTimeout(r, 2000)); // 间隔 2 秒防限流
    
    results.push({ index: i, success: textarea.value === '' });
  }
  return results;
}
```

### 对 input 元素（非 textarea）的变体
```javascript
// input 元素用 HTMLInputElement.prototype
const nativeSetter = Object.getOwnPropertyDescriptor(
  window.HTMLInputElement.prototype, 'value'
).set;
```

---

## 五、下载图片

### 从 Midjourney CDN 直接下载
图片 URL 格式：
```
https://cdn.midjourney.com/{job-id}/0_0.jpeg      # 全尺寸，变体 1
https://cdn.midjourney.com/{job-id}/0_1.jpeg      # 全尺寸，变体 2
https://cdn.midjourney.com/{job-id}/0_0_640_N.webp # 缩略图
```

提取所有 job ID：
```javascript
() => {
  const links = document.querySelectorAll('a[href*="/jobs/"]');
  const jobs = new Set();
  links.forEach(l => {
    const m = l.href.match(/\/jobs\/([a-f0-9-]+)/);
    if (m) jobs.add(m[1]);
  });
  return Array.from(jobs);
}
```

批量下载：
```bash
curl -o story_03.png "https://cdn.midjourney.com/{job-id}/0_0.jpeg"
```

---

## 六、知网等传统网站操作

知网等非 React 网站可以直接用 MCP 工具：
```
# 导航
navigate_page(type="url", url="https://www.cnki.net/")

# 填写搜索框
fill(uid="9_39", value="搜索关键词")

# 点击搜索
click(uid="9_40")

# 获取快照
take_snapshot(filePath="/tmp/cnki.txt")
```
这些网站不需要 `evaluate_script` 的 React hack。

---

## 七、故障排查

| 问题 | 原因 | 解决 |
|------|------|------|
| `list_pages` 只看到 `about:blank` | autoConnect 未生效 | 检查项目级 mcpServers 是否缺少 `--autoConnect` |
| Cloudflare 验证拦截 | 用 navigate_page 打开了新页面 | 用 select_page 选已有标签页 |
| fill 输入后提交无效 | React 应用 | 改用 evaluate_script + nativeSetter |
| 修改配置不生效 | MCP 未重启 | `/exit` 然后 `claude` 重进 |
| Chrome 没弹授权对话框 | 未开启远程调试 | 去 `chrome://inspect/#remote-debugging` 开启 |
| `brew upgrade` 降级了 | Homebrew 跟踪 stable channel | 用 `claude update` 升级 |

---

## 八、完整工作流示例：Midjourney 批量生图

```
1. 确认 Chrome 已开远程调试 + MCP 配了 --autoConnect
2. 用户在 Chrome 打开 midjourney.com/imagine 并登录
3. Claude Code 启动 → list_pages 找到 Midjourney 标签页
4. select_page 选中该标签页
5. evaluate_script 批量提交 prompt（nativeSetter + keydown Enter）
6. 等待生成完成
7. evaluate_script 提取所有 job ID
8. curl 批量下载图片到本地
9. 按编号重命名 story_XX.png
```
