//! 配置加载: TOML 解析 + 校验。逻辑与 Python 版 load_config 一致。

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

/// custom 网关字段映射的唯一事实来源: 默认配置文本与抓取逻辑都从这里生成。
pub const DEFAULT_FIELD_MAP: &[(&str, &str)] = &[
    ("prompt", "promptTokens"),
    ("completion", "completionTokens"),
    ("reasoning", "reasoningTokens"),
    ("cache_hit", "cacheHitTokens"),
    ("cache_miss", "cacheMissTokens"),
    ("session_cache_hit", "sessionCacheHitTokens"),
    ("session_cache_miss", "sessionCacheMissTokens"),
    ("total", "totalTokens"),
    ("cost", "cost"),
    ("currency", "currency"),
];

pub const USER_AGENT: &str = "tokenmon/2.0";

fn default_fields() -> BTreeMap<String, String> {
    DEFAULT_FIELD_MAP
        .iter()
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect()
}

pub const DEFAULT_CONFIG: &str = r##"# TokenMon 配置 —— 首次运行自动生成, 编辑后重启生效
# 支持三种网关类型: custom | litellm | openrouter

[gateway]
type = "custom"             # custom | litellm | openrouter | deepseek
base_url = "http://127.0.0.1:8080/usage"   # custom 网关返回 token 统计 JSON 的地址; 体验演示数据可填 "mock://usage"
api_key = ""                # 留空则不发送鉴权头; litellm 用 x-api-key, openrouter/custom 用 Bearer
refresh_seconds = 5         # 用量轮询间隔(秒, >=1), 越小越实时, 别打爆网关

# 最近对话列表(主界面"对话"面板显示最近 N 次对话的 prompt 与 token 总量)
logs_url = ""               # 仅 custom: 返回最近对话 JSON 数组的地址, 留空禁用
logs_limit = 10             # 展示最近 N 条对话 (1..50)
logs_page_size = 100        # litellm /spend/logs 每页条数 (1..1000)
logs_refresh_seconds = 60   # 对话列表刷新间隔(秒, >=10, 独立于 refresh_seconds)

# 仅 custom 类型生效: 程序字段名 = 响应 JSON 中的点分路径。
# 默认映射已适配常见网关返回(如 Claude Code 风格的 cacheHitTokens/reasoningTokens 等);
# 字段缺失时对应行自动隐藏(currency 如 "¥" 或 "$"):
[gateway.fields]
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

# custom 的 logs_url 约定返回 JSON 数组(按时间升序, 最新的在末尾):
#   [{"prompt": "用户第一句话…", "tokens": 12345, "time": "2026-08-13T10:00:00"}]
# 也兼容 {"data": [...]} 信封; tokens 键名接受 tokens/total_tokens/totalTokens。

[window]
always_on_top = true        # 置顶: Windows/X11 原生生效; Wayland 无协议, 尽力而为
decorated = false           # 主界面边框(精灵球永远无边框); 想要系统标题栏可改 true
"##;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct GatewayConfig {
    #[serde(rename = "type")]
    pub gtype: String,
    pub base_url: String,
    pub api_key: String,
    pub refresh_seconds: f64,
    pub logs_url: String,
    pub logs_limit: u32,
    pub logs_page_size: u32,
    pub logs_refresh_seconds: f64,
    /// 旧式配置兼容: tokens_path/cost_path 直接映射 total/cost
    pub tokens_path: Option<String>,
    pub cost_path: Option<String>,
    #[serde(rename = "fields")]
    pub fields: BTreeMap<String, String>,
}

