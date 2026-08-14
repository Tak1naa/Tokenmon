//! 网关抓取: 用量 + 最近对话。逻辑与 Python 版 tokenmon_core.py 一一对应。

use std::collections::{BTreeMap, HashMap};
use std::sync::OnceLock;
use std::time::{Duration, Instant};

use serde_json::Value;

use crate::config::{effective_fields, GatewayConfig, USER_AGENT};
use crate::model::{Conversation, Usage};

#[derive(Debug, Clone)]
pub struct FetchError {
    pub msg: String,
    pub http_code: Option<u16>,
}

impl FetchError {
    pub fn new(msg: impl Into<String>) -> Self {
        FetchError { msg: msg.into(), http_code: None }
    }
}

impl std::fmt::Display for FetchError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.msg)
    }
}

impl std::error::Error for FetchError {}

fn client() -> &'static reqwest::blocking::Client {
    static CLIENT: OnceLock<reqwest::blocking::Client> = OnceLock::new();
    CLIENT.get_or_init(|| {
        reqwest::blocking::Client::builder()
            .timeout(Duration::from_secs(10))
            .build()
            .expect("build http client")
    })
}

fn get_json(url: &str, headers: &[(String, String)]) -> Result<Value, FetchError> {
    let mut req = client().get(url).header("User-Agent", USER_AGENT);
    for (k, v) in headers {
        req = req.header(k, v);
    }
    let resp = req.send().map_err(|e| {
        FetchError::new(format!("网络错误 {e}: {url}"))
    })?;
    let status = resp.status();
    if !status.is_success() {
        return Err(FetchError {
            msg: format!("HTTP {} {}: {url}", status.as_u16(), status.canonical_reason().unwrap_or("")),
            http_code: Some(status.as_u16()),
        });
    }
    let text = resp.text().map_err(|e| {
        FetchError::new(format!("读取响应失败 {e}: {url}"))
    })?;
    serde_json::from_str(&text)
        .map_err(|_| FetchError::new(format!("响应不是合法 JSON: {url}")))
}

// --------------------------------------------------------------------------
// 数值工具(与 Python _as_number / get_path / _sum_field 一致)
// --------------------------------------------------------------------------

pub fn as_number(v: &Value) -> Option<f64> {
    match v {
        Value::Null => None,
        Value::Bool(_) => None,
        Value::Number(n) => n.as_f64(),
        Value::String(s) => {
            let cleaned: String = s.chars().filter(|c| *c != ',').collect();
            cleaned.trim().parse::<f64>().ok()
        }
        _ => None,
    }
}

pub fn get_path<'a>(data: &'a Value, dotted: &str) -> Option<&'a Value> {
    let mut cur = data;
    for part in dotted.split('.') {
        match cur.get(part) {
            Some(v) => cur = v,
            None => return None,
        }
    }
    Some(cur)
}

fn sum_field(items: &[Value], key: &str) -> Option<f64> {
    let mut total = 0.0;
    let mut found = false;
    for it in items {
        if let Some(v) = as_number(it.get(key)?) {
            total += v;
            found = true;
        }
    }
    if found { Some(total) } else { None }
}

fn sum_num(rows: &[Value], keys: &[&str]) -> Option<f64> {
    let mut total = 0.0;
    let mut found = false;
    for r in rows {
        for k in keys {
            if let Some(v) = r.get(*k).and_then(as_number) {
                total += v;
                found = true;
                break;
            }
        }
    }
    if found { Some(total) } else { None }
}

// --------------------------------------------------------------------------
// 用量抓取
// --------------------------------------------------------------------------

