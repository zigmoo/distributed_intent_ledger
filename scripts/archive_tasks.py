#!/usr/bin/env python3
import os
import sys
import shutil
import re
from datetime import datetime, timedelta

# archive_tasks.py
# DIL Protocol: Automates the archiving of completed/cancelled tasks.

BASE = os.environ.get("DIL_BASE", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INDEX_PATH = os.path.join(BASE, "_shared/_meta/task_index.md")
ARCHIVE_DIR = os.path.join(BASE, "_shared/tasks/_archive")
THRESHOLD_DAYS = 30

def get_task_rows():
    if not os.path.exists(INDEX_PATH):
        print(f"Error: Index not found at {INDEX_PATH}")
        sys.path(1)
    with open(INDEX_PATH, 'r') as f:
        return f.readlines()

def archive_tasks(days=THRESHOLD_DAYS, dry_run=False):
    rows = get_task_rows()
    new_rows = []
    archived_count = 0
    now = datetime.utcnow()
    cutoff = now - timedelta(days=days)

    if not os.path.exists(ARCHIVE_DIR):
        os.makedirs(ARCHIVE_DIR)

    # Header and separator logic
    header_count = 0
    for row in rows:
        if row.strip().startswith('|') and 'task_id' not in row.lower() and '---' not in row:
            parts = [p.strip() for p in row.split('|')]
            if len(parts) < 10:
                new_rows.append(row)
                continue
            
            task_id = parts[1]
            status = parts[3].lower()
            update_date_str = parts[9]
            task_path_rel = parts[8]

            try:
                update_date = datetime.strptime(update_date_str, "%Y-%m-%d")
            except ValueError:
                new_rows.append(row)
                continue

            if status in ['done', 'cancelled'] and update_date < cutoff:
                # ARCHIVE IT
                src_path = os.path.join(BASE, task_path_rel)
                filename = os.path.basename(src_path)
                dest_path = os.path.join(ARCHIVE_DIR, filename)

                print(f"Archiving {task_id} (Updated: {update_date_str})")
                if not dry_run:
                    if os.path.exists(src_path):
                        shutil.move(src_path, dest_path)
                    archived_count += 1
                else:
                    print(f"  [DRY RUN] Would move {src_path} -> {dest_path}")
                    archived_count += 1
            else:
                new_rows.append(row)
        else:
            new_rows.append(row)

    if not dry_run and archived_count > 0:
        with open(INDEX_PATH, 'w') as f:
            f.writelines(new_rows)
        print(f"Successfully archived {archived_count} tasks and updated index.")
    elif archived_count == 0:
        print("No tasks eligible for archiving.")
    else:
        print(f"[DRY RUN] Would have archived {archived_count} tasks.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Archive old DIL tasks.")
    parser.add_argument("--days", type=int, default=THRESHOLD_DAYS, help="Age threshold in days (default: 30)")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without executing")
    args = parser.parse_args()

    archive_tasks(days=args.days, dry_run=args.dry_run)
