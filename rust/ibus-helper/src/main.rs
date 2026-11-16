//! Native IBus text output, with a user-runtime IPC endpoint.
mod ipc;
mod typing;
mod wire;

use std::{
    collections::{HashMap, HashSet, VecDeque},
    path::PathBuf,
    sync::Arc,
};
use tokio::sync::Mutex;
use zbus::{fdo, interface, object_server::ObjectServer, zvariant::OwnedObjectPath, Connection};

const NAME: &str = "org.freedesktop.IBus.Phonon";
const CONTROL: &str = "/org/phonon/Dictation";

#[derive(Default)]
struct Target {
    generation: u64,
    focused: Option<(String, String, String)>, // engine path, context ID, client
    enabled: HashSet<String>,
}

impl Target {
    fn invalidate(&mut self) {
        self.generation += 1;
    }

    fn leave(&mut self, path: &str) {
        self.invalidate();
        if self.focused.as_ref().is_some_and(|focus| focus.0 == path) {
            self.focused = None;
        }
    }
}

type Shared = Arc<Mutex<Target>>;

struct Engine {
    path: String,
    target: Shared,
    typing: std::sync::Mutex<typing::Typing>,
}

#[interface(name = "org.freedesktop.IBus.Engine", spawn = false)]
impl Engine {
    async fn process_key_event(
        &self,
        keyval: u32,
        keycode: u32,
        state: u32,
        #[zbus(connection)] connection: &Connection,
    ) -> fdo::Result<bool> {
        let (handled, text) = self.typing.lock().unwrap().process(keyval, keycode, state);
        if let Some(text) = text {
            emit_text(connection, &self.path, &text).await?;
        }
        Ok(handled)
    }

    async fn focus_in(&self) {
        self.focus_in_id("", "").await;
    }

    async fn focus_in_id(&self, context: &str, client: &str) {
        let mut target = self.target.lock().await;
        target.invalidate();
        target.focused = Some((self.path.clone(), context.into(), client.into()));
    }

    async fn focus_out(&self) {
        self.typing.lock().unwrap().leave();
        self.target.lock().await.leave(&self.path);
    }

    async fn focus_out_id(&self, _context: &str) {
        self.focus_out().await;
    }

    async fn enable(&self) {
        let mut target = self.target.lock().await;
        target.invalidate();
        target.enabled.insert(self.path.clone());
    }

    async fn disable(&self) {
        self.typing.lock().unwrap().leave();
        let mut target = self.target.lock().await;
        target.leave(&self.path);
        target.enabled.remove(&self.path);
    }

    async fn reset(&self) {
        self.typing.lock().unwrap().reset();
        self.target.lock().await.invalidate();
    }

    fn set_capabilities(&self, _caps: u32) {}
    fn set_cursor_location(&self, _x: i32, _y: i32, _w: i32, _h: i32) {}
    fn set_surrounding_text(&self, _text: zbus::zvariant::OwnedValue, _cursor: u32, _anchor: u32) {}

    #[zbus(property)]
    fn focus_id(&self) -> bool {
        true
    }

    #[zbus(property)]
    fn active_surrounding_text(&self) -> bool {
        false
    }

    #[zbus(property)]
    fn set_content_type(&self, _content: (u32, u32)) {}
}

struct Service {
    path: String,
    target: Shared,
}

#[interface(name = "org.freedesktop.IBus.Service", spawn = false)]
impl Service {
    async fn destroy(&self, #[zbus(object_server)] server: &ObjectServer) -> fdo::Result<()> {
        let mut target = self.target.lock().await;
        target.leave(&self.path);
        target.enabled.remove(&self.path);
        drop(target);
        // Remove the engine now; remove this service after its method returns.
        server.remove::<Engine, _>(self.path.as_str()).await?;
        let server = server.clone();
        let path = self.path.clone();
        tokio::spawn(async move {
            let _ = server.remove::<Service, _>(path.as_str()).await;
        });
        Ok(())
    }
}

struct Factory {
    next_id: u64,
    target: Shared,
}

// IBus 1.5 negotiates FocusId and then ActiveSurroundingText asynchronously.
// Its latter callback resends FocusInId only if the former callback has run.
// Serialize property replies on the wire, matching libibus/GDBus; zbus's default
// Properties interface spawns independent tasks and can reverse these replies.
struct EngineProperties;

#[interface(name = "org.freedesktop.DBus.Properties", spawn = false)]
impl EngineProperties {
    fn get(&self, interface: &str, property: &str) -> fdo::Result<zbus::zvariant::OwnedValue> {
        if interface != "org.freedesktop.IBus.Engine" {
            return Err(fdo::Error::UnknownInterface(interface.into()));
        }
        match property {
            "FocusId" => Ok(true.into()),
            "ActiveSurroundingText" => Ok(false.into()),
            _ => Err(fdo::Error::UnknownProperty(property.into())),
        }
    }

