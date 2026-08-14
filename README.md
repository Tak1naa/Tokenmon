# TokenMon

精灵球样式的悬浮窗,实时监控 LLM 网关的 token 用量(输入/输出/推理/缓存命中/会话统计/成本),**Windows 与 Linux 双平台**,支持系统托盘与最近对话列表。

## 界面

**精灵球悬浮球**(红白 Poké Ball,常驻置顶,可拖动到任意位置,球身显示 token 用量缩写;点击时**上半球向上、下半球向下分离**并拉伸成与窗口同宽的穹顶,面板从**两半中间**展开——球与面板是同一个窗口,天然跟随球的位置;打开后窗口呈**胶囊形**,外侧带**主题色描边**(精灵球红 / 大师球紫 / 超级球蓝 / 高级球黄):

```text
    合拢态:                     打开态(上半上移、下半下移,面板从中间展开):
    ╭────────╮                ╭────────────────╮
    │  2.2M  │                │ ◗◗◗◗◗◗◗◗◗◗◗◗◗◗◗◗ │ ← 上半球(拉伸成与窗口同宽)
    │━━━━━━━━│                │ ━━━━━━━━━━━━━━━━ │
    │   ◎    │                │ ● TokenMon ⟳5s  │ ← 面板(胶囊窗口,主题色描边)
    ╰────────╯                │ Token 用量       │
                              │ 2,215,154        │
                              │ 费用   ¥0.3755   │
                              │  [详情][对话][皮肤] │
                              │ 127.0.0.1:8080/… │
                              │ ━━━━━━━━━━━━━━━━ │
                              │ ◖◖◖◖◖◖◖◖◖◖◖◖◖◖◖◖ │ ← 下半球
                              ╰────────────────╯
```

**主界面**(点击精灵球或托盘图标展开):

```text
      TokenMon
    Token 用量
    2,215,154
    缓存命中
    1,988,736
    费用
    ¥0.3755
    [详情 ▾]
    [对话 ▾]
    [皮肤 ▾]
  ● 127.0.0.1:8080/…
```

**详情下拉菜单**(点 `详情 ▾`,按数据可得性显隐):

```text
Prompt            2,105,876
Completion          109,278
Reasoning            79,503   ← 非推理模型/网关无此字段时自动隐藏
Cache Miss          117,140
Session Hit        1,988,736
Session Miss         117,140
本会话增量            +12,345
实时速率            +12.3 tok/s
```

**最近对话面板**(点 `对话 ▾` 展开,显示最近 N 次对话的 prompt 与 token 总量):

```text
最近对话                       已更新
帮我优化 tokenmon,做成精灵球样式…      123,456
写一个 litellm 网关的用量聚合脚本       88,912
…
```

- **系统托盘图标**: Windows 原生;Linux(GNOME)需 AppIndicator 扩展,不可用时自动降级——精灵球照常工作
- **皮肤系统**: 右键精灵球 → 「皮肤」菜单可切换 **精灵球 / 大师球 / 超级球 / 高级球**,外观按宝可梦官方设定(大师球紫色上半 + 粉色 M 徽记,超级球蓝色上半 + 球内红色侧块,高级球深色上半 + 黄色横纹);主界面「皮肤 ▾」直接平铺四个选项,选择自动保存并同步到托盘图标
- 状态点:绿 = 正常轮询,红 = 抓取出错;状态行显示网关地址与**最近成功更新时间**;抓取失败自动指数退避重试(用量封顶 60s、对话 300s),断网不会硬锤网关

## 快速开始

### Linux(Fedora)

```bash
sudo dnf install python3-pyside6        # 依赖;或 pip install --user PySide6
./install.sh                            # 装到 ~/.local/bin(可选)
python3 tokenmon.py --once              # 验证抓取(无需 GUI)
~/.local/bin/tokenmon                   # 启动精灵球
```

开机自启(install.sh 已生成 service 文件):

```bash
systemctl --user daemon-reload && systemctl --user enable --now tokenmon.service
```

RPM 直装方式照旧:`./packaging/build_rpm.sh` 后 `sudo dnf install ./packaging/rpmbuild/RPMS/x86_64/tokenmon-*.rpm`(依赖 `python3-pyside6` 由 RPM 自动带上)。

### Windows

```bat
pip install pyside6
双击 tokenmon.bat        # pythonw 免控制台启动
```

- 配置文件自动生成于 `%APPDATA%\tokenmon\config.toml`(Linux 为 `~/.config/tokenmon/config.toml`)
- 调试抓取:`python tokenmon.py --once`
- 单实例运行,重复启动会静默退出
- 托盘图标原生支持;关闭主界面 = 收起,托盘菜单/精灵球右键才是退出
- PyInstaller 打包(可选):`pip install pyinstaller && pyinstaller -F -w -n tokenmon tokenmon.py`

## 开发与测试

数据解析 / 配置校验 / 格式化均为无 GUI 依赖的纯函数,可直接跑单元测试(无需 PySide6):

```bash
python3 -m pip install --user pytest
python3 -m pytest -q            # 48 个用例:解析、聚合、配置校验、抓取(mock 网络层)
python3 tokenmon.py --once      # 端到端验证抓取(无需 GUI)
QT_QPA_PLATFORM=offscreen python3 tokenmon.py --smoke 3 --config <配置>  # GUI 冒烟
```

## 配置

首次运行自动生成 `~/.config/tokenmon/config.toml`(含 api_key,权限自动 600),按你的网关编辑:

```toml
[gateway]
type = "custom"            # custom | litellm | openrouter | deepseek
base_url = "http://127.0.0.1:8080/usage"
api_key = ""
refresh_seconds = 5         # >=1 秒,越小越实时,别打爆网关

# 最近对话(主界面"对话"面板)
logs_url = ""              # 仅 custom: 返回最近对话 JSON 数组的地址
logs_limit = 10            # 展示最近 N 条 (1..50)
logs_page_size = 100       # litellm /spend/logs 每页条数
logs_refresh_seconds = 60  # 对话列表刷新间隔(>=10 秒)

[gateway.fields]           # 仅 custom: 程序字段名 = JSON 点分路径
prompt = "promptTokens"
completion = "completionTokens"
reasoning = "reasoningTokens"
cache_hit = "cacheHitTokens"
cache_miss = "cacheMissTokens"
session_cache_hit = "sessionCacheHitTokens"
session_cache_miss = "sessionCacheMissTokens"
total = "totalTokens"
cost = "cost"
currency = "currency"

[window]
always_on_top = true
decorated = false
```

- **custom**:默认字段映射即适配 `cacheHitTokens / reasoningTokens / sessionCacheHitTokens …` 这类结构;你的端点返回同款 JSON 就**不用改映射**。字段缺失自动隐藏对应行。
- **litellm**:请求 `{base_url}/usage`(带 `x-api-key`),兼容多种返回结构,显示 Total + Cost;自动读取 `/spend/logs/v2`(旧版本降级 `/spend/logs/ui` → `/spend/logs`)并按 session 聚合出最近对话列表。
- **openrouter**:请求官方 key 查询接口,返回累计成本(credit 自动换算美元)。
- **deepseek**:官方没有 token 用量统计,改为查询 `/user/balance` 余额(参考 cc_switch 的查询方式),球身与「余额」行显示剩余金额,「费用」按 赠送+充值−余额 推算已用。无 token/缓存/对话数据:主界面自动隐藏「详情」「对话」入口,只保留余额与费用。
- **最近对话数据源**:litellm 全自动;custom 需把 `logs_url` 指向返回下面格式的端点(无则面板显示"无数据"):

```json
[{"prompt": "用户第一句话…", "tokens": 12345, "time": "2026-08-13T10:00:00"}]
```

先用调试模式确认数据:

```bash
tokenmon --once            # 只抓用量
tokenmon --once --logs     # 附带最近对话列表
```

## 使用

| 操作 | 效果 |
| --- | --- |
| 点击精灵球 | 球上下对半打开,面板从两半中间展开(球心保持不动)/ 收起 |
| 拖动精灵球 | 移动位置(支持多屏,面板随窗口一起) |
| 精灵球右键 | 菜单:显示主界面 / **皮肤**(切换球样式)/ 退出 |
| 托盘图标左键 | 展开/收起面板(Windows 原生;GNOME 需 AppIndicator 扩展) |
| Esc / `—` 按钮 | 收起(回到精灵球) |
| 主界面 `详情 ▾` | 从按钮处弹出其余数据下拉 |
| 主界面 `对话 ▾` | 展开最近对话面板(prompt + token 总量) |
| 主界面 `×` 按钮 | 退出 TokenMon |

## 常见问题

**Python 版本**:需 ≥ 3.11(`tomllib` 为标准库)。PATH 里的 `python3` 是 pyenv 等旧版本时,程序会**自动改投系统 Python** 重新运行;安装脚本也固定使用 `/usr/bin/python3`。

**托盘图标不可用(GNOME)**:需 AppIndicator 扩展:

```bash
sudo dnf install gnome-shell-extension-appindicator
gnome-extensions enable appindicatorsupport@rgcjonas.gmail.com   # 注销重登生效
```

不装也能完整使用:程序检测不到托盘宿主时自动降级,精灵球照常工作。

**置顶(always_on_top)**:Windows/X11 原生生效;Wayland 没有置顶协议,状态行会提示,不影响使用。

**菜单定位**:球与面板是**同一个窗口**——打开时上半球向上、下半球向下分离并拉伸成与窗口同宽的穹顶,面板从两半中间展开,球心在屏幕上保持不动、也不左右平移;窗口呈**胶囊形**(宽 200px),外侧带**主题色描边**。X11/Windows 下窗口向上下两侧同步扩展;Wayland 不允许程序移动窗口,改为球在窗口内下移,效果近似。收起时一切复位。

**"实时"粒度**:取决于网关接口与 `refresh_seconds`(默认 5s);悬浮球显示"程序运行期间的新增用量(会话增量)"与实时速率,毫秒级需网关注入钩子。

**球身文字会溢出吗?**:不会。文字按球身上半圆的实际可用宽度自动缩放字号(最小 6pt,十几位数字也能完整放下);金额 ≥1000 自动用紧凑格式(如 `¥1.2k`),精确值看主界面「费用/余额」行。

## 文件

- `tokenmon.py` — 主程序(单文件,纯逻辑区 + Qt 区;`--once` 无需 PySide6)
- `tokenmon.bat` — Windows 免控制台启动器
- `install.sh` — Linux 一键安装到 `~/.local`(服务文件直接复用根目录模板)
- `packaging/` — RPM 打包(`tokenmon.spec` + `build_rpm.sh` + desktop/service 源文件)
- `config.toml.example` — 配置示例
- `tokenmon.service` — systemd 用户服务示例(install.sh 的唯一模板)
- `tests/` — pytest 单元测试(解析 / 配置 / 格式化 / 抓取)
- `LICENSE` / `.gitignore` — MIT 许可证与仓库忽略规则
