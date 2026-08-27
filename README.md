# TokenMon Pet

一个“精灵球收纳桌面宠物”式的 LLM 网关监控器。它在本地轮询网关的
token、缓存、费用或余额数据；点击悬浮球，球体打开、伙伴出现，并在同一
透明窗口中展示统计卡。不会调用模型，也不会额外消耗 token。

![License](https://img.shields.io/badge/license-MIT-blue.svg)

## 特性

- Tauri 桌面版：Windows 使用系统 WebView2，Linux 使用系统 WebKit；不捆绑浏览器运行时。
- 单一透明窗口与原生托盘：隐藏后可由托盘重新拉起。
- 四位伙伴：皮卡丘、小火龙、杰尼龟、妙蛙种子；支持随机、手选和锁定。
- 宠物状态由本地数据驱动：等待、巡查、活跃、错误、休息。
- 四款球体皮肤：精灵球、超级球、高级球、大师球；皮肤与伙伴选择会保存。
- 兼容 LiteLLM、OpenRouter、DeepSeek 余额接口和可配置的 custom JSON 网关。
- 根目录 `tokenmon.py` 仍可用作不启动 GUI 的诊断 CLI。

## 界面与交互

合拢时球体轻微呼吸。展开时面板以 Genie 风格从球体中线拉出，伙伴从中间出现。
为兼容 Wayland/XWayland 的窗口定位限制，展开态的球体会滑入面板中心，收起时随
面板平滑滑回原位；不会在最后一帧突然跳位。

- 左键球体：展开或收起。
- 拖动球体：移动位置；在支持的桌面会话中，靠近左右边缘会自动吸附。
- 右键球体：刷新、伙伴、皮肤、设置和退出。
- 托盘左键：显示/隐藏悬浮球；托盘菜单的「展开面板」会先恢复隐藏窗口。
- `×`：仅隐藏悬浮球；从托盘选择「退出」才会结束程序。

统计卡按网关能力自动显示 Token、缓存、费用、余额四项数据；没有的字段会隐藏。

## 快速开始

### Linux

需要 Rust stable、WebKitGTK 和 Linux 状态栏托盘支持。Fedora 示例：

```bash
sudo dnf install webkit2gtk4.1 libappindicator-gtk3
git clone https://github.com/Tak1naa/Widgets.git
cd Widgets/tauri/src-tauri
cargo build --release
cd ../..
./install.sh
```

安装后：

```bash
tokenmon                 # 启动桌面宠物
tokenmon-cli --once --logs  # 诊断抓取与最近对话
```

若 GNOME 看不到托盘图标，安装并启用 AppIndicator 扩展后重新登录：

```bash
sudo dnf install gnome-shell-extension-appindicator
gnome-extensions enable appindicatorsupport@rgcjonas.gmail.com
```

### Windows

Windows 10/11 通常已包含 WebView2。安装 Rust 后运行：

```bat
packaging\build_win.bat
```

构建会生成 Tauri 的 NSIS 安装包。也可在仓库根目录运行 `tokenmon.bat` 启动已经构建的程序。

## 配置

首次运行会创建配置文件：

- Linux：`~/.config/tokenmon/config.toml`
- Windows：`%APPDATA%\tokenmon\config.toml`

可参考仓库中的 [`config.toml.example`](config.toml.example)。支持的 gateway type：

- `litellm`：聚合 `/usage` 数据，可选最近日志。
- `openrouter`：读取 API key 的额度与消费。
- `deepseek`：读取余额；官方接口没有 token 用量端点。
- `custom`：通过 `[gateway.fields]` 把任意 JSON 字段路径映射为 Token、缓存、费用等指标。

将 `base_url` 设置为 `mock://usage` 可在没有真实网关时体验界面。

## 开发与验证

```bash
# Rust 数据层与 Tauri 工作区
cd tauri/src-tauri
cargo test -p tokenmon-core
cargo check --workspace --offline

# 前端纯逻辑
cd ..
node --test tests/core.test.mjs

# 发布构建
cd src-tauri
cargo build --release
```

Linux 下设置 `TOKENMON_SMOKE_OPEN=1` 可触发自动开合的本地冒烟快照钩子。

## 项目结构

```text
tauri/
├── src/                 # 无框架 HTML / CSS / JavaScript 前端
│   ├── skins/           # 四款球体 SVG
│   └── companions/      # 伙伴 SVG 与素材归属说明
├── src-tauri/           # Rust 后端与 tokenmon-core 数据层
└── tests/               # 前端纯逻辑测试
tokenmon.py              # Python 诊断 CLI
tokenmon_core.py         # Python 诊断数据层
install.sh                # Linux 安装器
```

伙伴素材来源、角色权利说明与替换方式见
[`tauri/src/companions/ATTRIBUTION.md`](tauri/src/companions/ATTRIBUTION.md)。项目与
Pokémon、Nintendo、Creatures、GAME FREAK 或 The Pokémon Company 没有隶属关系。

## License

[MIT](LICENSE)
