import os
import csv
import hashlib
from datetime import datetime, timedelta

# Configuration matching enterprise SharePoint Online standards
INVALID_CHARS = set('~"#%&*:<>?/{|}')
MAX_PATH_LENGTH = 250
OBSOLETE_YEARS = 5

def get_file_hash(filepath):
    """Generate MD5 hash to detect duplicate content across legacy folders."""
    hasher = hashlib.md5()
    try:
        with open(filepath, 'rb') as f:
            buf = f.read(65536)
            while len(buf) > 0:
                hasher.update(buf)
                buf = f.read(65536)
        return hasher.hexdigest()
    except Exception:
        return "ERROR_READING_FILE"

def audit_legacy_source(source_dir, output_csv):
    """
    Inventories legacy files, flags ROT (Redundant, Obsolete, Trivial),
    checks naming conventions, and assigns target SharePoint metadata.
    """
    seen_hashes = {}
    inventory = []
    cutoff_date = datetime.now() - timedelta(days=365 * OBSOLETE_YEARS)

    for root, _, files in os.walk(source_dir):
        for file in files:
            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, source_dir)
            
            try:
                stat = os.stat(full_path)
                file_size = stat.st_size
                mod_date = datetime.fromtimestamp(stat.st_mtime)
            except OSError:
                continue

            file_hash = get_file_hash(full_path)
            
            # 1. Check naming conventions & path length
            bad_chars = [c for c in file if c in INVALID_CHARS]
            clean_name = "".join("_" if c in INVALID_CHARS else c for c in file)
            path_issue = len(rel_path) > MAX_PATH_LENGTH

            # 2. ROT Analysis (Duplicate, Obsolete, Empty/Trivial)
            if file_size == 0 or file.startswith("~$"):
                migration_decision = "Skip - Trivial/Temp File"
            elif file_hash in seen_hashes:
                migration_decision = f"Skip - Duplicate of {seen_hashes[file_hash]}"
            elif mod_date < cutoff_date:
                migration_decision = "Archive - Obsolete (>5 Years)"
            else:
                seen_hashes[file_hash] = rel_path
                migration_decision = "Migrate to SharePoint Online"

            # 3. Auto-map folder structure to Modern SharePoint Metadata
            folder_parts = rel_path.split(os.sep)
            department = folder_parts[0] if len(folder_parts) > 1 else "General"
            doc_type = "Policy" if "polic" in file.lower() else (
                       "Report" if "report" in file.lower() else "Standard Operating Procedure")

            inventory.append({
                "Source_Path": rel_path,
                "Original_Name": file,
                "Cleaned_Target_Name": clean_name,
                "File_Size_Bytes": file_size,
                "Last_Modified": mod_date.strftime("%Y-%m-%d"),
                "MD5_Checksum": file_hash,
                "Naming_Violation": "Yes" if bad_chars or path_issue else "No",
                "Migration_Decision": migration_decision,
                "Target_SP_Library": "Documents",
                "Target_Metadata_Department": department,
                "Target_Metadata_DocType": doc_type
            })

    # Export to CSV for Site Owner review
    if inventory:
        with open(output_csv, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=inventory[0].keys())
            writer.writeheader()
            writer.writerows(inventory)
    return inventory

def reconcile_migration(source_inventory, target_manifest_csv, report_csv):
    """
    Validates migrated content by reconciling expected 'Migrate' items
    against a SharePoint Online target export.
    """
    expected = {
        row["Cleaned_Target_Name"]: row 
        for row in source_inventory 
        if row["Migration_Decision"] == "Migrate to SharePoint Online"
    }

    target_files = {}
    if os.path.exists(target_manifest_csv):
        with open(target_manifest_csv, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                target_files[row["Name"]] = row

    reconciliation = []
    for name, src_data in expected.items():
        if name not in target_files:
            status = "FAIL - Missing in Target"
            metadata_verified = "No"
        else:
            tgt = target_files[name]
            size_match = int(tgt.get("File_Size_Bytes", 0)) == src_data["File_Size_Bytes"]
            meta_match = (tgt.get("Department") == src_data["Target_Metadata_Department"] and 
                          tgt.get("DocType") == src_data["Target_Metadata_DocType"])
            
            if size_match and meta_match:
                status = "PASS - Verified"
                metadata_verified = "Yes"
            elif not size_match:
                status = "FAIL - File Size Mismatch"
                metadata_verified = "Partial"
            else:
                status = "WARN - Missing Required Metadata"
                metadata_verified = "No"

        reconciliation.append({
            "Target_File_Name": name,
            "Source_Path": src_data["Source_Path"],
            "Expected_Size": src_data["File_Size_Bytes"],
            "Expected_Department": src_data["Target_Metadata_Department"],
            "Expected_DocType": src_data["Target_Metadata_DocType"],
            "Metadata_Verified": metadata_verified,
            "Validation_Status": status
        })

    if reconciliation:
        with open(report_csv, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=reconciliation[0].keys())
            writer.writeheader()
            writer.writerows(reconciliation)

if __name__ == "__main__":
    # Create sample mock data to test the pipeline immediately
    os.makedirs("mock_sp2013_source/Engineering/Subsite_A/2018_Archive", exist_ok=True)
    os.makedirs("mock_sp2013_source/Quality_Assurance", exist_ok=True)

    with open("mock_sp2013_source/Engineering/CNC_Operating_Policy#1.docx", "w") as f:
        f.write("Approved manufacturing SOP content v1.2")
    with open("mock_sp2013_source/Quality_Assurance/Copy_of_CNC_Policy.docx", "w") as f:
        f.write("Approved manufacturing SOP content v1.2") # Exact duplicate
    with open("mock_sp2013_source/Engineering/Subsite_A/2018_Archive/Temp_Empty.txt", "w") as f:
        pass # 0-byte trivial file
    with open("mock_sp2013_source/Quality_Assurance/Q3_Audit_Report.xlsx", "w") as f:
        f.write("Audit metrics and defect counts 2026")

    # Simulate target SharePoint Online export
    with open("mock_spo_target_export.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Name", "File_Size_Bytes", "Department", "DocType"])
        writer.writerow(["CNC_Operating_Policy_1.docx", "39", "Engineering", "Policy"])
        writer.writerow(["Q3_Audit_Report.xlsx", "36", "Quality_Assurance", ""]) # Missing DocType metadata

    inv = audit_legacy_source("mock_sp2013_source", "1_source_inventory_audit.csv")
    reconcile_migration(inv, "mock_spo_target_export.csv", "2_post_migration_reconciliation.csv")
    print("Generated 1_source_inventory_audit.csv and 2_post_migration_reconciliation.csv successfully.")