// Argos Tauri backend — 独立通用智能体的壳。
//
// Argos = Tauri 壳(React/TS UI + 本 Rust 后端)+ Python agent 服务(FastAPI+LangGraph)。
// 本后端负责:① 启动时拉起 Python agent 服务;② 暴露它的地址给前端;
// ③ 进程生命周期(随 app 退出而终止)。Python 服务承载 agent loop + verify/护城河。
//
// prod:Tauri sidecar 调打包好的可执行文件(PyInstaller 单文件,binaries/argos-agent-<triple>)。
// dev:sidecar 不存在时回退到 `uv run uvicorn` 拉起 agent/ 目录的源码服务(免打包)。
// MiniMax key 通过环境变量注入给 sidecar(key 不进打包产物,生产正道)。

use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;

use serde::{Deserialize, Serialize};
use tauri::Manager;
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::CommandChild;

const AGENT_PORT: u16 = 8848;

/// app 配置(持久化到用户配置目录,不进 bundle/git)。key 存这里,GUI 双击也能读到 —
/// 解决"Finder 启动不继承 shell env、sidecar 读不到 key、只能跑 DEMO"的根本问题。
#[derive(Default, Serialize, Deserialize)]
struct Settings {
    #[serde(default)]
    minimax_key: String,
    #[serde(default)]
    minimax_model: String,
}

/// 配置文件路径:~/Library/Application Support/com.argos.app/settings.json(macOS)。
/// 用 dirs::config_dir 跨平台;拿不到则退到当前目录(极端兜底)。
fn settings_path() -> PathBuf {
    let mut p = dirs::config_dir().unwrap_or_else(|| PathBuf::from("."));
    p.push("com.argos.app");
    p.push("settings.json");
    p
}

// 路径参数化(便于测试);默认走 settings_path()。
fn load_at(p: &std::path::Path) -> Settings {
    std::fs::read_to_string(p)
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_default()
}

fn save_at(p: &std::path::Path, s: &Settings) -> Result<(), String> {
    if let Some(dir) = p.parent() {
        std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    }
    let json = serde_json::to_string_pretty(s).map_err(|e| e.to_string())?;
    std::fs::write(p, json).map_err(|e| e.to_string())
}

fn load_settings() -> Settings {
    load_at(&settings_path())
}

fn save_settings(s: &Settings) -> Result<(), String> {
    save_at(&settings_path(), s)
}

/// 前端读当前设置(key 只回是否已配置 + 后四位,不回明文,避免界面泄露完整 key)。
#[tauri::command]
fn get_settings() -> serde_json::Value {
    let s = load_settings();
    let key_tail = if s.minimax_key.len() >= 4 {
        s.minimax_key[s.minimax_key.len() - 4..].to_string()
    } else {
        String::new()
    };
    serde_json::json!({
        "key_configured": !s.minimax_key.is_empty(),
        "key_tail": key_tail,
        "model": s.minimax_model,
    })
}

/// 前端写 key(/可选 model)。保存后需重启 app 让新 sidecar 带上 key —— 返回提示由前端给。
#[tauri::command]
fn set_minimax_key(key: String, model: Option<String>) -> Result<(), String> {
    let mut s = load_settings();
    s.minimax_key = key.trim().to_string();
    if let Some(m) = model {
        let m = m.trim();
        if !m.is_empty() {
            s.minimax_model = m.to_string();
        }
    }
    save_settings(&s)
}

/// 持有 agent 子进程句柄(两种来源:sidecar 或 dev 的 uv),app 退出时杀掉。
enum AgentChild {
    Sidecar(CommandChild),
    Dev(Child),
}
struct AgentProc(Mutex<Option<AgentChild>>);

/// agent 服务地址,前端用它直接 fetch(SSE /run、/health)。
#[tauri::command]
fn agent_base_url() -> String {
    format!("http://127.0.0.1:{AGENT_PORT}")
}

/// 注入给 sidecar 的环境。key 来源优先级:
///   1) 持久化配置文件(用户在设置界面填的)—— 打包 .app 双击的正道,GUI 不继承 shell env;
///   2) 进程环境变量 VITE_MINIMAX_KEY —— dev 从 shell 起 app 时方便;
///   3) 都没有 → 不注入,sidecar 自己回退读仓库 .env.local(纯 dev)。
fn minimax_env() -> Vec<(String, String)> {
    let mut env = Vec::new();
    let cfg = load_settings();

    let key = if !cfg.minimax_key.is_empty() {
        Some(cfg.minimax_key)
    } else {
        std::env::var("VITE_MINIMAX_KEY").ok()
    };
    if let Some(k) = key {
        env.push(("VITE_MINIMAX_KEY".into(), k));
    }

    let model = if !cfg.minimax_model.is_empty() {
        Some(cfg.minimax_model)
    } else {
        std::env::var("VITE_MINIMAX_MODEL").ok()
    };
    if let Some(m) = model {
        env.push(("VITE_MINIMAX_MODEL".into(), m));
    }

    env.push(("ARGOS_AGENT_PORT".into(), AGENT_PORT.to_string()));
    env
}

