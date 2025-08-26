# WeRead2Notion-Pro

自动将微信读书的笔记、划线、阅读记录和阅读时间同步到 Notion 数据库。

基于源项目[WeRead2Notion-Pro](https://github.com/malinkang/weread2notion-pro) 修改

## ✨ 功能特性

- 📚 **书籍信息同步**：自动同步微信读书书架中的书籍信息
- 📝 **笔记同步**：同步书籍中的划线和笔记内容
- 📊 **阅读统计**：记录每日阅读时间和进度
- 🌡️ **热力图**：生成阅读时间热力图
- 🔄 **自动同步**：通过 GitHub Actions 定时自动同步
- 🎯 **增量更新**：只同步有变化的内容，避免重复操作

## 🚀 快速开始

### 1. 创建 Notion 集成

1. 访问 [Notion 开发者页面](https://www.notion.so/my-integrations)
2. 点击 "New integration"
3. 填写集成名称，选择工作区
4. 复制生成的 Token（格式为 `secret_xxx`）

### 2. 复制 Notion 模板

1. 访问 [Notion 模板页面]()
2. 点击右上角的 "Duplicate" 复制模板到你的工作区
3. 复制模板页面的 URL 或页面 ID

### 3. 获取微信读书 Cookie

#### 方法 1：手动获取（推荐）
1. 在浏览器中登录微信读书网页版
2. 打开开发者工具（F12）
3. 切换到 Application/Storage 标签页
4. 找到 Cookies 中的 `wr_skey` 值

#### 方法 2：使用 CookieCloud（可选）
1. 访问 [CookieCloud]()
2. 注册账号并获取用户 ID 和密码
3. 安装浏览器插件自动同步 Cookie

### 4. 配置 GitHub Actions

1. Fork 本项目到你的 GitHub 仓库
2. 进入仓库的 Settings → Secrets and variables → Actions
3. 添加以下 Secrets：

| Secret 名称 | 说明 | 示例 |
|-------------|------|-----|
| `NOTION_TOKEN` | Notion 集成 Token | `secret_xxx...` |
| `NOTION_PAGE` | Notion 页面 ID 或 URL | `https://xxx.notion.site/xxx` |
| `WEREAD_COOKIE` | 微信读书 Cookie | `wr_skey=xxx...` |
| `CC_URL` | CookieCloud 服务器地址（可选） |  |
| `CC_ID` | CookieCloud 用户 ID（可选） | `your_id` |
| `CC_PASSWORD` | CookieCloud 密码（可选） | `your_password` |

4. 可选：在 Variables 中自定义数据库名称（使用默认值可不设置）

### 5. 手动触发同步

1. 进入 Actions 页面
2. 选择 "weread note sync" 工作流
3. 点击 "Run workflow" 手动触发同步

## 📋 环境变量配置

复制 `.env.example` 为 `.env` 并填写相关配置：

```bash
# Notion 配置（必需）
NOTION_TOKEN=your_notion_integration_token
NOTION_PAGE=your_notion_page_id_or_url

# 微信读书配置（必需）
WEREAD_COOKIE=your_weread_cookie

# CookieCloud 配置（可选）
CC_URL=https://cookiecloud.com/
CC_ID=your_cookiecloud_id
CC_PASSWORD=your_cookiecloud_password

# 数据库名称（可选，使用默认值可不设置）
BOOK_DATABASE_NAME=书架
REVIEW_DATABASE_NAME=笔记
BOOKMARK_DATABASE_NAME=划线
DAY_DATABASE_NAME=日
# ... 其他数据库名称
```

## 🛠️ 本地运行

### 安装依赖
```bash
pip install -r requirements.txt
pip install -e .
```

### 运行同步命令

```bash
# 同步书籍信息
python -m weread2notionpro.book

# 同步笔记和划线
python -m weread2notionpro.weread

# 同步阅读时间
python -m weread2notionpro.read_time
```

### 测试运行
```bash
# 运行完整测试
python test_workflows.py

# 运行模拟测试（不调用实际API）
python test_workflows.py --simulate
```

## 📊 数据结构

同步完成后，Notion 中将创建以下数据库：

| 数据库名称 | 功能 |
|-----------|------|
| 书架 | 存储书籍基本信息 |
| 笔记 | 存储书籍的想法和评论 |
| 划线 | 存储书籍中的划线内容 |
| 日 | 每日阅读时间记录 |
| 周 | 每周阅读统计 |
| 月 | 每月阅读统计 |
| 年 | 每年阅读统计 |
| 分类 | 书籍分类信息 |
| 作者 | 书籍作者信息 |
| 章节 | 书籍章节信息 |
| 阅读记录 | 详细阅读记录 |
| 设置 | 同步配置信息 |

## 🔧 故障排除

### 常见问题

1. **同步失败**：检查 Cookie 是否过期，重新获取最新的 Cookie
2. **Notion 权限错误**：确认 Notion 集成已添加到对应页面
3. **数据库未创建**：首次运行需要一些时间初始化数据库结构
4. **中文乱码**：确保文件编码为 UTF-8

### 日志查看

- GitHub Actions 日志：在 Actions 页面查看每次运行的详细日志
- 本地日志：查看项目目录下的 `logs/` 文件夹

## 🤝 贡献

欢迎提交 Issue 和 Pull Request 来帮助改进这个项目！




