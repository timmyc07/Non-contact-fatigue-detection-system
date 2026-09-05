fn main() {
    let manifest_dir = std::path::PathBuf::from(
        std::env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR is required"),
    );
    std::fs::create_dir_all(manifest_dir.join("../dist/ncfd-engine"))
        .expect("failed to create the generated engine resource directory");
    tauri_build::build()
}