impl Default for GatewayConfig {
    fn default() -> Self {
        GatewayConfig {
            gtype: "litellm".into(),
            base_url: String::new(),
            api_key: String::new(),
            refresh_seconds: 5.0,
            logs_url: String::new(),
            logs_limit: 10,
            logs_page_size: 100,
            logs_refresh_seconds: 60.0,
            tokens_path: None,
            cost_path: None,
            fields: BTreeMap::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct WindowConfig {
    pub always_on_top: bool,
    pub decorated: bool,
}

impl Default for WindowConfig {
    fn default() -> Self {
        WindowConfig {
            always_on_top: true,
            decorated: false,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct AppConfig {
    pub gateway: GatewayConfig,
    pub window: WindowConfig,
}

impl Default for AppConfig {
    fn default() -> Self {
        AppConfig {
            gateway: GatewayConfig::default(),
            window: WindowConfig::default(),
        }
    }
}

/// 配置文件所在目录(与 Python 版 get_config_dir 一致)。
pub fn config_dir() -> PathBuf {
    if cfg!(windows) {
        let base = std::env::var("APPDATA").unwrap_or_else(|_| {
            std::env::var("USERPROFILE")
                .map(|h| format!("{h}\\AppData\\Roaming"))
                .unwrap_or_else(|_| ".".into())
        });
        return PathBuf::from(base).join("tokenmon");
    }
    let home = std::env::var("HOME").unwrap_or_else(|_| ".".into());
    let home_default = PathBuf::from(&home).join(".config").join("tokenmon");
    let xdg_base = std::env::var("XDG_CONFIG_HOME")
        .unwrap_or_else(|_| format!("{home}/.config"));
    let xdg = PathBuf::from(xdg_base).join("tokenmon");
    // Flatpak 沙箱(VSCode 等)会把 XDG_CONFIG_HOME 重定向到 ~/.var/app/...,
    // 但用户编辑的总是宿主 home 下的配置 —— 已存在则优先用它
    if xdg != home_default && home_default.join("config.toml").exists() {
        return home_default;
    }
    xdg
}

pub fn config_path() -> PathBuf {
    config_dir().join("config.toml")
}

/// 解析并校验配置。错误信息面向用户, 与 Python 版一致。
pub fn load_config(path: &Path) -> Result<AppConfig, String> {
    let text = std::fs::read_to_string(path)
        .map_err(|e| format!("读取配置失败: {e}"))?;
    let mut cfg: AppConfig =
        toml::from_str(&text).map_err(|e| format!("配置解析失败: {e}"))?;

    let gw = &mut cfg.gateway;
    let gtype = gw.gtype.trim().to_lowercase();
    if !matches!(gtype.as_str(), "litellm" | "openrouter" | "custom" | "deepseek") {
        return Err(format!(
            "未知 gateway type: {gtype:?} (可选: litellm/openrouter/custom/deepseek)"
        ));
    }
    gw.gtype = gtype;

    if !(gw.refresh_seconds >= 1.0) {
        return Err("[gateway] refresh_seconds 不能小于 1 秒(否则轮询会空转)".into());
    }
    if !(1..=50).contains(&gw.logs_limit) {
        return Err("[gateway] logs_limit 必须在 1..50 之间".into());
    }
    if !(1..=1000).contains(&gw.logs_page_size) {
        return Err("[gateway] logs_page_size 必须在 1..1000 之间".into());
    }
    if !(gw.logs_refresh_seconds >= 10.0) {
        return Err("[gateway] logs_refresh_seconds 不能小于 10 秒".into());
    }

    if gw.gtype == "custom" && !gw.fields.is_empty() {
        let known: Vec<&str> = DEFAULT_FIELD_MAP.iter().map(|(k, _)| *k).collect();
        let unknown: Vec<&str> = gw
            .fields
            .keys()
            .filter(|k| !known.contains(&k.as_str()))
            .map(|k| k.as_str())
            .collect();
        if !unknown.is_empty() {
            return Err(format!(
                "[gateway.fields] 未知字段名: {} (可选: {})",
                unknown.join(", "),
                known.join(", ")
            ));
        }
    }
    Ok(cfg)
}

/// 展开后的完整字段映射(默认 + 用户覆盖 + 旧式路径兼容)。
pub fn effective_fields(gw: &GatewayConfig) -> BTreeMap<String, String> {
    let mut fields = default_fields();
    for (k, v) in &gw.fields {
        fields.insert(k.clone(), v.clone());
    }
    if gw.tokens_path.is_some() && gw.fields.is_empty() {
        if let Some(p) = &gw.tokens_path {
            fields.insert("total".into(), p.clone());
        }
    }
    if gw.cost_path.is_some() && gw.fields.is_empty() {
        if let Some(p) = &gw.cost_path {
            fields.insert("cost".into(), p.clone());
        }
    }
    fields
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_config_parses() {
        let dir = std::env::temp_dir().join("tokenmon-test");
        std::fs::create_dir_all(&dir).unwrap();
        let p = dir.join("config.toml");
        std::fs::write(&p, DEFAULT_CONFIG).unwrap();
        let cfg = load_config(&p).unwrap();
        assert_eq!(cfg.gateway.gtype, "custom");
        assert_eq!(cfg.gateway.refresh_seconds, 5.0);
        assert_eq!(cfg.window.always_on_top, true);
        assert!(cfg.gateway.fields.contains_key("total"));
    }

    #[test]
    fn rejects_bad_refresh() {
        let cfg: AppConfig = toml::from_str(
            "[gateway]\ntype = \"custom\"\nrefresh_seconds = 0\n",
        )
        .unwrap();
        assert!(cfg.gateway.refresh_seconds < 1.0);
        // 通过 load_config 完整校验
        let dir = std::env::temp_dir().join("tokenmon-test2");
        std::fs::create_dir_all(&dir).unwrap();
        let p = dir.join("c.toml");
        std::fs::write(
            &p,
            "[gateway]\ntype = \"custom\"\nrefresh_seconds = 0\n",
        )
        .unwrap();
        assert!(load_config(&p).is_err());
    }

    #[test]
    fn rejects_unknown_type() {
        let dir = std::env::temp_dir().join("tokenmon-test3");
        std::fs::create_dir_all(&dir).unwrap();
        let p = dir.join("c.toml");
        std::fs::write(&p, "[gateway]\ntype = \"foo\"\n").unwrap();
        let err = load_config(&p).unwrap_err();
        assert!(err.contains("未知 gateway type"));
    }

    #[test]
    fn rejects_unknown_field() {
        let dir = std::env::temp_dir().join("tokenmon-test4");
        std::fs::create_dir_all(&dir).unwrap();
        let p = dir.join("c.toml");
        std::fs::write(
            &p,
            "[gateway]\ntype = \"custom\"\n[gateway.fields]\nfoo = \"x\"\n",
        )
        .unwrap();
        assert!(load_config(&p).is_err());
    }

    #[test]
    fn legacy_paths_map_to_total_cost() {
        let dir = std::env::temp_dir().join("tokenmon-test5");
        std::fs::create_dir_all(&dir).unwrap();
        let p = dir.join("c.toml");
        std::fs::write(
            &p,
            "[gateway]\ntype = \"custom\"\ntokens_path = \"data.total\"\ncost_path = \"data.cost\"\n",
        )
        .unwrap();
        let cfg = load_config(&p).unwrap();
        let f = effective_fields(&cfg.gateway);
        assert_eq!(f.get("total").unwrap(), "data.total");
        assert_eq!(f.get("cost").unwrap(), "data.cost");
    }

    #[test]
    fn effective_fields_merge() {
        let mut gw = GatewayConfig::default();
        gw.fields.insert("total".into(), "data.totalTokens".into());
        let f = effective_fields(&gw);
        assert_eq!(f.get("total").unwrap(), "data.totalTokens");
        assert_eq!(f.get("prompt").unwrap(), "promptTokens"); // 默认保留
    }
}
