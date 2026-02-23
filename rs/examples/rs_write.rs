//! Write repos from fixtures.json so Python/TypeScript can read them.
//! Usage: cargo run --manifest-path rs/Cargo.toml --example rs_write -- <fixtures.json> <output_dir>

use std::collections::HashMap;
use std::path::PathBuf;

use base64::Engine;
use serde::Deserialize;

use gitstore::fs::BatchOptions;
use gitstore::{GitStore, OpenOptions, MODE_BLOB_EXEC};

#[derive(Deserialize)]
struct Fixture {
    branch: Option<String>,
    #[serde(default)]
    files: HashMap<String, String>,
    #[serde(default)]
    symlinks: HashMap<String, String>,
    #[serde(default)]
    binary_files: HashMap<String, String>,
    #[serde(default)]
    executable_files: HashMap<String, String>,
    commits: Option<Vec<CommitStep>>,
    #[serde(default)]
    notes: HashMap<String, String>,
}

#[derive(Deserialize)]
struct CommitStep {
    message: String,
    #[serde(default)]
    files: HashMap<String, String>,
    #[serde(default)]
    removes: Vec<String>,
}

fn write_scenario(store: &GitStore, branch: &str, spec: &Fixture) {
    let fs = store.branches().get(branch).unwrap();
    let mut batch = fs.batch(Default::default());

    for (filepath, content) in &spec.files {
        batch.write(filepath, content.as_bytes()).unwrap();
    }
    for (filepath, target) in &spec.symlinks {
        batch.write_symlink(filepath, target).unwrap();
    }
    for (filepath, b64) in &spec.binary_files {
        let data = base64::engine::general_purpose::STANDARD
            .decode(b64)
            .unwrap();
        batch.write(filepath, &data).unwrap();
    }
    for (filepath, content) in &spec.executable_files {
        batch
            .write_with_mode(filepath, content.as_bytes(), MODE_BLOB_EXEC)
            .unwrap();
    }

    batch.commit().unwrap();
}

fn write_history(store: &GitStore, branch: &str, commits: &[CommitStep]) {
    for step in commits {
        let fs = store.branches().get(branch).unwrap();
        let mut batch = fs.batch(BatchOptions {
            message: Some(step.message.clone()),
        });

        for (filepath, content) in &step.files {
            batch.write(filepath, content.as_bytes()).unwrap();
        }
        for filepath in &step.removes {
            batch.remove(filepath).unwrap();
        }

        batch.commit().unwrap();
    }
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 3 {
        eprintln!("Usage: rs_write <fixtures.json> <output_dir>");
        std::process::exit(1);
    }

    let fixtures_path = &args[1];
    let output_dir = &args[2];

    let fixtures_text = std::fs::read_to_string(fixtures_path).unwrap();
    let fixtures: HashMap<String, Fixture> =
        serde_json::from_str(&fixtures_text).unwrap();

    for (name, spec) in &fixtures {
        let repo_path = PathBuf::from(output_dir).join(format!("rs_{}.git", name));
        let branch = spec.branch.as_deref().unwrap_or("main");

        let store = GitStore::open(&repo_path, OpenOptions {
            create: true,
            branch: Some(branch.to_string()),
            ..Default::default()
        })
        .unwrap();

        if let Some(commits) = &spec.commits {
            write_history(&store, branch, commits);
        } else {
            write_scenario(&store, branch, spec);
        }

        if !spec.notes.is_empty() {
            let fs = store.branches().get(branch).unwrap();
            let commit_hash = fs.commit_hash().unwrap();
            for (namespace, text) in &spec.notes {
                store
                    .notes()
                    .namespace(namespace)
                    .set(&commit_hash, text)
                    .unwrap();
            }
        }

        println!("  rs_write: {} -> {}", name, repo_path.display());
    }
}