    fn get_all(&self, interface: &str) -> fdo::Result<HashMap<String, zbus::zvariant::OwnedValue>> {
        if interface != "org.freedesktop.IBus.Engine" {
            return Ok(HashMap::new());
        }
        Ok(HashMap::from([
            ("FocusId".into(), true.into()),
            ("ActiveSurroundingText".into(), false.into()),
        ]))
    }

    fn set(
        &self,
        interface: &str,
        property: &str,
        value: zbus::zvariant::OwnedValue,
    ) -> fdo::Result<()> {
        if interface != "org.freedesktop.IBus.Engine" {
            return Err(fdo::Error::UnknownInterface(interface.into()));
        }
        if property != "ContentType" {
            return Err(fdo::Error::PropertyReadOnly(property.into()));
        }
        let _: (u32, u32) = value
            .try_into()
            .map_err(|err: zbus::zvariant::Error| fdo::Error::InvalidArgs(err.to_string()))?;
        Ok(())
    }
}

#[interface(name = "org.freedesktop.IBus.Factory")]
impl Factory {
    async fn create_engine(
        &mut self,
        name: &str,
        #[zbus(object_server)] server: &ObjectServer,
    ) -> fdo::Result<OwnedObjectPath> {
        if name != "phonon" {
            return Err(fdo::Error::Failed("Unknown engine".into()));
        }
        self.next_id += 1;
        let path = format!("/org/freedesktop/IBus/Engine/Phonon/{}", self.next_id);
        server
            .at(
                path.as_str(),
                Engine {
                    path: path.clone(),
                    target: self.target.clone(),
                    typing: std::sync::Mutex::new(
                        typing::Typing::new().map_err(|err| fdo::Error::Failed(err.to_string()))?,
                    ),
                },
            )
            .await?;
        server
            .remove::<zbus::fdo::Properties, _>(path.as_str())
            .await?;
        server.at(path.as_str(), EngineProperties).await?;
        server
            .at(
                path.as_str(),
                Service {
                    path: path.clone(),
                    target: self.target.clone(),
                },
            )
            .await?;
        Ok(path.try_into().expect("generated object path"))
    }
}

#[derive(Clone)]
struct Control {
    target: Shared,
    instance: String,
    requests: Arc<Mutex<Requests>>,
}

#[derive(Default)]
struct Requests {
    entries: HashMap<String, (String, Option<(String, bool)>)>,
    order: VecDeque<String>,
}

async fn emit_text(connection: &Connection, engine: &str, text: &str) -> fdo::Result<()> {
    let text = wire::text(text).map_err(|err| fdo::Error::Failed(err.to_string()))?;
    connection
        .emit_signal(
            None::<&str>,
            engine,
            "org.freedesktop.IBus.Engine",
            "CommitText",
            &(text,),
        )
        .await?;
    Ok(())
}

impl Control {
    fn token(&self, target: &Target, engine: &str) -> String {
        format!("{}:{}:{}", self.instance, target.generation, engine)
    }

    async fn begin(&self) -> serde_json::Value {
        let target = self.target.lock().await;
        let Some((engine, context, client)) = target.focused.as_ref() else {
            return serde_json::json!({"ok": false, "selected": !target.enabled.is_empty(), "error": "No focused input field"});
        };
        if context.is_empty() || client == "fake" || !target.enabled.contains(engine) {
            return serde_json::json!({"ok": false, "selected": !target.enabled.is_empty(), "error": "No focused input field"});
        }
        let token = self.token(&target, engine);
        let request_id = uuid::Uuid::new_v4().to_string();
        let mut requests = self.requests.lock().await;
        while requests.order.len() >= 256 {
            if let Some(old) = requests.order.pop_front() {
                requests.entries.remove(&old);
            }
        }
        requests.order.push_back(request_id.clone());
        requests
            .entries
            .insert(request_id.clone(), (token.clone(), None));
        serde_json::json!({"ok": true, "selected": true, "request_id": request_id, "token": token, "context": context})
    }

