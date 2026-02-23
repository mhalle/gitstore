//! Read repos written by another language and verify contents match fixtures.
//! Usage: cargo run --manifest-path rs/Cargo.toml --example rs_read -- <fixtures.json> <repo_dir> <prefix>

use std::collections::{HashMap, HashSet};
use std::path::PathBuf;

use base64::Engine;
use serde::Deserialize;

use gitstore::{FileType, GitStore, OpenOptions};

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
    #[allow(dead_code)]
    message: String,
    #[serde(default)]
    files: HashMap<String, String>,
    #[serde(default)]
    removes: Vec<String>,
}

fn check_basic(fs: &gitstore::Fs, spec: &Fixture, name: &str) -> u32 {
    let mut failures = 0u32;

    // Text files
    for (filepath, expected) in &spec.files {
        match fs.read_text(filepath) {
            Ok(ref actual) if actual == expected => {
                println!("  OK   {}: {}", name, filepath);
            }
            Ok(ref actual) => {
                println!(
                    "  FAIL {}: {} content expected {:?}, got {:?}",
                    name, filepath, expected, actual
                );
                failures += 1;
            }
            Err(e) => {
                println!("  FAIL {}: {} error: {}", name, filepath, e);
                failures += 1;
            }
        }
    }

    // Symlinks
    for (filepath, expected_target) in &spec.symlinks {
        match fs.readlink(filepath) {
            Ok(ref actual) if actual == expected_target => {
                println!("  OK   {}: symlink {} -> {}", name, filepath, actual);
            }
            Ok(ref actual) => {
                println!(
                    "  FAIL {}: {} link target expected {:?}, got {:?}",
                    name, filepath, expected_target, actual
                );
                failures += 1;
            }
            Err(e) => {
                println!("  FAIL {}: {} error: {}", name, filepath, e);
                failures += 1;
            }
        }
    }

    // Binary files
    for (filepath, b64) in &spec.binary_files {
        let expected_bytes = base64::engine::general_purpose::STANDARD
            .decode(b64)
            .unwrap();
        match fs.read(filepath) {
            Ok(ref actual) if *actual == expected_bytes => {
                println!(
                    "  OK   {}: binary {} ({} bytes)",
                    name,
                    filepath,
                    actual.len()
                );
            }
            Ok(_) => {
                println!("  FAIL {}: {} binary content mismatch", name, filepath);
                failures += 1;
            }
            Err(e) => {
                println!("  FAIL {}: {} error: {}", name, filepath, e);
                failures += 1;
            }
        }
    }

    // Executable files
    for (filepath, expected) in &spec.executable_files {
        match fs.read_text(filepath) {
            Ok(ref actual) if actual != expected => {
                println!(
                    "  FAIL {}: {} content expected {:?}, got {:?}",
                    name, filepath, expected, actual
                );
                failures += 1;
                continue;
            }
            Err(e) => {
                println!("  FAIL {}: {} error: {}", name, filepath, e);
                failures += 1;
                continue;
            }
            _ => {}
        }
        // Check mode via walk
        match fs.walk("") {
            Ok(entries) => {
                let mut found = false;
                for (path, entry) in &entries {
                    if path == filepath {
                        if FileType::from_mode(entry.mode)
                            != Some(FileType::Executable)
                        {
                            println!(
                                "  FAIL {}: {} expected EXECUTABLE, got mode {:#o}",
                                name, filepath, entry.mode
                            );
                            failures += 1;
                        } else {
                            println!("  OK   {}: executable {}", name, filepath);
                        }
                        found = true;
                        break;
                    }
                }
                if !found {
                    println!(
                        "  FAIL {}: {} not found in walk",
                        name, filepath
                    );
                    failures += 1;
                }
            }
            Err(e) => {
                println!("  FAIL {}: walk error: {}", name, e);
                failures += 1;
            }
        }
    }

    // Verify file count
    let mut all_files = HashSet::new();
    if let Ok(entries) = fs.walk("") {
        for (path, _entry) in entries {
            all_files.insert(path);
        }
    }

    let mut expected_files = HashSet::new();
    expected_files.extend(spec.files.keys().cloned());
    expected_files.extend(spec.symlinks.keys().cloned());
    expected_files.extend(spec.binary_files.keys().cloned());
    expected_files.extend(spec.executable_files.keys().cloned());

    let extra: Vec<_> = all_files.difference(&expected_files).collect();
    let missing: Vec<_> = expected_files.difference(&all_files).collect();

    if !extra.is_empty() {
        println!("  FAIL {}: unexpected files {:?}", name, extra);
        failures += 1;
    }
    if !missing.is_empty() {
        println!("  FAIL {}: missing files {:?}", name, missing);
        failures += 1;
    }

    failures
}

