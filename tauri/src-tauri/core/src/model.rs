use serde::Serialize;

/// 一次轮询的用量快照。各字段可为 None(网关不提供该指标)。
/// 内部字段名(小写下划线) <-> JSON 字段由 [gateway.fields] 映射。
#[derive(Debug, Default, Clone, Serialize)]
pub struct Usage {
    pub prompt: Option<f64>,
    pub completion: Option<f64>,
    pub reasoning: Option<f64>,
    pub cache_hit: Option<f64>,
    pub cache_miss: Option<f64>,
    pub session_cache_hit: Option<f64>,
    pub session_cache_miss: Option<f64>,
    pub total: Option<f64>,
    pub cost: Option<f64>,
    pub balance: Option<f64>,
    pub currency: Option<String>,
    #[serde(skip)]
    pub raw: serde_json::Value,
}

impl Usage {
    pub fn mock() -> Self {
        Usage {
            prompt: Some(2105876.0),
            completion: Some(109278.0),
            reasoning: Some(79503.0),
            cache_hit: Some(1988736.0),
            cache_miss: Some(117140.0),
            session_cache_hit: Some(1988736.0),
            session_cache_miss: Some(117140.0),
            total: Some(2215154.0),
            cost: Some(0.3755),
            balance: None,
            currency: Some("¥".into()),
            raw: serde_json::json!({"mock": true}),
        }
    }
}

/// 一次对话的聚合快照(prompt + token 总量)。
#[derive(Debug, Clone, Serialize)]
pub struct Conversation {
    pub prompt: String,
    pub tokens: Option<f64>,
    pub spend: Option<f64>,
    pub requests: u64,
    pub last_time: Option<String>,
    pub source_id: String,
}

impl Conversation {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        prompt: &str,
        tokens: Option<f64>,
        spend: Option<f64>,
        requests: u64,
        last_time: Option<String>,
        source_id: String,
    ) -> Self {
        Conversation {
            prompt: prompt.to_string(),
            tokens,
            spend,
            requests,
            last_time,
            source_id,
        }
    }
}
