//! One bounded JSON request/response per Unix-socket connection.
use crate::Control;
use serde::Deserialize;
use serde_json::{json, Value};
use std::{os::unix::fs::PermissionsExt, path::Path, sync::Arc, time::Duration};
use tokio::{
    io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader},
    net::{UnixListener, UnixStream},
};
use zbus::Connection;

const MAX_REQUEST: u64 = 1024 * 1024;

#[derive(Deserialize)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
enum Request {
    Begin,
    Commit {
        request_id: String,
        token: String,
        text: String,
    },
}

async fn serve(
    stream: UnixStream,
    control: Arc<Control>,
    connection: Connection,
) -> anyhow::Result<()> {
    let (reader, mut writer) = stream.into_split();
    let mut reader = BufReader::new(reader).take(MAX_REQUEST + 1);
    let mut line = String::new();
    let response: Value =
        match tokio::time::timeout(Duration::from_secs(2), reader.read_line(&mut line)).await {
            Ok(Ok(n)) if n <= MAX_REQUEST as usize && line.ends_with('\n') => {
                match serde_json::from_str::<Request>(&line) {
                    Ok(Request::Begin) => control.begin().await,
                    Ok(Request::Commit {
                        request_id,
                        token,
                        text,
                    }) => {
                        control
                            .commit_request(&connection, &request_id, &token, &text)
                            .await
                    }
                    Err(_) => json!({"ok": false, "error": "Invalid request"}),
                }
            }
            _ => json!({"ok": false, "error": "Incomplete or oversized request"}),
        };
    writer.write_all(format!("{response}\n").as_bytes()).await?;
    Ok(())
}

pub async fn run(path: &Path, control: Arc<Control>, connection: Connection) -> anyhow::Result<()> {
    let parent = path
        .parent()
        .ok_or_else(|| anyhow::anyhow!("Socket needs a parent directory"))?;
    std::fs::create_dir_all(parent)?;
    // Only chmod the directory we own, never the whole runtime directory.
    anyhow::ensure!(
        parent.file_name().is_some_and(|name| name == "phonon"),
        "Socket must be inside a directory named phonon"
    );
    std::fs::set_permissions(parent, std::fs::Permissions::from_mode(0o700))?;
    if path.exists() {
        anyhow::ensure!(
            UnixStream::connect(path).await.is_err(),
            "An IBus helper socket is already active"
        );
        std::fs::remove_file(path)?;
    }
    let listener = UnixListener::bind(path)?;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
    // Limit stalled clients without blocking IBus dispatch.
    let permits = Arc::new(tokio::sync::Semaphore::new(16));
    loop {
        let permit = permits.clone().acquire_owned().await?;
        let (stream, _) = listener.accept().await?;
        let control = control.clone();
        let connection = connection.clone();
        tokio::spawn(async move {
            let _permit = permit;
            let _ =
                tokio::time::timeout(Duration::from_secs(3), serve(stream, control, connection))
                    .await;
        });
    }
}
