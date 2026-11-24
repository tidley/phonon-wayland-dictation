# Native IBus output: feasibility investigation

This document retains the original Debian feasibility investigation. For current
installation instructions, including NixOS, see the [README](README.md#native-ibus-input-optional)
and [Rust helper guide](rust/ibus-helper/README.md).

## Conclusion

Native text insertion is feasible on the inspected Debian GNOME/Wayland setup.
Implement an optional **Rust IBus engine/helper**, with local IPC from the
existing dictation process. The helper must be selected as an input method;
IBus is not a general background application's text-injection API.

Implementation is tracked in [issue #2](https://github.com/tidley/phonon-wayland-dictation/issues/2).
The Rust engine, per-user installer, application output integration, and
declarative NixOS package are implemented; see the helper guide for installation
and selection. Initial investigation tests
used an isolated daemon and did not change desktop configuration.

## Original Debian observations

- GNOME Shell 48.7, IBus 1.5.32, and an active GNOME IBus daemon.
- System Python can load the IBus introspection bindings; the speech application's
  virtual environment cannot. Python is not required for the proposed helper.
- Rust and Cargo are installed. The `ibus-1.0` pkg-config development metadata is
  absent, so a libibus-based Rust build would need development dependencies.
- GNOME's configured source is `('xkb', 'gb')`, while `ibus engine` reports
  `xkb:us::eng`. These are separate observations, not a reason to change the
  user's layout automatically. A Phonon source must preserve the intended layout.

### Isolated protocol experiment

An ad-hoc Python/PyGObject probe was run under `dbus-run-session`, with its own
IBus daemon, socket, and temporary config/cache directories. It did not switch
the desktop's engine or insert text into a real application.

The experiment successfully:

1. Registered an engine component and factory.
2. Selected that engine on the **isolated** bus and received engine creation and
   focus notifications.
3. Committed Unicode and multiline text, including a trailing space, using
   `IBus.Engine.commit_text(IBus.Text.new_from_string(text))`.
4. Received the exact text in a test input context's `commit-text` callback.
5. Returned an ordinary letter key to the client rather than consuming it.

An initial attempt to select the engine only on the input context did not create
the engine: IBus's global-engine mode ignores per-context engine selection.
Selecting it globally on the isolated bus resolved this. The upstream engine
switch test documents this behavior.

Focus-in/out signals were observed. The simple engine's exposed `has_focus` field
was false despite delivered focus signals, so the implementation should track
explicit callbacks/context IDs rather than assume that field is sufficient.

This initial experiment confirmed the protocol path, not application compatibility.
It was followed by the compiled Rust prototype described below.

### Rust milestone

The zbus-based helper now registers its own component and factory, emits real
IBus text commits, passes ordinary keys through, and tracks focus IDs and engine
lifecycle. A repeatable private-daemon integration harness verifies exact text
delivery, focus changes across two clients, stale-token rejection, reset,
focus-out/refocus, engine disable, and 25 ordered commits. Python is used only
as the GI test client; the engine is Rust. See the helper README for commands
and remaining desktop-integration work.

The selectable-engine stage now includes the installer, a runtime-directory
socket, reserved/deduplicated requests, application output routing, and
libxkbcommon Compose/dead-key support. An additional staged-install harness
verifies real descriptor discovery, cached registry loading, and activation
by IBus. Desktop application compatibility remains a manual-validation task.

### NixOS integration and verification

On NixOS 26.05 with GNOME 50.6 and IBus 1.5.33, the installed
`ibus-with-plugins` wrapper unconditionally replaces `IBUS_COMPONENT_PATH`.
Therefore, extending that variable through a systemd environment drop-in is
insufficient. The implementation packages the Rust helper and XML descriptor as
an IBus engine and appends it through `i18n.inputMethod.ibus.engines`, preserving
the other configured engines and rooting the runtime closure in the system
generation. GNOME source registration remains per-user and preserves existing
keyboard sources.

Nix-managed Rust 1.95 and libxkbcommon build the helper successfully; development
Cargo output is kept separate from the shared checkout's Debian target. The
runtime-registration, staged-install and Nix-packaged integration modes pass
against private IBus daemons. A dedicated GTK field in the actual GNOME Wayland
session also received Unicode text through the native client without a clipboard
change. Cached local CPU model startup and keyboard monitoring were verified.

This desktop check supplied known text, not recorded speech. Physical hotkey
dictation, broader toolkit compatibility, logout/reboot and administrator-activated
rebuild persistence still need manual validation. See [CHANGELOG.md](CHANGELOG.md)
for the current verification summary.

## Recommended architecture

```text
Existing evdev trigger -> FFmpeg -> existing serial transcription worker
                                            |
                                  local request with text
                                            v
                                Rust Phonon IBus helper
                                            |
                                      CommitText
                                            v
                             focused IBus-capable application
```

- Keep the working recording, evdev recovery, and Phonon-2 server lifecycle.
- Add an explicit output destination such as `--output ibus`; preserve the
  existing clipboard destination as the default during rollout.
- Run the helper independently from the speech virtual environment. Let IBus
  activate it through a component/engine descriptor and offer it as a GNOME
  input source. Verify descriptor discovery and installation on Debian before
  choosing a user-local installation mechanism.
- Use a Unix socket under the user's runtime directory, or a session D-Bus
  interface, for communication with the dictation process. Requests need IDs and
  explicit responses so a failed/ambiguous request cannot cause duplicate text
  through an automatic paste retry.
- Record a focus-generation/context token at capture start; check it before
  committing the transcription. A change of focus or selected engine must not
  silently redirect a delayed transcription to another field. Focus IDs do not
  necessarily identify individual widgets on every toolkit, so test this on
  GNOME, including movement within one window.
- Service IBus callbacks and IPC promptly; audio capture and transcription stay
  in their existing process/worker.
- Native commit does not use `wl-copy`, `ydotool`, a paste shortcut, or the paste
  delay. The normal/terminal paste-mode distinction is unnecessary for this
  destination; terminal behavior still needs validation.

## Rust implementation route

The preferred first prototype is a Rust helper using **zbus** to implement the
IBus D-Bus engine/factory interfaces. Current zbus documentation includes an IBus
connection builder; it discovers the separate IBus bus via `ibus address`.
Connecting only to the ordinary session bus is not equivalent.

Implement component/engine registration, factory creation, engine lifecycle and
focus methods, ordinary-key passthrough, and `CommitText`. IBus text/component
values use IBus-specific serialization inside D-Bus variants; match upstream
wire types and test interoperability with the installed daemon.

The crate named `ibus` is not a complete engine SDK: its published 0.2.0 release
and README describe a limited, client-focused API. Do not assume it provides
the engine implementation just because of its name.

Ordinary-key passthrough alone does not prove Compose/dead-key compatibility.
The protocol probe used `IBus.EngineSimple`, which supplies existing simple-engine
behavior. A pure Rust engine must preserve keyboard/Compose behavior explicitly.
If that becomes the larger implementation burden, Rust bindings to libibus and
`EngineSimple` are a viable route, with GObject/GLib integration and development
packages as additional build requirements.

## Original implementation plan and remaining validation

Steps 1–3 are implemented and covered by the helper's automated tests. Steps
4–6 remain the broader manual compatibility checklist; the NixOS GTK clipboard
preservation check above covers one application and session.

1. Build the Rust engine against an isolated IBus daemon. Verify exact Unicode
   and multiline commits, ordinary-key handling, focus/context IDs, and engine
   activation/deactivation before connecting it to the desktop.
2. Add request/response IPC and focus-token handling. Verify slow transcription,
   focus changes, helper restarts, and repeated requests without duplicate commits.
3. Register an opt-in Phonon input source on GNOME, preserving the GB layout;
   test ordinary typing, shortcuts, Compose, and dead keys.
4. Test native insertion in GNOME Text Editor, Terminator/VTE, Firefox, and the
   actual Electron/Wayland applications in use. For SSH, the local terminal
   must accept the committed text; the remote program needs no IBus integration.
   This does not establish bracketed-paste semantics or automatic submission.
5. Test switching applications or fields during transcription, non-text focus,
   source switching, lock/unlock, suspend/resume, and rapid dictation cycles.
6. Confirm the clipboard is unchanged and the IBus destination invokes neither
   clipboard commands nor synthetic paste shortcuts.

## References

- [IBus engine API and commit_text](https://ibus.github.io/docs/ibus-1.5/IBusEngine.html)
- [IBus 1.5.32 engine header, including focus-ID callbacks](https://github.com/ibus/ibus/blob/1.5.32/src/ibusengine.h)
- [Upstream global/per-context engine switching tests](https://github.com/ibus/ibus/blob/1.5.32/src/tests/ibus-engine-switch.c)
- [zbus IBus connection builder](https://docs.rs/zbus/latest/zbus/connection/struct.Builder.html#method.ibus)
- [ibus-rs scope and implementation](https://github.com/ArturKovacs/ibus-rs)