fn check_history(
    store: &GitStore,
    branch: &str,
    spec: &Fixture,
    name: &str,
) -> u32 {
    let mut failures = 0u32;
    let commits = spec.commits.as_ref().unwrap();

    let fs = store.branches().get(branch).unwrap();

    // Final state: last commit
    let last = &commits[commits.len() - 1];
    for (filepath, expected) in &last.files {
        match fs.read_text(filepath) {
            Ok(ref actual) if actual == expected => {
                println!("  OK   {}: HEAD {}", name, filepath);
            }
            Ok(ref actual) => {
                println!(
                    "  FAIL {}: HEAD {} expected {:?}, got {:?}",
                    name, filepath, expected, actual
                );
                failures += 1;
            }
            Err(e) => {
                println!("  FAIL {}: HEAD {} error: {}", name, filepath, e);
                failures += 1;
            }
        }
    }

    // Removed files should not exist
    for filepath in &last.removes {
        match fs.exists(filepath) {
            Ok(true) => {
                println!(
                    "  FAIL {}: {} should have been removed",
                    name, filepath
                );
                failures += 1;
            }
            Ok(false) => {
                println!("  OK   {}: {} removed", name, filepath);
            }
            Err(e) => {
                println!("  FAIL {}: {} error: {}", name, filepath, e);
                failures += 1;
            }
        }
    }

    // Walk back through history
    let num_commits = commits.len();
    match fs.back(num_commits - 1) {
        Ok(back_fs) => {
            let first = &commits[0];
            for (filepath, expected) in &first.files {
                match back_fs.read_text(filepath) {
                    Ok(ref actual) if actual == expected => {
                        println!("  OK   {}: commit[0] {}", name, filepath);
                    }
                    Ok(ref actual) => {
                        println!(
                            "  FAIL {}: commit[0] {} expected {:?}, got {:?}",
                            name, filepath, expected, actual
                        );
                        failures += 1;
                    }
                    Err(e) => {
                        println!(
                            "  FAIL {}: commit[0] {} error: {}",
                            name, filepath, e
                        );
                        failures += 1;
                    }
                }
            }
        }
        Err(e) => {
            println!(
                "  FAIL {}: back({}) error: {}",
                name,
                num_commits - 1,
                e
            );
            failures += 1;
        }
    }

    // Count commits by walking parents
    let mut count = 0u32;
    let mut current = fs;
    loop {
        count += 1;
        match current.parent() {
            Ok(Some(parent)) => current = parent,
            Ok(None) | Err(_) => break,
        }
    }

    // +1 for the initial empty commit created by GitStore.open
    let expected_count = (num_commits + 1) as u32;
    if count != expected_count {
        println!(
            "  FAIL {}: expected {} commits, found {}",
            name, expected_count, count
        );
        failures += 1;
    } else {
        println!("  OK   {}: {} commits in history", name, count);
    }

    failures
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 4 {
        eprintln!("Usage: rs_read <fixtures.json> <repo_dir> <prefix>");
        std::process::exit(1);
    }

    let fixtures_path = &args[1];
    let repo_dir = &args[2];
    let prefix = &args[3];

    let fixtures_text = std::fs::read_to_string(fixtures_path).unwrap();
    let fixtures: HashMap<String, Fixture> =
        serde_json::from_str(&fixtures_text).unwrap();

    let mut failures = 0u32;

    for (name, spec) in &fixtures {
        let repo_path =
            PathBuf::from(repo_dir).join(format!("{}_{}.git", prefix, name));
        let branch = spec.branch.as_deref().unwrap_or("main");

        if !repo_path.exists() {
            println!(
                "  FAIL {}: repo not found at {}",
                name,
                repo_path.display()
            );
            failures += 1;
            continue;
        }

        let store = GitStore::open(&repo_path, OpenOptions {
            create: false,
            ..Default::default()
        })
        .unwrap();

        if spec.commits.is_some() {
            failures += check_history(&store, branch, spec, name);
        } else {
            let fs = store.branches().get(branch).unwrap();
            failures += check_basic(&fs, spec, name);
        }

        if !spec.notes.is_empty() {
            let fs = store.branches().get(branch).unwrap();
            let commit_hash = fs.commit_hash().unwrap();
            for (namespace, expected_text) in &spec.notes {
                match store.notes().namespace(namespace).get(&commit_hash) {
                    Ok(ref actual) if actual == expected_text => {
                        println!("  OK   {}: notes[{}]", name, namespace);
                    }
                    Ok(ref actual) => {
                        println!(
                            "  FAIL {}: notes[{}] expected {:?}, got {:?}",
                            name, namespace, expected_text, actual
                        );
                        failures += 1;
                    }
                    Err(_) => {
                        println!(
                            "  FAIL {}: notes[{}] not found for {}",
                            name, namespace, commit_hash
                        );
                        failures += 1;
                    }
                }
            }
        }
    }

    if failures > 0 {
        println!("\n{} failure(s)", failures);
        std::process::exit(1);
    } else {
        println!("\nAll checks passed");
    }
}