fn usage_from_litellm(data: &Value) -> Usage {
    let tokens = data.get("total_tokens").and_then(as_number);
    let cost = data.get("total_cost").and_then(as_number);
    let tokens = tokens.or_else(|| {
        data.get("api_keys")
            .and_then(|v| v.as_object())
            .map(|m| sum_field(&m.values().cloned().collect::<Vec<_>>(), "total_tokens"))
            .flatten()
    });
    let tokens = tokens.or_else(|| {
        data.get("data")
            .and_then(|v| v.as_array())
            .map(|a| sum_field(a, "total_tokens"))
            .flatten()
    });
    let cost = cost.or_else(|| {
        data.get("api_keys")
            .and_then(|v| v.as_object())
            .map(|m| sum_field(&m.values().cloned().collect::<Vec<_>>(), "total_cost"))
            .flatten()
    });
    let cost = cost.or_else(|| {
        data.get("data")
            .and_then(|v| v.as_array())
            .map(|a| sum_field(a, "total_cost"))
            .flatten()
    });
    Usage {
        total: tokens,
        cost,
        currency: Some("$".into()),
        raw: data.clone(),
        ..Default::default()
    }
}

fn usage_from_openrouter(data: &Value) -> Usage {
    let usage = data
        .get("data")
        .and_then(|v| v.get("usage"))
        .cloned()
        .unwrap_or(Value::Null);
    let credits = usage.get("total_usage").and_then(as_number);
    let cost = credits.map(|c| c / 1000.0);
    Usage {
        cost,
        currency: Some("$".into()),
        raw: data.clone(),
        ..Default::default()
    }
}

fn usage_from_deepseek(data: &Value) -> Result<Usage, FetchError> {
    if data.get("is_available") != Some(&Value::Bool(true)) {
        return Err(FetchError::new("DeepSeek 余额查询不可用(is_available=false)"));
    }
    let infos = data.get("balance_infos").and_then(|v| v.as_array()).cloned().unwrap_or_default();
    let info = infos.first().cloned().unwrap_or(Value::Null);
    let currency = info
        .get("currency")
        .and_then(|v| v.as_str())
        .unwrap_or("CNY")
        .to_string();
    let sym = match currency.to_uppercase().as_str() {
        "CNY" => "¥".to_string(),
        "USD" => "$".to_string(),
        _ => currency,
    };
    let remaining = info.get("total_remaining").and_then(as_number);
    let balance = remaining.or_else(|| info.get("total_balance").and_then(as_number));
    let mut cost = info.get("total_used").and_then(as_number);
    if cost.is_none() && balance.is_some() {
        let granted = info.get("granted_balance").and_then(as_number).unwrap_or(0.0);
        let topped = info.get("topped_up_balance").and_then(as_number).unwrap_or(0.0);
        let used = granted + topped - balance.unwrap_or(0.0);
        cost = if used >= 0.0 { Some(used) } else { None };
    }
    Ok(Usage {
        balance,
        cost,
        currency: Some(sym),
        raw: data.clone(),
        ..Default::default()
    })
}

pub fn usage_from_custom(data: &Value, fields: &BTreeMap<String, String>) -> Usage {
    let mut u = Usage { raw: data.clone(), ..Default::default() };
    for (fname, path) in fields {
        if fname == "currency" {
            if let Some(v) = get_path(data, path).and_then(|v| v.as_str()) {
                u.currency = Some(v.to_string());
            }
        } else {
            let v = get_path(data, path).and_then(as_number);
            match fname.as_str() {
                "prompt" => u.prompt = v,
                "completion" => u.completion = v,
                "reasoning" => u.reasoning = v,
                "cache_hit" => u.cache_hit = v,
                "cache_miss" => u.cache_miss = v,
                "session_cache_hit" => u.session_cache_hit = v,
                "session_cache_miss" => u.session_cache_miss = v,
                "total" => u.total = v,
                "cost" => u.cost = v,
                _ => {}
            }
        }
    }
    u
}

fn base_key(gw: &GatewayConfig) -> (String, String) {
    (
        gw.base_url.trim_end_matches('/').to_string(),
        gw.api_key.trim().to_string(),
    )
}

