#!/usr/bin/env python3
"""Snapshot the current filesystem state for comparison."""

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path


def get_git_info():
    """Get current git information."""
    try:
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
        branch = subprocess.check_output(['git', 'branch', '--show-current'], text=True).strip()
        
        # Get tags
        try:
            tags = subprocess.check_output(['git', 'tag', '--points-at', 'HEAD'], text=True).strip().split('\n')
            tags = [tag for tag in tags if tag]
        except:
            tags = []
        
        return {
            "commit": commit,
            "branch": branch,
            "tags": tags
        }
    except:
        return {
            "commit": "unknown",
            "branch": "unknown", 
            "tags": []
        }


def scan_filesystem():
    """Scan the current filesystem structure."""
    root = Path(".")
    
    directories = []
    files = []
    
    for path in root.rglob("*"):
        if path.is_dir():
            if ".git" not in str(path):
                directories.append(str(path))
        elif path.is_file():
            if ".git" not in str(path):
                files.append(str(path))
    
    return sorted(directories), sorted(files)


def get_file_stats():
    """Get file count statistics."""
    root = Path(".")
    
    stats = {
        "total_files": 0,
        "python_files": 0,
        "json_files": 0,
        "markdown_files": 0,
        "html_files": 0,
        "toml_files": 0,
        "other_files": 0
    }
    
    for path in root.rglob("*"):
        if path.is_file() and ".git" not in str(path):
            stats["total_files"] += 1
            
            suffix = path.suffix.lower()
            if suffix == ".py":
                stats["python_files"] += 1
            elif suffix == ".json":
                stats["json_files"] += 1
            elif suffix == ".md":
                stats["markdown_files"] += 1
            elif suffix == ".html":
                stats["html_files"] += 1
            elif suffix == ".toml":
                stats["toml_files"] += 1
            else:
                stats["other_files"] += 1
    
    return stats


def create_snapshot():
    """Create a comprehensive filesystem snapshot."""
    git_info = get_git_info()
    directories, files = scan_filesystem()
    file_stats = get_file_stats()
    
    snapshot = {
        "snapshot_info": {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "description": "Filesystem snapshot",
            "git_commit": git_info["commit"],
            "git_branch": git_info["branch"],
            "git_tags": git_info["tags"]
        },
        "filesystem": {
            "directories": directories,
            "files": files,
            "file_counts": file_stats
        },
        "current_working_directory": str(Path.cwd()),
        "environment": {
            "python_version": f"{os.sys.version_info.major}.{os.sys.version_info.minor}.{os.sys.version_info.micro}",
            "platform": os.name
        }
    }
    
    return snapshot


def main():
    """Main function to create and save snapshot."""
    snapshot = create_snapshot()
    
    # Create snapshots directory if it doesn't exist
    snapshots_dir = Path("snapshots")
    snapshots_dir.mkdir(exist_ok=True)
    
    # Generate filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = snapshots_dir / f"filesystem_snapshot_{timestamp}.json"
    
    # Save snapshot
    with open(filename, 'w') as f:
        json.dump(snapshot, f, indent=2)
    
    print(f"Filesystem snapshot saved to: {filename}")
    print(f"Total files: {snapshot['filesystem']['file_counts']['total_files']}")
    print(f"Total directories: {len(snapshot['filesystem']['directories'])}")
    print(f"Git commit: {snapshot['snapshot_info']['git_commit'][:8]}")


if __name__ == "__main__":
    main()
