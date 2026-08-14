//! 格式化(纯函数, CLI 与 GUI 共用)。

pub fn fmt_tokens(n: Option<f64>) -> String {
    match n {
        Some(v) => format_int(v),
        None => "—".into(),
    }
}

fn format_int(n: f64) -> String {
    let r = n.round() as i64;
    let s = r.to_string();
    let mut out = String::new();
    let bytes = s.as_bytes();
    for (i, b) in bytes.iter().enumerate() {
        if i > 0 && (bytes.len() - i) % 3 == 0 {
            out.push(',');
        }
        out.push(*b as char);
    }
    out
}

pub fn fmt_money(n: Option<f64>, currency: Option<&str>) -> String {
    match n {
        Some(v) => {
            let sym = currency.filter(|s| !s.is_empty()).unwrap_or("$");
            format!("{sym}{v:.4}")
        }
        None => "—".into(),
    }
}

/// 悬浮球用紧凑格式: 2.2M / 123k / 1,234
pub fn fmt_short(n: Option<f64>) -> String {
    match n {
        Some(v) => {
            if v >= 1_000_000.0 {
                format!("{:.1}M", v / 1_000_000.0)
            } else if v >= 1_000.0 {
                format!("{:.1}k", v / 1_000.0)
            } else {
                format_int(v)
            }
        }
        None => "—".into(),
    }
}

/// 悬浮球用紧凑金额: $0.38 / ¥1.2k
pub fn fmt_money_short(n: Option<f64>, currency: Option<&str>) -> String {
    match n {
        Some(v) => {
            let sym = currency.filter(|s| !s.is_empty()).unwrap_or("$");
            if v >= 1_000.0 {
                format!("{sym}{:.1}k", v / 1_000.0)
            } else {
                format!("{sym}{v:.2}")
            }
        }
        None => "—".into(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tokens_thousands() {
        assert_eq!(fmt_tokens(Some(2215154.0)), "2,215,154");
        assert_eq!(fmt_tokens(Some(123.0)), "123");
        assert_eq!(fmt_tokens(None), "—");
    }

    #[test]
    fn money_fixed() {
        assert_eq!(fmt_money(Some(0.3755), Some("¥")), "¥0.3755");
        assert_eq!(fmt_money(Some(1.5), None), "$1.5000");
        assert_eq!(fmt_money(None, Some("$")), "—");
    }

    #[test]
    fn short_format() {
        assert_eq!(fmt_short(Some(2_215_154.0)), "2.2M");
        assert_eq!(fmt_short(Some(123_456.0)), "123.5k");
        assert_eq!(fmt_short(Some(1234.0)), "1.2k");
        assert_eq!(fmt_short(Some(999.0)), "999");
        assert_eq!(fmt_short(None), "—");
    }

    #[test]
    fn money_short() {
        assert_eq!(fmt_money_short(Some(0.3755), Some("¥")), "¥0.38");
        assert_eq!(fmt_money_short(Some(1500.0), Some("$")), "$1.5k");
        assert_eq!(fmt_money_short(None, Some("$")), "—");
    }
}