/// 按网关类型抓取用量。异常向上抛, 由调用方统一处理。
pub fn fetch_usage(gw: &GatewayConfig) -> Result<Usage, FetchError> {
    let (base, key) = base_key(gw);

    if base.starts_with("mock://") {
        return Ok(Usage::mock());
    }

    let mut headers: Vec<(String, String)> = Vec::new();

    match gw.gtype.as_str() {
        "litellm" => {
            if base.is_empty() {
                return Err(FetchError::new("litellm 网关需要配置 base_url"));
            }
            if !key.is_empty() {
                headers.push(("x-api-key".into(), key));
            }
            let data = get_json(&format!("{base}/usage"), &headers)?;
            Ok(usage_from_litellm(&data))
        }
        "openrouter" => {
            if key.is_empty() {
                return Err(FetchError::new("openrouter 网关需要配置 api_key"));
            }
            headers.push(("Authorization".into(), format!("Bearer {key}")));
            let data = get_json("https://openrouter.ai/api/v1/auth/key", &headers)?;
            Ok(usage_from_openrouter(&data))
        }
        "deepseek" => {
            if key.is_empty() {
                return Err(FetchError::new("deepseek 网关需要配置 api_key"));
            }
            headers.push(("Authorization".into(), format!("Bearer {key}")));
            let base = if base.is_empty() { "https://api.deepseek.com".to_string() } else { base };
            let data = get_json(&format!("{base}/user/balance"), &headers)?;
            usage_from_deepseek(&data)
        }
        _ => {
            // custom —— 按 [gateway.fields] 映射取数
            if base.is_empty() {
                return Err(FetchError::new("custom 网关需要配置 base_url"));
            }
            if !key.is_empty() {
                headers.push(("Authorization".into(), format!("Bearer {key}")));
            }
            let data = get_json(&base, &headers)?;
            let fields = effective_fields(gw);
            Ok(usage_from_custom(&data, &fields))
        }
    }
}

// --------------------------------------------------------------------------
// 最近对话
// --------------------------------------------------------------------------

const MCP_CALL_TYPES: &[&str] = &["call_mcp_tool", "list_mcp_tools", "mcp"];

fn rows_from_envelope(data: &Value) -> Vec<Value> {
    if let Some(obj) = data.as_object() {
        if let Some(rows) = obj.get("data").and_then(|v| v.as_array()) {
            return rows.clone();
        }
        return vec![];
    }
    if let Some(arr) = data.as_array() {
        return arr.clone();
    }
    vec![]
}

fn truncate_prompt(text: &str, maxlen: usize) -> String {
    let joined: String = text.split_whitespace().collect::<Vec<_>>().join(" ");
    if joined.chars().count() <= maxlen {
        joined
    } else {
        let truncated: String = joined.chars().take(maxlen - 1).collect();
        format!("{truncated}…")
    }
}

fn first_user_message(messages: &Value) -> Option<String> {
    let parsed: Value = match messages {
        Value::Null => return None,
        Value::String(s) => {
            let s = s.trim();
            if s.is_empty() || s == "{}" {
                return None;
            }
            if !s.starts_with('[') && !s.starts_with('{') {
                return Some(s.to_string()); // 非 JSON 裸文本
            }
            match serde_json::from_str(s) {
                Ok(v) => v,
                Err(_) => return None,
            }
        }
        other => other.clone(),
    };
    let list: Vec<Value> = match parsed {
        Value::Array(a) => a,
        Value::Object(_) => vec![parsed],
        _ => return None,
    };
    for m in list {
        let role = m.get("role").and_then(|v| v.as_str()).unwrap_or("");
        if !role.eq_ignore_ascii_case("user") {
            continue;
        }
        if let Some(c) = m.get("content") {
            if let Some(s) = c.as_str() {
                let s = s.trim();
                if !s.is_empty() {
                    return Some(s.to_string());
                }
            }
            if let Some(parts) = c.as_array() {
                for part in parts {
                    if let Some(t) = part.get("text").and_then(|v| v.as_str()) {
                        if !t.trim().is_empty() {
                            return Some(t.trim().to_string());
                        }
                    }
                }
            }
        }
    }
    None
}

fn extract_user_prompt(rows: &[Value]) -> String {
    for allow_mcp in [false, true] {
        for r in rows {
            if !allow_mcp {
                let ct = r.get("call_type").and_then(|v| v.as_str()).unwrap_or("");
                if MCP_CALL_TYPES.contains(&ct) {
                    continue;
                }
            }
            if let Some(msg) = r.get("messages").and_then(first_user_message) {
                return truncate_prompt(&msg, 120);
            }
        }
    }
    "（无文本）".to_string()
}