    async fn commit_request(
        &self,
        connection: &Connection,
        request_id: &str,
        token: &str,
        text: &str,
    ) -> serde_json::Value {
        // Same lock order as begin. Reservations must have been issued by this
        // helper; expired/evicted IDs are rejected, never treated as new commits.
        let target = self.target.lock().await;
        let mut requests = self.requests.lock().await;
        let Some((reserved_token, committed)) = requests.entries.get_mut(request_id) else {
            return serde_json::json!({"ok": false, "error": "Unknown or expired request"});
        };
        if reserved_token != token {
            return serde_json::json!({"ok": false, "error": "Request token mismatch"});
        }
        if let Some((previous, emitted)) = committed {
            return if previous == text && *emitted {
                serde_json::json!({"ok": true, "status": "already_emitted"})
            } else if previous == text {
                serde_json::json!({"ok": false, "error": "Previous delivery uncertain; not emitted again"})
            } else {
                serde_json::json!({"ok": false, "error": "Request already used for different text"})
            };
        }
        let Some((engine, context, client)) = target.focused.as_ref() else {
            return serde_json::json!({"ok": false, "error": "Focus changed"});
        };
        if context.is_empty()
            || client == "fake"
            || !target.enabled.contains(engine)
            || self.token(&target, engine) != token
        {
            return serde_json::json!({"ok": false, "error": "Focus changed; transcription not committed"});
        }
        // Reserve the outcome before sending. A transport failure is ambiguous:
        // retrying must not emit the same request again.
        *committed = Some((text.to_owned(), false));
        match emit_text(connection, engine, text).await {
            Ok(()) => {
                *committed = Some((text.to_owned(), true));
                serde_json::json!({"ok": true, "status": "emitted"})
            }
            Err(_) => {
                serde_json::json!({"ok": false, "error": "Commit delivery uncertain; do not retry as a new request"})
            }
        }
    }
}

// Retained for protocol diagnostics. Dictation uses the reserved-request socket API.
#[interface(name = "org.phonon.Dictation1", spawn = false)]
impl Control {
    async fn get_target(&self) -> fdo::Result<(String, String)> {
        let target = self.target.lock().await;
        let (engine, context, _) = target
            .focused
            .as_ref()
            .filter(|focus| {
                !focus.1.is_empty() && focus.2 != "fake" && target.enabled.contains(&focus.0)
            })
            .ok_or_else(|| fdo::Error::Failed("No enabled focused engine".into()))?;
        Ok((self.token(&target, engine), context.clone()))
    }

    async fn commit(
        &self,
        token: &str,
        text: &str,
        #[zbus(connection)] connection: &Connection,
    ) -> fdo::Result<()> {
        let target = self.target.lock().await;
        let (engine, _, _) = target
            .focused
            .as_ref()
            .filter(|focus| {
                !focus.1.is_empty() && focus.2 != "fake" && target.enabled.contains(&focus.0)
            })
            .ok_or_else(|| fdo::Error::Failed("No enabled focused engine".into()))?;
        if self.token(&target, engine) != token {
            return Err(fdo::Error::Failed(
                "Focus changed; transcription not committed".into(),
            ));
        }
        // Hold the target lock until the signal is enqueued, ordering it against
        // focus callbacks handled by this helper. Client delivery isn't an ACK.
        emit_text(connection, engine, text).await?;
        Ok(())
    }
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let mut args = std::env::args().skip(1);
    let mut address = None;
    let mut socket = None;
    let mut activated = false;
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--address" => {
                address = Some(
                    args.next()
                        .ok_or_else(|| anyhow::anyhow!("Missing address"))?,
                )
            }
            "--socket" => {
                socket = Some(PathBuf::from(
                    args.next()
                        .ok_or_else(|| anyhow::anyhow!("Missing socket path"))?,
                ))
            }
            "--ibus" => activated = true,
            _ => {
                anyhow::bail!("Usage: phonon-ibus-helper --ibus | --address ADDRESS --socket PATH")
            }
        }
    }
    let address = match address {
        Some(value) => value,
        None => {
            let result = std::process::Command::new("ibus").arg("address").output()?;
            anyhow::ensure!(result.status.success(), "IBus is unavailable");
            String::from_utf8(result.stdout)?.trim().to_owned()
        }
    };
    let socket = socket.unwrap_or_else(|| {
        PathBuf::from(std::env::var("XDG_RUNTIME_DIR").expect("XDG_RUNTIME_DIR is required"))
            .join("phonon/ibus.sock")
    });
    let target = Shared::default();
    let control = Control {
        target: target.clone(),
        instance: uuid::Uuid::new_v4().to_string(),
        requests: Default::default(),
    };
    let connection = zbus::connection::Builder::address(address.as_str())?
        .name(NAME)?
        .serve_at(
            "/org/freedesktop/IBus/Factory",
            Factory {
                next_id: 0,
                target: target.clone(),
            },
        )?
        .serve_at(CONTROL, control.clone())?
        .build()
        .await?;
    let bus = zbus::Proxy::new(
        &connection,
        "org.freedesktop.IBus",
        "/org/freedesktop/IBus",
        "org.freedesktop.IBus",
    )
    .await?;
    if !activated {
        let _: () = bus
            .call("RegisterComponent", &(wire::component()?,))
            .await?;
    }
    println!("Phonon IBus engine ready");
    let mut terminate = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())?;
    tokio::select! {
        result = ipc::run(&socket, Arc::new(control), connection.clone()) => { result?; }
        _ = tokio::signal::ctrl_c() => {},
        _ = terminate.recv() => {},
        _ = async { while !connection.is_closed() { tokio::time::sleep(std::time::Duration::from_secs(1)).await; } } => {},
    }
    let _ = std::fs::remove_file(socket);
    Ok(())
}
