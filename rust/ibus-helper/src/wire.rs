//! IBus serializables are variant-wrapped structs, not plain D-Bus strings.
use std::collections::HashMap;
use zbus::zvariant::{OwnedValue, StructureBuilder, Value};

fn serializable(name: &'static str) -> StructureBuilder<'static> {
    StructureBuilder::new()
        .add_field(name)
        .add_field(HashMap::<String, Value<'static>>::new())
}

fn variant(builder: StructureBuilder<'_>) -> zbus::zvariant::Result<OwnedValue> {
    Value::from(builder.build()?).try_into()
}

pub fn text(text: &str) -> zbus::zvariant::Result<OwnedValue> {
    let attributes = variant(serializable("IBusAttrList").add_field(Vec::<OwnedValue>::new()))?;
    variant(
        serializable("IBusText")
            .add_field(text.to_owned())
            .add_field(attributes),
    )
}

pub fn component() -> zbus::zvariant::Result<OwnedValue> {
    let engine = variant(
        serializable("IBusEngineDesc")
            .add_field("phonon")
            .add_field("Phonon Dictation (English, UK)")
            .add_field("Native offline dictation")
            .add_field("en")
            .add_field("MIT")
            .add_field("Phonon contributors")
            .add_field("") // icon
            .add_field("gb")
            .add_field(0u32) // rank: do not auto-select
            .add_field("") // hotkeys
            .add_field("Ph") // symbol
            .add_field("") // setup
            .add_field("") // layout variant
            .add_field("") // layout option
            .add_field("1.0") // version
            .add_field("") // text domain
            .add_field(""), // icon property key
    )?;
    variant(
        serializable("IBusComponent")
            .add_field("org.freedesktop.IBus.Phonon")
            .add_field("Phonon IBus engine")
            .add_field("0.1.0")
            .add_field("MIT")
            .add_field("Phonon contributors")
            .add_field("") // homepage
            .add_field("") // exec: explicit prototype startup only
            .add_field("") // text domain
            .add_field(Vec::<OwnedValue>::new()) // observed paths
            .add_field(vec![engine]),
    )
}
