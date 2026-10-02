"""
save_history.py - Save Version History & Rollback System for Resume Previews.
Enables multi-level Undo & Redo for saved resume documents, preventing data loss.
"""
import os
import json
import time
from pathlib import Path
from datetime import datetime

MAX_HISTORY_SNAPSHOTS = 25


def _get_history_dir(target_dir: Path) -> Path:
    hdir = target_dir / ".history"
    hdir.mkdir(parents=True, exist_ok=True)
    return hdir


def _get_manifest_path(target_dir: Path) -> Path:
    return _get_history_dir(target_dir) / "manifest.json"


def _load_manifest(target_dir: Path) -> dict:
    mpath = _get_manifest_path(target_dir)
    if mpath.exists():
        try:
            with open(mpath, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    data.setdefault("history", [])
                    data.setdefault("redo", [])
                    return data
        except Exception as e:
            print(f"[SaveHistory] Error reading manifest: {e}")
    return {"history": [], "redo": []}


def _save_manifest(target_dir: Path, data: dict):
    mpath = _get_manifest_path(target_dir)
    try:
        with open(mpath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[SaveHistory] Error writing manifest: {e}")


def record_pre_save_snapshot(
    target_dir: Path,
    json_filename: str = "tailored_resume.json",
    is_initial: bool = False,
    label: str = "",
    summary: str = ""
):
    """
    Snapshots the existing file on disk BEFORE a new save overwrites it.
    If no history exists, records the disk file as the 'Original / Baseline' version.
    """
    source_file = target_dir / json_filename
    if not source_file.exists():
        return None

    try:
        with open(source_file, "r", encoding="utf-8") as f:
            existing_data = json.load(f)
    except Exception as e:
        print(f"[SaveHistory] Could not read source for snapshot: {e}")
        return None

    hdir = _get_history_dir(target_dir)
    manifest = _load_manifest(target_dir)

    ts = int(time.time() * 1000)
    iso_time = datetime.now().strftime("%I:%M %p")
    vid = f"v_{ts}"
    snapshot_filename = f"{json_filename.replace('.json', '')}_{vid}.json"
    snapshot_file = hdir / snapshot_filename

    with open(snapshot_file, "w", encoding="utf-8") as f:
        json.dump(existing_data, f, indent=2, ensure_ascii=False)

    is_first = (len(manifest.get("history", [])) == 0)
    if not label:
        if is_initial or is_first:
            label = "Original Generated Resume"
        else:
            save_num = len(manifest.get("history", [])) + 1
            label = f"Saved Version #{save_num} ({iso_time})"

    entry = {
        "id": vid,
        "timestamp": datetime.now().isoformat(),
        "display_time": iso_time,
        "label": label,
        "summary": summary or label,
        "filename": snapshot_filename,
        "is_initial": is_initial or is_first
    }

    manifest.setdefault("history", []).append(entry)
    manifest["redo"] = []  # new explicit save clears future redo branch

    # Limit to MAX_HISTORY_SNAPSHOTS
    history = manifest["history"]
    if len(history) > MAX_HISTORY_SNAPSHOTS:
        # Preserve index 0 if it was marked as initial
        del_idx = 1 if (len(history) > 2 and history[0].get("is_initial")) else 0
        removed = history.pop(del_idx)
        old_snap = hdir / removed.get("filename", "")
        if old_snap.exists():
            try:
                old_snap.unlink()
            except Exception:
                pass

    _save_manifest(target_dir, manifest)
    return entry


def undo_last_save(target_dir: Path, json_filename: str = "tailored_resume.json"):
    """
    Rolls back to the previous saved snapshot.
    Preserves the current file to the redo stack.
    Returns: (restored_data_dict, restored_label, can_undo, can_redo) or None
    """
    hdir = _get_history_dir(target_dir)
    manifest = _load_manifest(target_dir)
    history = manifest.get("history", [])

    if not history:
        return None

    current_file = target_dir / json_filename
    current_data = None
    if current_file.exists():
        try:
            with open(current_file, "r", encoding="utf-8") as f:
                current_data = json.load(f)
        except Exception:
            pass

    target_entry = history.pop()

    # Push current version to redo stack
    if current_data:
        ts = int(time.time() * 1000)
        redo_name = f"redo_{ts}.json"
        with open(hdir / redo_name, "w", encoding="utf-8") as f:
            json.dump(current_data, f, indent=2, ensure_ascii=False)
        manifest.setdefault("redo", []).append({
            "id": f"redo_{ts}",
            "timestamp": datetime.now().isoformat(),
            "display_time": datetime.now().strftime("%I:%M %p"),
            "filename": redo_name,
            "label": "Undone Save"
        })

    # Read historical target
    snap_path = hdir / target_entry.get("filename", "")
    if not snap_path.exists():
        _save_manifest(target_dir, manifest)
        return None

    try:
        with open(snap_path, "r", encoding="utf-8") as f:
            restored_data = json.load(f)
    except Exception as e:
        print(f"[SaveHistory] Error restoring snapshot {snap_path}: {e}")
        return None

    # Write restored data onto current file
    with open(current_file, "w", encoding="utf-8") as f:
        json.dump(restored_data, f, indent=2, ensure_ascii=False)

    _save_manifest(target_dir, manifest)
    can_undo = len(manifest["history"]) > 0
    can_redo = len(manifest.get("redo", [])) > 0
    return restored_data, target_entry.get("label", "Previous Version"), can_undo, can_redo


def redo_last_save(target_dir: Path, json_filename: str = "tailored_resume.json"):
    """
    Reapplies an undone save from the redo stack.
    Returns: (redo_data_dict, redo_label, can_undo, can_redo) or None
    """
    hdir = _get_history_dir(target_dir)
    manifest = _load_manifest(target_dir)
    redo_stack = manifest.get("redo", [])

    if not redo_stack:
        return None

    target_redo = redo_stack.pop()
    current_file = target_dir / json_filename

    # Read target redo data
    snap_path = hdir / target_redo.get("filename", "")
    if not snap_path.exists():
        _save_manifest(target_dir, manifest)
        return None

    try:
        with open(snap_path, "r", encoding="utf-8") as f:
            redo_data = json.load(f)
    except Exception as e:
        print(f"[SaveHistory] Error reading redo file: {e}")
        return None

    # Save current file to history before writing redo
    if current_file.exists():
        try:
            with open(current_file, "r", encoding="utf-8") as f:
                cur = json.load(f)
            ts = int(time.time() * 1000)
            hist_name = f"hist_{ts}.json"
            with open(hdir / hist_name, "w", encoding="utf-8") as f:
                json.dump(cur, f, indent=2, ensure_ascii=False)
            manifest.setdefault("history", []).append({
                "id": f"hist_{ts}",
                "timestamp": datetime.now().isoformat(),
                "display_time": datetime.now().strftime("%I:%M %p"),
                "filename": hist_name,
                "label": "Version prior to Redo",
                "summary": "State prior to redo"
            })
        except Exception:
            pass

    # Overwrite current file with redo data
    with open(current_file, "w", encoding="utf-8") as f:
        json.dump(redo_data, f, indent=2, ensure_ascii=False)

    _save_manifest(target_dir, manifest)
    can_undo = len(manifest.get("history", [])) > 0
    can_redo = len(manifest.get("redo", [])) > 0
    return redo_data, "Redone Save", can_undo, can_redo


def restore_specific_version(target_dir: Path, version_id: str, json_filename: str = "tailored_resume.json"):
    """
    Restores an exact version from the manifest history by version_id.
    """
    hdir = _get_history_dir(target_dir)
    manifest = _load_manifest(target_dir)
    history = manifest.get("history", [])

    matched = None
    matched_idx = -1
    for idx, entry in enumerate(history):
        if entry.get("id") == version_id:
            matched = entry
            matched_idx = idx
            break

    if not matched:
        return None

    snap_path = hdir / matched.get("filename", "")
    if not snap_path.exists():
        return None

    try:
        with open(snap_path, "r", encoding="utf-8") as f:
            restored_data = json.load(f)
    except Exception as e:
        print(f"[SaveHistory] Could not read target version: {e}")
        return None

    current_file = target_dir / json_filename
    # Snapshot current to history before jumping
    if current_file.exists():
        try:
            with open(current_file, "r", encoding="utf-8") as f:
                cur = json.load(f)
            ts = int(time.time() * 1000)
            hist_name = f"hist_{ts}.json"
            with open(hdir / hist_name, "w", encoding="utf-8") as f:
                json.dump(cur, f, indent=2, ensure_ascii=False)
            manifest.setdefault("history", []).append({
                "id": f"hist_{ts}",
                "timestamp": datetime.now().isoformat(),
                "display_time": datetime.now().strftime("%I:%M %p"),
                "filename": hist_name,
                "label": "Version before Rollback",
                "summary": "Auto-saved before restoring previous version"
            })
        except Exception:
            pass

    with open(current_file, "w", encoding="utf-8") as f:
        json.dump(restored_data, f, indent=2, ensure_ascii=False)

    _save_manifest(target_dir, manifest)
    return restored_data, matched.get("label", "Selected Version"), True, False


def get_history_summary(target_dir: Path):
    """
    Returns available history versions for UI display.
    """
    manifest = _load_manifest(target_dir)
    history = list(manifest.get("history", []))
    redo = list(manifest.get("redo", []))

    # Return newest first for dropdown
    reversed_history = list(reversed(history))

    return {
        "success": True,
        "history": reversed_history,
        "can_undo": len(history) > 0,
        "can_redo": len(redo) > 0,
        "latest_undo_label": history[-1].get("label") if history else "",
        "latest_redo_label": redo[-1].get("label") if redo else ""
    }