pub fn parse_litellm_logs(rows: &[Value], limit: usize) -> Vec<Conversation> {
    let mut groups: HashMap<String, Vec<Value>> = HashMap::new();
    for row in rows {
        if !row.is_object() {
            continue;
        }
        let sid = row.get("session_id").and_then(|v| v.as_str()).unwrap_or("");
        let rid = row.get("request_id").and_then(|v| v.as_str()).unwrap_or("");
        let key = if !sid.is_empty() {
            sid.to_string()
        } else if !rid.is_empty() {
            rid.to_string()
        } else {
            format!("__single_{}", groups.len())
        };
        groups.entry(key).or_default().push(row.clone());
    }
    let mut convs: Vec<Conversation> = Vec::new();
    for (key, mut group_rows) in groups {
        group_rows.sort_by_key(|r| {
            r.get("startTime").and_then(|v| v.as_str()).unwrap_or("").to_string()
        });
        let mut tokens = sum_num(&group_rows, &["total_tokens"]);
        if tokens.is_none() {
            let p = sum_num(&group_rows, &["prompt_tokens"]);
            let c = sum_num(&group_rows, &["completion_tokens"]);
            tokens = match (p, c) {
                (Some(p), Some(c)) => Some(p + c),
                (Some(p), None) => Some(p),
                (None, Some(c)) => Some(c),
                (None, None) => None,
            };
        }
        let last_time = group_rows
            .iter()
            .filter_map(|r| r.get("startTime").and_then(|v| v.as_str()))
            .max()
            .map(|s| s.to_string());
        convs.push(Conversation::new(
            &extract_user_prompt(&group_rows),
            tokens,
            sum_num(&group_rows, &["spend"]),
            group_rows.len() as u64,
            last_time,
            key,
        ));
    }
    convs.sort_by(|a, b| b.last_time.cmp(&a.last_time));
    convs.truncate(limit);
    convs
}

fn fetch_litellm_conversations(
    base: &str,
    headers: &[(String, String)],
    limit: usize,
    page_size: usize,
) -> Result<Vec<Conversation>, FetchError> {
    let page_url = |ep: &str, page: usize| {
        format!("{base}{ep}?page={page}&page_size={page_size}&sort_by=startTime&sort_order=desc")
    };
    // v2 优先, 404/405 降级 /spend/logs/ui; 两者都是 {data, total_pages} 信封带分页
    for ep in ["/spend/logs/v2", "/spend/logs/ui"] {
        let first = match get_json(&page_url(ep, 1), headers) {
            Ok(v) => v,
            Err(e) => {
                if matches!(e.http_code, Some(404) | Some(405)) {
                    continue;
                }
                return Err(e);
            }
        };
        let mut rows = rows_from_envelope(&first);
        let total_pages: i64 = first
            .get("total_pages")
            .and_then(as_number)
            .map(|v| v as i64)
            .unwrap_or(1);
        let mut page = 1usize;
        let mut convs = parse_litellm_logs(&rows, limit);
        let deadline = Instant::now() + Duration::from_secs(20);
        while convs.len() < limit
            && page < total_pages.min(3) as usize
            && Instant::now() < deadline
        {
            page += 1;
            match get_json(&page_url(ep, page), headers) {
                Ok(data) => {
                    rows.extend(rows_from_envelope(&data));
                    convs = parse_litellm_logs(&rows, limit);
                }
                Err(_) => break,
            }
        }
        return Ok(convs);
    }
    // 旧版 /spend/logs: 无分页, 返回裸数组
    let data = get_json(&format!("{base}/spend/logs"), headers)?;
    Ok(parse_litellm_logs(&rows_from_envelope(&data), limit))
}

