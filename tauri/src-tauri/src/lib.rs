//! TokenMon Tauri 后端: 配置热载 / 网关抓取转发 / 托盘 / 窗口命令。
//!
//! 数据层全部在 tokenmon-core(纯 Rust, 可独立单测), 这里只做薄封装。

use std::path::{Path, PathBuf};
use std::sync::Mutex;

use serde::Serialize;
use tauri::menu::{IsMenuItem, Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{Emitter, Manager, WebviewWindow};

use tokenmon_core::config::{
    config_dir, config_path, load_config, AppConfig, GatewayConfig, WindowConfig, DEFAULT_CONFIG,
};
use tokenmon_core::{Conversation, Usage};

pub struct AppState {
    cfg: Mutex<AppConfig>,
    path: PathBuf,
}

impl AppState {
    fn new() -> Self {
        let path = config_path();
        ensure_default_config(&path);
        let cfg = load_config(&path).unwrap_or_default();
        AppState { cfg: Mutex::new(cfg), path }
    }

    fn gateway(&self) -> GatewayConfig {
        self.cfg.lock().unwrap().gateway.clone()
    }

    fn replace(&self, cfg: AppConfig) {
        *self.cfg.lock().unwrap() = cfg;
    }
}

fn ensure_default_config(path: &Path) {
    if path.exists() {
        return;
    }
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    let _ = std::fs::write(path, DEFAULT_CONFIG);
    #[cfg(not(windows))]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600));
    }
}

#[derive(Serialize)]
struct ConfigPayload {
    gateway: GatewayConfig,
    window: WindowConfig,
    error: Option<String>,
    config_path: String,
}

fn build_payload(state: &AppState) -> ConfigPayload {
    let cfg = state.cfg.lock().unwrap().clone();
    let error = if state.path.exists() {
        load_config(&state.path)
            .err()
            .map(|e| format!("配置错误: {e}"))
    } else {
        None
    };
    ConfigPayload {
        gateway: cfg.gateway,
        window: cfg.window,
        error,
        config_path: state.path.display().to_string(),
    }
}

/// 用系统默认方式打开文件/目录(文本编辑器/文件管理器)。
fn open_with_default_app(path: &Path) -> Result<(), String> {
    #[cfg(windows)]
    {
        std::process::Command::new("cmd")
            .args(["/C", "start", "", &path.display().to_string()])
            .spawn()
            .map_err(|e| e.to_string())?;
        return Ok(());
    }
    #[cfg(not(windows))]
    {
        if path.is_file() {
            if let Ok(editor) = std::env::var("VISUAL").or_else(|_| std::env::var("EDITOR")) {
                let mut parts = editor.split_whitespace().collect::<Vec<_>>();
                parts.push(path.to_str().unwrap_or(""));
                if std::process::Command::new(parts[0])
                    .args(&parts[1..])
                    .spawn()
                    .is_ok()
                {
                    return Ok(());
                }
            }
        }
        let _ = std::process::Command::new("xdg-open")
            .arg(path)
            .spawn()
            .map_err(|e| e.to_string())?;
        Ok(())
    }
}

// --------------------------------------------------------------------------
// 前端命令
// --------------------------------------------------------------------------

#[tauri::command]
fn get_config(state: tauri::State<AppState>) -> ConfigPayload {
    build_payload(state.inner())
}

#[tauri::command]
fn fetch_usage(state: tauri::State<AppState>) -> Result<Usage, String> {
    tokenmon_core::fetch_usage(&state.gateway()).map_err(|e| e.to_string())
}

#[tauri::command]
fn fetch_conversations(state: tauri::State<AppState>) -> Result<Vec<Conversation>, String> {
    tokenmon_core::fetch_conversations(&state.gateway()).map_err(|e| e.to_string())
}

#[tauri::command]
fn edit_config(state: tauri::State<AppState>) -> Result<String, String> {
    open_with_default_app(&state.path)?;
    Ok(state.path.display().to_string())
}

#[tauri::command]
fn open_config_dir(_state: tauri::State<AppState>) -> Result<(), String> {
    open_with_default_app(&config_dir())
}

#[tauri::command]
fn reload_config(app: tauri::AppHandle, state: tauri::State<AppState>) -> ConfigPayload {
    match load_config(&state.path) {
        Ok(cfg) => {
            state.replace(cfg);
            // 置顶等窗口设置随配置生效
            if let Some(win) = app.get_webview_window("main") {
                let top = state.cfg.lock().unwrap().window.always_on_top;
                let _ = win.set_always_on_top(top);
                set_tray_topmost_checked(&app, top);
            }
            build_payload(state.inner())
        }
        Err(err) => ConfigPayload {
            gateway: state.gateway(),
            window: state.cfg.lock().unwrap().window.clone(),
            error: Some(format!("配置错误: {err}")),
            config_path: state.path.display().to_string(),
        },
    }
}

