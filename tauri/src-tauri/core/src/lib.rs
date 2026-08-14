//! TokenMon 数据层 —— 配置加载 / 网关抓取 / 解析聚合 / 格式化。
//!
//! 纯 Rust 实现, 不依赖任何 GUI/tauri, 可独立单测:
//!     cargo test -p tokenmon-core
//!
//! 逻辑与 Python 版 tokenmon_core.py 一一对应, 保持行为一致。

pub mod config;
pub mod fetch;
pub mod fmt;
pub mod model;

pub use config::{config_path, load_config, AppConfig};
pub use fetch::{fetch_conversations, fetch_usage};
pub use model::{Conversation, Usage};