pub fn parse_custom_conversations(data: &Value, limit: usize) -> Vec<Conversation> {
    let mut data = data.clone();
    if data.is_object() {
        let mut found = false;
        for k in ["conversations", "logs", "data"] {
            if let Some(arr) = data.get(k).and_then(|v| v.as_array()) {
                data = Value::Array(arr.clone());
                found = true;
                break;
            }
        }
        if !found {
            return vec![];
        }
    }
    let items = match data.as_array() {
        Some(a) => a,
        None => return vec![],
    };
    let mut convs: Vec<Conversation> = Vec::new();
    for item in items {
        if !item.is_object() {
            continue;
        }
        let prompt = item
            .get("prompt")
            .or_else(|| item.get("question"))
            .or_else(|| item.get("text"))
            .and_then(|v| v.as_str())
            .map(|s| truncate_prompt(s, 120))
            .unwrap_or_else(|| "（无文本）".to_string());
        let tokens = ["tokens", "total_tokens", "totalTokens"]
            .iter()
            .find_map(|k| item.get(*k).and_then(as_number));
        let spend = item.get("spend").and_then(as_number)
            .or_else(|| item.get("cost").and_then(as_number));
        let last_time = item
            .get("time")
            .or_else(|| item.get("startTime"))
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());
        let source_id = item
            .get("id")
            .or_else(|| item.get("session_id"))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        convs.push(Conversation::new(&prompt, tokens, spend, 1, last_time, source_id));
    }
    // 约定网关按时间升序返回; 反转后按 last_time 降序
    convs.reverse();
    convs.sort_by(|a, b| b.last_time.cmp(&a.last_time));
    convs.truncate(limit);
    convs
}

fn mock_conversations() -> Vec<Conversation> {
    let samples: &[(&str, f64, &str)] = &[
        ("帮我优化 tokenmon, 做成精灵球样式, 并适配 Windows", 123456.0, "2026-08-13T11:30:00"),
        ("写一个 litellm 网关的用量聚合脚本", 88912.0, "2026-08-13T10:12:00"),
        ("解释一下 OpenRouter 的 credit 计费规则", 45210.0, "2026-08-12T21:47:00"),
        ("重构 FastAPI 项目, 拆分路由模块", 210330.0, "2026-08-12T16:05:00"),
        ("用 Rust 写一个 JSON 解析器", 78020.0, "2026-08-12T09:21:00"),
        ("帮我调试 postgres 慢查询", 56784.0, "2026-08-11T19:40:00"),
        ("翻译一段技术文档", 8120.0, "2026-08-11T15:02:00"),
        ("写单元测试覆盖边界情况", 43150.0, "2026-08-11T10:55:00"),
        ("给 NAS 设计一个备份策略", 15340.0, "2026-08-10T22:18:00"),
        ("解释 Python GIL 与 asyncio", 28760.0, "2026-08-10T14:33:00"),
    ];
    samples
        .iter()
        .enumerate()
        .map(|(i, (p, t, ts))| {
            Conversation::new(
                p,
                Some(*t),
                Some((t * 0.000002 * 10000.0).round() / 10000.0),
                1,
                Some(ts.to_string()),
                format!("mock-{i}"),
            )
        })
        .collect()
}

/// 抓取最近对话列表。异常向上抛, 由调用方降级为"无数据"。
pub fn fetch_conversations(gw: &GatewayConfig) -> Result<Vec<Conversation>, FetchError> {
    let (base, key) = base_key(gw);
    let limit = gw.logs_limit as usize;
    let page_size = gw.logs_page_size as usize;

    if base.starts_with("mock://") || gw.logs_url.starts_with("mock://") {
        return Ok(mock_conversations());
    }

    let mut headers: Vec<(String, String)> = Vec::new();
    match gw.gtype.as_str() {
        "litellm" => {
            if base.is_empty() {
                return Err(FetchError::new("litellm 网关需要配置 base_url"));
            }
            if !key.is_empty() {
                headers.push(("x-api-key".into(), key));
            }
            fetch_litellm_conversations(&base, &headers, limit, page_size)
        }
        "custom" => {
            let url = gw.logs_url.trim();
            if url.is_empty() {
                return Ok(vec![]);
            }
            if !key.is_empty() {
                headers.push(("Authorization".into(), format!("Bearer {key}")));
            }
            let data = get_json(url, &headers)?;
            Ok(parse_custom_conversations(&data, limit))
        }
        _ => Ok(vec![]),
    }
}