#[tauri::command]
fn set_always_on_top(
    app: tauri::AppHandle,
    window: WebviewWindow,
    on: bool,
) -> Result<(), String> {
    window.set_always_on_top(on).map_err(|e| e.to_string())?;
    let state = app.state::<AppState>();
    state.cfg.lock().unwrap().window.always_on_top = on;
    set_tray_topmost_checked(&app, on);
    Ok(())
}

#[tauri::command]
fn hide_ball(window: WebviewWindow) -> Result<(), String> {
    window.hide().map_err(|e| e.to_string())
}

#[tauri::command]
fn quit(app: tauri::AppHandle) {
    app.exit(0);
}

// --------------------------------------------------------------------------
// 托盘
// --------------------------------------------------------------------------

fn set_tray_topmost_checked(app: &tauri::AppHandle, on: bool) {
    if let Some(tray) = app.tray_by_id("main") {
        if let Some(menu) = tray.menu() {
            if let Some(item) = menu.get("topmost") {
                if let Some(mi) = item.as_menuitem() {
                    let _ = mi.set_checked(on);
                }
            }
        }
    }
}

fn emit_to_main(app: &tauri::AppHandle, event: &str) {
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.emit(event, ());
    }
}

fn setup_tray(app: &tauri::App) -> tauri::Result<()> {
    let toggle = MenuItem::with_id(app, "toggle", "展开面板", true, None::<&str>)?;
    let refresh = MenuItem::with_id(app, "refresh", "刷新", true, None::<&str>)?;
    let skin_poke = MenuItem::with_id(app, "skin-pokeball", "精灵球", true, None::<&str>)?;
    let skin_master = MenuItem::with_id(app, "skin-master", "大师球", true, None::<&str>)?;
    let skin_great = MenuItem::with_id(app, "skin-great", "超级球", true, None::<&str>)?;
    let skin_ultra = MenuItem::with_id(app, "skin-ultra", "高级球", true, None::<&str>)?;
    let skins = Submenu::with_items(
        app,
        "皮肤",
        true,
        &[&skin_poke, &skin_master, &skin_great, &skin_ultra],
    )?;
    let topmost = MenuItem::with_id(app, "topmost", "窗口置顶", true, None::<&str>)?;
    let edit_cfg = MenuItem::with_id(app, "edit-config", "编辑配置…", true, None::<&str>)?;
    let open_dir = MenuItem::with_id(app, "open-config-dir", "打开配置目录", true, None::<&str>)?;
    let reload = MenuItem::with_id(app, "reload-config", "重载配置", true, None::<&str>)?;
    let settings = Submenu::with_items(
        app,
        "设置",
        true,
        &[&topmost, &edit_cfg, &open_dir, &reload],
    )?;
    let quit = MenuItem::with_id(app, "quit", "退出", true, None::<&str>)?;
    let sep = PredefinedMenuItem::separator(app)?;
    let menu = Menu::with_items(app, &[&toggle, &refresh, &skins, &settings, &sep, &quit])?;

    let icon = app
        .default_window_icon()
        .cloned()
        .expect("default window icon: 请检查 bundle.icon 配置");

    let _tray = TrayIconBuilder::with_id("main")
        .icon(icon)
        .menu(&menu)
        .show_menu_on_left_click(false)
        .tooltip("TokenMon")
        .on_menu_event(|app, event| match event.id.as_ref() {
            "toggle" => emit_to_main(app, "tm-toggle"),
            "refresh" => emit_to_main(app, "tm-refresh"),
            "skin-pokeball" => emit_to_main(app, "tm-skin-pokeball"),
            "skin-master" => emit_to_main(app, "tm-skin-master"),
            "skin-great" => emit_to_main(app, "tm-skin-great"),
            "skin-ultra" => emit_to_main(app, "tm-skin-ultra"),
            "topmost" => emit_to_main(app, "tm-topmost"),
            "edit-config" => emit_to_main(app, "tm-edit-config"),
            "open-config-dir" => emit_to_main(app, "tm-open-config-dir"),
            "reload-config" => emit_to_main(app, "tm-reload-config"),
            "quit" => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            // 左键单击: 重新拉起被隐藏的球, 或隐藏
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                let app = tray.app_handle();
                if let Some(win) = app.get_webview_window("main") {
                    if win.is_visible().unwrap_or(true) {
                        let _ = win.hide();
                    } else {
                        let _ = win.show();
                        let _ = win.unminimize();
                        let _ = win.set_focus();
                    }
                }
            }
        })
        .build(app)?;
    let _ = _tray;
    Ok(())
}

// --------------------------------------------------------------------------

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(win) = app.get_webview_window("main") {
                let _ = win.show();
                let _ = win.unminimize();
                let _ = win.set_focus();
            }
        }))
        .manage(AppState::new())
        .setup(|app| {
            setup_tray(app)?;
            // 按配置应用置顶
            let state = app.state::<AppState>();
            let top = state.cfg.lock().unwrap().window.always_on_top;
            set_tray_topmost_checked(app.handle(), top);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_config,
            fetch_usage,
            fetch_conversations,
            edit_config,
            open_config_dir,
            reload_config,
            set_always_on_top,
            hide_ball,
            quit,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
