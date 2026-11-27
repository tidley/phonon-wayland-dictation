# Changelog

## Unreleased

### Added

- NixOS installation with a declarative IBus engine package and graphical-login
  service using `--output auto`. Existing NixOS IBus engines are retained through
  list merging. The supplied Nix shell includes the native build/runtime
  dependencies and keeps Cargo output separate from Debian's shared-checkout
  artefacts and virtualenv.
- `install_ibus.py --register-only` for GNOME source registration after installing
  the engine declaratively, and `--packaged` integration tests for NixOS's actual
  IBus wrapper and descriptor discovery.
- Optional Rust IBus input source with per-user GNOME installation, native text
  insertion, Compose/dead-key and Unicode entry, runtime-socket IPC, focus tokens,
  and request deduplication ([#2]). The installer preserves other input sources
  and can enable automatic IBus/clipboard routing. Without that configuration,
  clipboard output remains the application default.
- Isolated tests for installed-engine discovery/activation, native IPC, stale
  results, duplicate requests, normal typing, rapid commits, and helper restart.

### Fixed

- Recover native Phonon input after GNOME unlock leaves the US keyboard fallback
  active following cancelled engine switches. A background unlock watcher
  rechecks the user's source preference and unlocked state before bounded
  reactivation; per-window sources and clipboard-only output are excluded.
- Discover and preserve IBus component paths instead of assuming
  `/usr/share/ibus/component`. NixOS uses its engine package mechanism because
  its wrapper replaces `IBUS_COMPONENT_PATH`; an environment-only drop-in does
  not work there. Conventional per-user installation remains supported.
- Honour `CARGO_TARGET_DIR` for both build and `--no-build` installation.
- Serialize IBus engine-property replies so initial focus-ID negotiation remains
  reliable when selecting or restarting the native engine.
- Recover from evdev `SYN_DROPPED` without treating the keyboard as disconnected:
  discard events through the next `SYN_REPORT`, query held keys, and reconcile
  modifiers while retaining the open device. Cancel capture only if the
  initiating key is released or its state cannot be recovered.
- Track the keyboard that initiated capture so unrelated keyboard removals or
  releases cannot prematurely stop recording. Coalesce mirrored input presses
  without transferring recording ownership when the initiating device disappears.
- Process completed recordings in a serial worker and drain readable input
  buffers to `EAGAIN`, keeping transcription and clipboard operations off the
  keyboard event loop.
- Cache unchanged input devices that do not provide the hotkey modifiers instead
  of reopening them during every periodic scan. Invalidate cached identities on
  disappearance, replacement, udev notifications, and resume; continue retrying
  inaccessible devices for permission recovery. This removes recurring scan
  stalls that could overflow keyboard event buffers ([#1]).

### Verification

- Unlock recovery: all 76 Python tests passed, and a private session-bus check
  verified unlock-event dispatch and monitor shutdown. The user confirmed that
  Right Ctrl dictation works after a real GNOME lock/unlock without toggling
  input sources.
- 67 automated Python tests cover input recovery, recording ownership, mirrored events,
  input during transcription and paste, device-cache invalidation, hotplug,
  permission retries, suspend/resume handling, native-output routing/failures,
  installer configuration preservation, component-path discovery, and separate
  build-target selection.
- All three real-IBus integration modes pass against an isolated daemon on
  NixOS 26.05 / IBus 1.5.33: runtime registration/helper restart, staged
  installation, and Nix-packaged discovery/activation. Rust release build,
  Clippy, and formatting checks pass with Nix-managed Rust 1.95.
- A real GNOME 50.6 Wayland GTK scratch field received a Unicode native commit
  with identical clipboard contents before and after. The existing service
  started with auto output, healthy keyboard monitoring, and the cached local
  Phonon-2 CPU model. Physical speech/hotkey, logout/reboot, and system-activated
  rebuild checks remain manual; this desktop test supplied known text directly.
- The user confirmed normal keyboard typing and Right Ctrl dictation with Phonon
  selected on GNOME, with `Output: IBus` in the service log. The full application
  compatibility matrix and remaining manual
  focus/lifecycle scenarios are still tracked in [#2].
- On the affected Logitech setup, initial discovery took approximately 1.43
  seconds; subsequent cached scans took 0.12–0.50 milliseconds with no device
  reopens. A user-tested 33-second recording completed without input-loss
  messages or premature cancellation. These results do not establish all
  hardware or lifecycle scenarios.

[#1]: https://github.com/tidley/phonon-wayland-dictation/issues/1
[#2]: https://github.com/tidley/phonon-wayland-dictation/issues/2