/// 优先用打包的 sidecar 拉起 agent;失败(dev 无 sidecar)则回退 `uv run uvicorn`。
fn spawn_agent(app: &tauri::AppHandle) -> Option<AgentChild> {
    // 1) prod:sidecar(binaries/argos-agent-<target-triple>)。
    match app.shell().sidecar("argos-agent") {
        Ok(cmd) => {
            let cmd = cmd.envs(minimax_env());
            match cmd.spawn() {
                Ok((_rx, child)) => {
                    eprintln!("[argos] sidecar agent 已拉起 :{AGENT_PORT}");
                    return Some(AgentChild::Sidecar(child));
                }
                Err(e) => eprintln!("[argos] sidecar spawn 失败({e}),回退 dev"),
            }
        }
        Err(e) => eprintln!("[argos] 无 sidecar({e}),回退 dev"),
    }
    // 2) dev:uv run uvicorn(源码,免打包)。
    let mut c = Command::new("uv");
    c.args(["run", "uvicorn", "argos_agent.server:app", "--port", &AGENT_PORT.to_string()])
        .current_dir("../agent");
    for (k, v) in minimax_env() {
        c.env(k, v);
    }
    match c.spawn() {
        Ok(child) => {
            eprintln!("[argos] dev agent(uv)已拉起 :{AGENT_PORT}");
            Some(AgentChild::Dev(child))
        }
        Err(e) => {
            eprintln!("[argos] 拉起 agent 失败({e});前端会显示未连接");
            None
        }
    }
}

fn kill_child(child: AgentChild) {
    match child {
        AgentChild::Sidecar(c) => { let _ = c.kill(); }
        AgentChild::Dev(mut c) => { let _ = c.kill(); }
    }
}

/// 重启 agent sidecar:杀旧 + 重 spawn(读最新 settings 的 key)。
/// 这是"填了 key 立即生效"的入口 —— 用户在设置界面填 key 后点重启,
/// 无需退出整个 app(sidecar 启动时读 key,所以必须重启 sidecar 才能带上新 key)。
#[tauri::command]
fn restart_agent(app: tauri::AppHandle) -> Result<(), String> {
    // 1) 杀掉当前 sidecar
    if let Some(state) = app.try_state::<AgentProc>() {
        if let Some(old) = state.0.lock().unwrap().take() {
            kill_child(old);
        }
    }
    // 2) 给端口一点释放时间,再重新拉起(带新 env)
    std::thread::sleep(std::time::Duration::from_millis(400));
    match spawn_agent(&app) {
        Some(child) => {
            if let Some(state) = app.try_state::<AgentProc>() {
                *state.0.lock().unwrap() = Some(child);
            }
            Ok(())
        }
        None => Err("重新拉起 agent 失败".into()),
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(AgentProc(Mutex::new(None)))
        .setup(|app| {
            let handle = app.handle().clone();
            if let Some(child) = spawn_agent(&handle) {
                *app.state::<AgentProc>().0.lock().unwrap() = Some(child);
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            // 主窗口关闭 → 杀掉 agent 子进程,避免遗留。
            if let tauri::WindowEvent::Destroyed = event {
                if let Some(state) = window.app_handle().try_state::<AgentProc>() {
                    if let Some(child) = state.0.lock().unwrap().take() {
                        kill_child(child);
                    }
                }
            }
        })
        .invoke_handler(tauri::generate_handler![agent_base_url, get_settings, set_minimax_key, restart_agent])
        .run(tauri::generate_context!())
        .expect("error while running argos");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn settings_roundtrip() {
        // 写 key → 读回:这是打包 app 配 key 的命门(GUI 不继承 env,必须靠持久化)
        let dir = std::env::temp_dir().join(format!("argos-test-{}", std::process::id()));
        let p = dir.join("settings.json");
        let _ = std::fs::remove_file(&p);

        // 初始:无文件 → 默认空(诚实空态)
        let s0 = load_at(&p);
        assert!(s0.minimax_key.is_empty());

        // 写 key + model
        let s1 = Settings { minimax_key: "sk-test-1234".into(), minimax_model: "MiniMax-M3".into() };
        save_at(&p, &s1).unwrap();

        // 读回:key/model 都在
        let s2 = load_at(&p);
        assert_eq!(s2.minimax_key, "sk-test-1234");
        assert_eq!(s2.minimax_model, "MiniMax-M3");

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn empty_key_is_demo_mode() {
        // 空 key → get_settings 报 key_configured:false(诚实:只能跑演示)
        let s = Settings::default();
        assert!(s.minimax_key.is_empty());
        // key_tail 逻辑:不足 4 位不泄露
        let tail = if s.minimax_key.len() >= 4 { &s.minimax_key[s.minimax_key.len()-4..] } else { "" };
        assert_eq!(tail, "");
    }

    #[test]
    fn key_tail_only_last_four() {
        // 已配 key → 只回后四位,不泄露完整 key
        let s = Settings { minimax_key: "sk-secret-abcd".into(), minimax_model: String::new() };
        let tail = &s.minimax_key[s.minimax_key.len()-4..];
        assert_eq!(tail, "abcd");
        assert_ne!(tail, s.minimax_key); // 确实只是尾巴,不是全部
    }
}
