# GitHub 上传指引（照着做即可）

## 零、先确认：要传什么

本文件夹 `重复文件查找器-GitHub仓库` 已经是**可直接上传的仓库内容**：

```
README.md              仓库首页说明（GitHub 上展示的就是它）
LICENSE                MIT 开源协议
.gitignore             排除本机数据与大文件
finder_app.py          后端
app.html               前端页面
启动重复文件查找器.bat   Windows 启动脚本
使用说明.md            使用说明
打包说明.md            免安装版制作流程
SKILL.md               WorkBuddy 技能描述（可选能力）
```

**绝对不要上传**：`index.json`（含你电脑上全部文件路径）、`settings.json`、`deletions.json`、`log.txt`、`python\` 目录、`*.zip` —— 这些已在 `.gitignore` 里排除。

## 一、准备工作（只需做一次）

1. **GitHub 账号**：https://github.com 注册，邮箱需验证。
2. **选择上传方式**（三选一，推荐 A）：
   - **A. GitHub Desktop（最省事，图形界面）**：https://desktop.github.com 下载安装并登录。
   - **B. 网页拖拽**：无需安装软件，但**只能传文件、不能传空文件夹**，且一次最多 100 个文件。
   - **C. 命令行 git**：你电脑上已装 Git（`C:\Program Files\Git\cmd\git.exe`）。
3. **网络**：github.com 访问不畅时，可开代理或用国内镜像（如 gitclone.com 代理前缀），公司网络需确认是否放行。
4. **设置 git 身份**（仅命令行方式需要，做一次即可）：
   ```bash
   git config --global user.name "你的名字"
   git config --global user.email "你的邮箱"
   ```

## 二、创建仓库

1. 登录 GitHub → 右上角 `+` → **New repository**
2. 填写：
   - Repository name：`dup-file-finder`（英文更通用；也可以写 `重复文件查找器`）
   - Description：`Windows 重复文件查找与清理工具（纯 Python 标准库 + 网页界面）`
   - 选 **Public**（公开，别人能搜到）或 **Private**（仅自己/指定的人可见）
   - **不要**勾选 "Add a README file"（我们已有 README，勾了会和本地冲突）
   - **不要**勾选 Add .gitignore / Choose a license（我们已有）
3. 点 **Create repository**，记下仓库地址，形如：
   `https://github.com/你的用户名/dup-file-finder.git`

## 三、上传（三种方式任选）

### A. GitHub Desktop（推荐）

1. 打开 GitHub Desktop → `File` → `Add local repository` → 选择本文件夹
   （若提示"不是 git 仓库"，点 "create a repository" 就地初始化）
2. 左下填写 Summary（如 `首次提交`）→ **Commit to main**
3. 顶部 **Publish repository** → 填名字、取消勾选 "Keep this code private" 若要公开 → Publish

### B. 网页拖拽（无需安装）

1. 进入新建的空仓库页面，点 **uploading an existing file**（或 `Add file` → `Upload files`）
2. 把本文件夹里的**所有文件和文件夹**拖进去
3. 底部填提交信息 → **Commit changes**
4. 注意：文件夹（如里面有子目录）需逐个进入后上传；ZIP 附件走 Release，不走这里。

### C. 命令行（我已帮你初始化好本地仓库时，只需最后两条）

```bash
cd "D:\BaiduSyncdisk\workbuddy同步工作\工具\重复文件查找器-GitHub仓库"
git init                                   # 若已初始化可跳过
git add .
git commit -m "首次提交：重复文件查找器"
git remote add origin https://github.com/你的用户名/dup-file-finder.git
git branch -M main
git push -u origin main                    # 会弹窗登录 GitHub
```

`git push` 时的认证：浏览器登录即可；如用命令行登录，需用 **Personal Access Token**（GitHub → Settings → Developer settings → Personal access tokens → 勾选 `repo`）代替密码。

## 四、发布「免安装版」给同事（重要）

10MB 的内置 Python 包**不适合进 Git 仓库**，应作为 Release 附件：

1. 仓库页面右侧 **Releases** → **Create a new release**
2. Tag version 填 `v1.0`，标题填 `v1.0 免安装版（内置 Python）`
3. 把 `重复文件查找器_免安装版.zip`（10.4MB）**拖到下方 Attach binaries 区域**
4. 点 **Publish release**
5. 之后同事直接从 Releases 页面下载 ZIP 即可，README 里也建议加一句下载说明。

## 五、以后更新版本

改完代码后（以 GitHub Desktop 为例）：修改文件 → 左下填 Summary → Commit → 右上角 **Push origin**。
命令行则是 `git add . && git commit -m "说明" && git push`。

## 六、常见问题

- **`git push` 被拒绝 / 要输入密码**：密码处应填 Personal Access Token，不是账号密码。
- **提示文件太大**：确认 `python\` 和 `*.zip` 未被 `git add`（`.gitignore` 已排除）；若误加，用 `git rm --cached -r python`。
- **中文文件名乱码**：提交无碍，GitHub 网页能正常显示；命令行显示乱码可执行 `git config --global core.quotepath false`。
- **想让别人也能改进**：README 里可加一句"欢迎 Issue 与 PR"。