// --------------------------------------------------------------------------
// 测试
// --------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::DEFAULT_FIELD_MAP;
    use serde_json::json;

    fn fields() -> BTreeMap<String, String> {
        DEFAULT_FIELD_MAP
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect()
    }

    #[test]
    fn as_number_variants() {
        assert_eq!(as_number(&json!(123)), Some(123.0));
        assert_eq!(as_number(&json!(1.5)), Some(1.5));
        assert_eq!(as_number(&json!("1,234")), Some(1234.0));
        assert_eq!(as_number(&json!(null)), None);
        assert_eq!(as_number(&json!(true)), None);
        assert_eq!(as_number(&json!("abc")), None);
    }

    #[test]
    fn get_path_dotted() {
        let data = json!({"data": {"total_tokens": 42}});
        assert_eq!(get_path(&data, "data.total_tokens"), Some(&json!(42)));
        assert_eq!(get_path(&data, "data.missing"), None);
        assert_eq!(get_path(&data, "nope.x"), None);
    }

    #[test]
    fn custom_usage_mapping() {
        let data = json!({
            "promptTokens": 100, "completionTokens": 50, "totalTokens": 150,
            "cost": 0.12, "currency": "¥",
            "nested": {"cacheHitTokens": 80},
        });
        let mut f = fields();
        f.insert("cache_hit".into(), "nested.cacheHitTokens".into());
        let u = usage_from_custom(&data, &f);
        assert_eq!(u.prompt, Some(100.0));
        assert_eq!(u.completion, Some(50.0));
        assert_eq!(u.total, Some(150.0));
        assert_eq!(u.cost, Some(0.12));
        assert_eq!(u.cache_hit, Some(80.0));
        assert_eq!(u.currency.as_deref(), Some("¥"));
        assert_eq!(u.reasoning, None);
    }

    #[test]
    fn litellm_usage_variants() {
        // 顶层聚合
        let u = usage_from_litellm(&json!({"total_tokens": 1000, "total_cost": 1.5}));
        assert_eq!(u.total, Some(1000.0));
        assert_eq!(u.cost, Some(1.5));
        // api_keys dict
        let u = usage_from_litellm(&json!({
            "api_keys": {"a": {"total_tokens": 10}, "b": {"total_tokens": 20}}
        }));
        assert_eq!(u.total, Some(30.0));
        // data list
        let u = usage_from_litellm(&json!({
            "data": [{"total_tokens": 5}, {"total_tokens": 7}]
        }));
        assert_eq!(u.total, Some(12.0));
        // 全空
        let u = usage_from_litellm(&json!({}));
        assert_eq!(u.total, None);
    }

    #[test]
    fn openrouter_credit_math() {
        let u = usage_from_openrouter(&json!({"data": {"usage": {"total_usage": 2500}}}));
        assert_eq!(u.cost, Some(2.5));
        assert_eq!(u.currency.as_deref(), Some("$"));
    }

    #[test]
    fn deepseek_balance() {
        let u = usage_from_deepseek(&json!({
            "is_available": true,
            "balance_infos": [{
                "currency": "CNY", "total_balance": 100.0,
                "granted_balance": 50.0, "topped_up_balance": 60.0
            }]
        }))
        .unwrap();
        assert_eq!(u.balance, Some(100.0));
        assert_eq!(u.cost, Some(10.0)); // 50 + 60 - 100
        assert_eq!(u.currency.as_deref(), Some("¥"));

        let err = usage_from_deepseek(&json!({"is_available": false}));
        assert!(err.is_err());
    }

    #[test]
    fn litellm_logs_grouping() {
        let rows = vec![
            json!({"session_id": "s1", "request_id": "r1", "total_tokens": 10,
                   "messages": [{"role": "user", "content": "第一条"}],
                   "startTime": "2026-08-13T10:00:00", "call_type": ""}),
            json!({"session_id": "s1", "request_id": "r2", "total_tokens": 20,
                   "messages": [{"role": "assistant", "content": "回复"}],
                   "startTime": "2026-08-13T10:01:00", "call_type": ""}),
            json!({"session_id": "s2", "request_id": "r3", "total_tokens": 5,
                   "messages": [{"role": "user", "content": "另一条"}],
                   "startTime": "2026-08-13T11:00:00", "call_type": ""}),
        ];
        let convs = parse_litellm_logs(&rows, 10);
        assert_eq!(convs.len(), 2);
        let s1 = convs.iter().find(|c| c.source_id == "s1").unwrap();
        assert_eq!(s1.tokens, Some(30.0));
        assert_eq!(s1.requests, 2);
        assert_eq!(s1.prompt, "第一条");
        assert!(convs[0].last_time >= convs[1].last_time);
    }

    #[test]
    fn litellm_logs_skip_mcp() {
        let rows = vec![
            json!({"session_id": "s1", "total_tokens": 1,
                   "messages": [{"role": "user", "content": "MCP 工具调用"}],
                   "call_type": "call_mcp_tool", "startTime": "2026-08-13T10:00:00"}),
            json!({"session_id": "s1", "total_tokens": 1,
                   "messages": [{"role": "user", "content": "真正的提问"}],
                   "call_type": "", "startTime": "2026-08-13T10:01:00"}),
        ];
        let convs = parse_litellm_logs(&rows, 10);
        assert_eq!(convs[0].prompt, "真正的提问");
    }

    #[test]
    fn litellm_logs_fallback_to_prompt_plus_completion() {
        let rows = vec![
            json!({"session_id": "s1", "prompt_tokens": 7, "completion_tokens": 3,
                   "messages": [{"role": "user", "content": "hi"}],
                   "startTime": "2026-08-13T10:00:00", "call_type": ""}),
        ];
        let convs = parse_litellm_logs(&rows, 10);
        assert_eq!(convs[0].tokens, Some(10.0));
    }

    #[test]
    fn custom_conversations_envelope() {
        let data = json!({
            "data": [
                {"prompt": "问题A", "tokens": 100, "time": "2026-08-13T10:00:00"},
                {"prompt": "问题B", "total_tokens": 200, "time": "2026-08-13T11:00:00"},
            ]
        });
        let convs = parse_custom_conversations(&data, 10);
        assert_eq!(convs.len(), 2);
        assert_eq!(convs[0].prompt, "问题B"); // 最新在前
        assert_eq!(convs[0].tokens, Some(200.0));
        assert_eq!(convs[1].tokens, Some(100.0));
    }

    #[test]
    fn custom_conversations_limit() {
        let items: Vec<Value> = (0..5)
            .map(|i| json!({"prompt": format!("q{i}"), "tokens": i}))
            .collect();
        let convs = parse_custom_conversations(&json!(items), 2);
        assert_eq!(convs.len(), 2);
    }

    #[test]
    fn first_user_message_variants() {
        // 字符串 JSON
        assert_eq!(
            first_user_message(&Value::String(
                r#"[{"role":"user","content":"你好"}]"#.to_string()
            )),
            Some("你好".to_string())
        );
        // 多模态块
        assert_eq!(
            first_user_message(&json!([{"role": "user", "content": [
                {"type": "image"}, {"type": "text", "text": "看图说话"}
            ]}])),
            Some("看图说话".to_string())
        );
        // 裸文本
        assert_eq!(
            first_user_message(&Value::String("裸文本".to_string())),
            Some("裸文本".to_string())
        );
        // 无 user 消息
        assert_eq!(
            first_user_message(&json!([{"role": "assistant", "content": "x"}])),
            None
        );
        assert_eq!(first_user_message(&Value::Null), None);
    }

    #[test]
    fn truncate_prompt_joins_whitespace() {
        assert_eq!(truncate_prompt("  a   b  ", 10), "a b");
        let long = "x".repeat(150);
        let t = truncate_prompt(&long, 120);
        assert_eq!(t.chars().count(), 120);
        assert!(t.ends_with('…'));
    }

    #[test]
    fn mock_usage_total() {
        let u = Usage::mock();
        assert_eq!(u.total, Some(2215154.0));
        assert_eq!(u.cost, Some(0.3755));
    }

    #[test]
    fn mock_conversations_shape() {
        let convs = mock_conversations();
        assert_eq!(convs.len(), 10);
        assert!(convs[0].tokens.is_some());
    }
}
