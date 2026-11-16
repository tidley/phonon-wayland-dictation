# Changelog

## Unreleased

### Added

- Optional Rust IBus input source with per-user GNOME installation, native text
  insertion, Compose/dead-key and Unicode entry, runtime-socket IPC, focus tokens,
  and request deduplication ([#2]). The installer preserves other input sources
  and can enable automatic IBus/clipboard routing. Without that configuration,
  clipboard output remains the application default.
- Isolated tests for installed-engine discovery/activation, native IPC, stale
  results, duplicate requests, normal typing, rapid commits, and helper restart.

### Fixed

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

- 64 automated Python tests cover input recovery, recording ownership, mirrored events,
  input during transcription and paste, device-cache invalidation, hotplug,
  permission retries, suspend/resume handling, native-output routing/failures,
  and installer configuration preservation.
- Both real-IBus integration modes pass against an isolated daemon, including
  staged installation/activation and helper restart. Rust release build, Clippy,
  and formatting checks pass.
- The user confirmed normal keyboard typing and Right Ctrl dictation with Phonon
  selected on GNOME, with `Output: IBus` in the service log. The full application
  compatibility matrix, clipboard-preservation observation, and remaining manual
  focus/lifecycle scenarios are still tracked in [#2].
- On the affected Logitech setup, initial discovery took approximately 1.43
  seconds; subsequent cached scans took 0.12–0.50 milliseconds with no device
  reopens. A user-tested 33-second recording completed without input-loss
  messages or premature cancellation. These results do not establish all
  hardware or lifecycle scenarios.

[#1]: https://github.com/tidley/phonon-wayland-dictation/issues/1
[#2]: https://github.com/tidley/phonon-wayland-dictation/issues/2
