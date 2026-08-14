# TokenMon

精灵球样式的悬浮窗,实时监控 LLM 网关的 token 用量(输入/输出/推理/缓存命中/会话统计/成本),**Windows 与 Linux 双平台**,支持系统托盘与最近对话列表。

> **两个实现**:'tauri/' 为 **Tauri(Rust + 系统 WebView)精简版**,发布体积 **~10-15MB**(对标 cc_switch 架构,Windows 用系统自带 WebView2,Linux 用系统 webkit2gtk);根目录 'tokenmon.py' 为 **Tkinter 标准库版**(零运行时依赖,冻结 ~36MB)。两者共用同一套配置格式与数据逻辑,任选其一。

## 界面

**精灵球悬浮球**(红白 Poké Ball,常驻置顶,可拖动到任意位置,球身显示 token 用量缩写;点击时**上半球向上、下半球向下分离**(保留原始半球形状,不拉伸),面板从**两半中间**展开——球与面板是同一个窗口,天然跟随球的位置;打开后窗口呈"球 + 面板"组合形,外侧带**主题色描边**(精灵球红 / 大师球紫 / 超级球蓝 / 高级球黄):

```text
    合拢态:                     打开态(上半上移、下半下移,面板从中间展开):
    ╭────────╮                ╭────╮─────────────────────╮
    │  2.2M  │                │ ◗◗◗◗│ ← 上半球(原始形状)   │
    │━━━━━━━━│                │ ━━━━│                     │
    │   ◎    │                │ ● TokenMon ⟳ ×      │ ← 面板(宽 200px,
    ╰────────╯                │ Token 用量  2,215,154 │    主题色描边)
                              │ 缓存命中  1,988,736   │
                              │ 费用      ¥0.3755     │
                              │   [详情][对话][皮肤]    │
                              │ 127.0.0.1:8080/…     │
                              │ ━━━━│                     │
                              ╰────╯─────────────────────╯
```

- 面板各统计行按网关类型自动取舍(deepseek/openrouter 无 total 与 cache,litellm 无 cache,custom 按 [gateway.fields] 映射缺失即隐藏);费用/余额按配置的 currency 显示。
- **详情** 下拉:Prompt / Completion / Reasoning / Cache Miss / Session Hit / Session Miss / 本会话增量 / 实时速率。
- **最近对话** 面板:最近 N 次对话的 prompt 与 token 总量(litellm 按 session 聚合,支持分页;custom 按 logs_url)。
- **边缘吸附**:把球拖到屏幕左右边缘(≤48px)自动贴边并旋转 90°;吸附态展开时球横置、左右分离,面板从球与屏幕边缘之间伸出。拖动即解除吸附。
- 开合动画与窗口尺寸逐帧同步(12 帧 × 16ms),两半分离与面板展开速率一致。
- **字体自适应**:球身文字按上半球可用宽度自动缩放字号,永不溢出。

## Tauri 版(推荐, ~10-15MB)

```
tauri/
├── src/                  # 前端: 纯 HTML/CSS/JS(零框架、零构建), 精灵球为内联 SVG 矢量
│   ├── index.html / styles.css / app.js / core.js
│   └── skins/ball_*.svg  # 4 皮肤矢量图(由 Qt 绘制代码一次性导出)
├── src-tauri/            # Rust 后端
│   ├── core/             # tokenmon-core: 数据层(纯 Rust, 独立单测)
│   └── src/lib.rs        # 薄封装: 配置热载 / 抓取转发 / 托盘 / 窗口命令
└── tests/                # node 单测(前端核心逻辑)
```

**构建**(需 Rust stable;Linux 另需 webkit2gtk4.1 开发包):

```bash
# 本地
cd tauri/src-tauri
cargo test -p tokenmon-core        # 数据层单测
cd ../.. && node --test tests/     # 前端核心单测
cargo tauri build                  # 产出 Windows NSIS exe / Linux deb+rpm+AppImage

# CI(推荐): 打 v2 标签自动构建并发布到 GitHub Release
git tag v2.0.0 && git push origin v2.0.0
```

运行依赖:Windows 10/11 自带 WebView2;Linux 需 'sudo dnf install webkit2gtk4.1'(Fedora)。

> **Linux 开发提示**:窗口尺寸必须用**逻辑坐标**(LogicalSize/LogicalPosition),物理值在 HiDPI(scale≠1)下会被窗口系统二次缩放;'resizable' 在 X11 下需为 true 才能程序化 resize(无边框窗口用户无法手动改尺寸,不影响使用)。
>
> **冒烟测试**:设 'TOKENMON_SMOKE_OPEN=1' 启动会自动展开/收起面板并抓取窗口快照到 /tmp/tmtest/(Linux webkit snapshot,无需截图工具)。

## Tkinter 版(Python 标准库,零依赖)

```bash
python3 tokenmon.py            # 首次运行自动生成配置
python3 tokenmon.py --once     # 只抓取一次用量并打印(无需 GUI)
python3 -m pytest tests/       # 48 个单元测试
```

打包(见 'packaging/'):'build_win.bat'(Windows 一键 PyInstaller, ~36MB)、'build_rpm.sh'(Fedora RPM)。

## 配置

首次运行自动生成 'config.toml'(Windows: '%APPDATA%/tokenmon/config.toml';Linux: '~/.config/tokenmon/config.toml'),支持三种网关:

| 网关 | base_url | api_key | 说明 |
|---|---|---|---|
| custom | 任意 JSON 统计接口 | Bearer | 字段路径用 [gateway.fields] 映射,默认适配 Claude Code 风格(cacheHitTokens/reasoningTokens…) |
| litellm | http://host:4000 | x-api-key | /usage 兼容各版本(api_keys/data 列表聚合) |
| openrouter | 留空 | 必填 | 官方 /api/v1/auth/key,credit 自动换算为美元 |
| deepseek | 留空或官方地址 | 必填 | 余额查询(¥/$),赠送+充值-余额推算已用 |

体验演示:base_url 填 'mock://usage' 即可看到假数据,无需真实网关。

## 操作

| 操作 | 效果 |
|---|---|
| 点击精灵球 | 展开 / 收起面板(球两半上下分离,面板从中间展开) |
| 拖动精灵球 | 移动;拖到屏幕左/右边缘自动吸附并旋转 90° |
| 精灵球右键 | 菜单:展开/收起面板、刷新、**皮肤**(精灵球/大师球/超级球/高级球)、设置(窗口置顶 / 编辑配置 / 打开配置目录 / 重载配置)、退出 |
| 托盘图标左键 | 展开/收起面板;若悬浮球被隐藏(× 或窗口管理器关闭),点击托盘重新拉起 |
| 托盘图标右键 | 与右键菜单相同的完整菜单 |
| Esc / 点击精灵球 | 收起(回到精灵球) |
| 主界面 ⟳ | 手动立即刷新用量与最近对话 |
| 主界面 详情 | 从按钮处弹出其余数据下拉 |
| 主界面 设置 | 二级菜单:**编辑配置**(默认编辑器打开)/ **打开配置目录** / **重载配置**(改完立即生效,无需重启) |
| 主界面 对话 | 展开最近对话面板(prompt + token 总量) |
| 主界面 × | 隐藏悬浮球(托盘可重新拉起;托盘菜单「退出」才真正退出) |

## 常见问题

**Tauri 版托盘图标不可用(GNOME)**:需 AppIndicator 扩展:

```bash
sudo dnf install gnome-shell-extension-appindicator
gnome-extensions enable appindicatorsupport@rgcjonas.gmail.com   # 注销重登生效
```

**置顶(always_on_top)**:Windows/X11 原生生效;Wayland 没有置顶协议,合成器(GNOME/KDE)会忽略该标志,不影响使用。配置默认开启;也可在「设置 → 窗口置顶」随时切换。

**透明窗口**:Tauri 版依赖合成器实现透明(Windows 原生支持;GNOME/KDE 默认合成;无合成器的 X11 会话下球会带底色,建议在桌面环境内使用)。

**菜单定位**:球与面板是**同一个窗口**——打开时上半球向上、下半球向下分离(保留原始半球形状),面板从两半中间展开,球心在屏幕上保持不动、也不左右平移;窗口呈"球 + 面板"组合形(宽 200px),外侧带**主题色描边**。收起时一切复位。

**"实时"粒度**:取决于网关接口与 refresh_seconds(默认 5s);悬浮球显示"程序运行期间的新增用量(会话增量)"与实时速率,毫秒级需网关注入钩子。

**球身文字会溢出吗?**:不会。文字按球身上半圆的实际可用宽度自动缩放字号(最小 6pt,十几位数字也能完整放下);金额 ≥1000 自动用紧凑格式(如 ¥1.2k),精确值看主界面「费用/余额」行。

## 文件

- 'tauri/' — Tauri(Rust + WebView)精简版:前端(HTML/CSS/JS + SVG 矢量皮肤)+ Rust 数据层与后端
- 'tokenmon.py' — Tkinter 版主程序(单文件;纯逻辑区在 'tokenmon_core.py')
- 'tokenmon_core.py' — 数据层(纯标准库:配置/抓取/解析/格式化,两版共用逻辑来源)
- 'tokenmon.bat' — Windows 免控制台启动器
- 'install.sh' — Linux 一键安装到 ~/.local(服务文件直接复用根目录模板)
- 'packaging/' — RPM 打包 + Windows PyInstaller 构建(build_win.bat) + 资产生成
- 'config.toml.example' — 配置示例
- 'tests/' — pytest 单元测试(解析 / 配置 / 格式化 / 抓取)
- 'assets/' — 预渲染精灵球位图与矢量图(4 皮肤)
- 'LICENSE' / '.gitignore' — MIT 许可证与仓库忽略规则
