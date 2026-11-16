//! Compose/dead-key and Ctrl+Shift+U input while ordinary keys pass through.
use std::{collections::HashSet, ffi::OsStr};
use xkbcommon::xkb::{self, compose};

pub struct Typing {
    compose: compose::State,
    unicode: Option<String>,
    consumed: HashSet<u32>,
}

// The native state has unique ownership, exposes no pointers, and is accessed
// only through Engine's Mutex. libxkbcommon state may move between threads but
// must never be accessed concurrently.
unsafe impl Send for Typing {}

impl Typing {
    pub fn new() -> anyhow::Result<Self> {
        let context = xkb::Context::new(xkb::CONTEXT_NO_FLAGS);
        let locale = ["LC_ALL", "LC_CTYPE", "LANG"]
            .iter()
            .find_map(|key| std::env::var(key).ok().filter(|value| !value.is_empty()))
            .unwrap_or_else(|| "C.UTF-8".into());
        let table = compose::Table::new_from_locale(
            &context,
            OsStr::new(&locale),
            compose::COMPILE_NO_FLAGS,
        )
        .map_err(|_| anyhow::anyhow!("Cannot load Compose table for {locale}"))?;
        Ok(Self {
            compose: compose::State::new(&table, compose::STATE_NO_FLAGS),
            unicode: None,
            consumed: HashSet::new(),
        })
    }

    pub fn reset(&mut self) {
        self.compose.reset();
        self.unicode = None;
        // Retain consumed press codes until their releases arrive.
    }

    pub fn leave(&mut self) {
        self.reset();
        self.consumed.clear();
    }

    pub fn process(&mut self, key: u32, code: u32, modifiers: u32) -> (bool, Option<String>) {
        if modifiers & (1 << 30) != 0 {
            return (self.consumed.remove(&code), None);
        }
        if (0xffe1..=0xffee).contains(&key) {
            return (false, None);
        }
        let mut output = None;
        let handled;
        if let Some(buffer) = self.unicode.as_mut() {
            match key {
                0xff0d | 0x20 => {
                    output = u32::from_str_radix(buffer, 16)
                        .ok()
                        .and_then(char::from_u32)
                        .filter(|value| *value != '\0')
                        .map(|value| value.to_string());
                    self.unicode = None;
                }
                0xff1b => self.unicode = None,
                0xff08 => {
                    buffer.pop();
                }
                _ => {
                    if let Some(value) =
                        char::from_u32(key).filter(|value| value.is_ascii_hexdigit())
                    {
                        if buffer.len() < 6 {
                            buffer.push(value);
                        }
                    }
                }
            }
            handled = true;
        } else if (key == b'u' as u32 || key == b'U' as u32) && modifiers & 5 == 5 {
            self.compose.reset();
            self.unicode = Some(String::new());
            handled = true;
        } else if modifiers & ((1 << 2) | (1 << 3) | (1 << 6) | (1 << 26)) != 0 {
            self.reset();
            handled = false;
        } else if self.compose.feed(xkb::Keysym::new(key)) == compose::FeedResult::Ignored {
            handled = false;
        } else {
            match self.compose.status() {
                compose::Status::Nothing => handled = false,
                compose::Status::Composing => handled = true,
                compose::Status::Composed => {
                    output = self.compose.utf8();
                    self.compose.reset();
                    handled = true;
                }
                compose::Status::Cancelled => {
                    self.compose.reset();
                    handled = true;
                }
            }
        }
        if handled {
            self.consumed.insert(code);
        }
        (handled, output)
    }
}
