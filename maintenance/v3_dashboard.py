"""Operator-controlled V3 pilot maintenance dashboard (read-only by default).

All stage/recover/rollback operations affect only the V3 local version store.
No Scheduled Tasks, REG services, ArcGIS Pro add-ins or live watcher files are touched.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
import zipfile

if not __package__:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from maintenance import self_monitor
from maintenance.v3_core import Manager, REPO, TAG_PATTERN, atomic_json, read_json
from maintenance.v3_office_diagnostics import inspect_office

LOCAL = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "REPORTAPP" / "Maintenance" / "v3"


class Dashboard:
    def __init__(self, root):
        self.root = root
        root.title("REPORTAPP — Self-Maintenance V3 (Pilot)")
        root.geometry("760x550")
        self.manager = Manager(LOCAL)
        self.busy = False
        wrapper = ttk.Frame(root, padding=16)
        wrapper.pack(fill="both", expand=True)
        ttk.Label(wrapper, text="REPORTAPP Maintenance V3", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(
            wrapper,
            text="Pilot only • no automatic update of the working watcher, ArcGIS project or add-in.",
            foreground="#8a5900",
        ).pack(anchor="w", pady=(4, 12))
        row = ttk.Frame(wrapper)
        row.pack(fill="x", pady=(0, 10))
        for name, fn in (
            ("Refresh Health", self.refresh),
            ("Review & Stage ZIP", self.stage_package),
            ("Recover Interrupted Switch", self.recover),
            ("Rollback V3 Pointer", self.rollback),
        ):
            ttk.Button(row, text=name, command=fn).pack(side="left", padx=(0, 6))
        ttk.Button(wrapper, text="Save Sanitized Office Diagnostic (JSON)",
                   command=self.export_diagnostic).pack(anchor="w", pady=(0, 8))
        self.overview = tk.Text(wrapper, wrap="word", height=22, font=("Consolas", 10))
        self.overview.pack(fill="both", expand=True)
        self.overview.configure(state="disabled")
        self.message = tk.StringVar(value="Read-only inspection; V2 remains in service.")
        ttk.Label(wrapper, textvariable=self.message).pack(anchor="w", pady=(10, 0))
        self.refresh()

    def _display(self, content):
        self.overview.configure(state="normal")
        self.overview.delete("1.0", "end")
        self.overview.insert("1.0", content)
        self.overview.configure(state="disabled")

    def _job(self, label, fn, done=None, refresh_after=True):
        if self.busy:
            messagebox.showwarning("Maintenance busy", "Wait for the current task to finish.")
            return
        self.busy = True
        self.message.set(label)
        def background():
            try:
                result = fn()
                def succeeded():
                    self.busy = False
                    self.message.set("Completed: " + label)
                    if done:
                        done(result)
                    if refresh_after:
                        self.refresh()
                self.root.after(0, succeeded)
            except Exception as exc:
                desc = f"{type(exc).__name__}: {str(exc).splitlines()[0][:280]}"
                def failed():
                    self.busy = False
                    self.message.set("Failed safely: " + label)
                    messagebox.showerror("V3 safety check stopped", desc)
                    self.refresh()
                self.root.after(0, failed)
        threading.Thread(target=background, daemon=True).start()

    def refresh(self):
        if self.busy:
            return
        self._job("Checking local maintenance health", self._get_health,
                  self._show_health, refresh_after=False)

    def _get_health(self):
        legacy = self_monitor.collect_health()
        v3 = self.manager.status()
        failures = []
        for tag in v3["blocked"][-4:]:
            report = read_json(self.manager.local / "diagnostics" / (tag + ".json"), {})
            failures.append({key: report.get(key) for key in
                             ("tag", "stage", "code", "details", "rollback")})
        office = inspect_office(self.manager.local.parent)
        return legacy, v3, failures, office

    def _show_health(self, data):
        legacy, v3, failures, office = data
        content = [
            "CURRENT WATCHER (V2 — UNCHANGED)",
            "  State: " + str(legacy.get("status")),
            "  Scheduled Task: " + str(legacy.get("watcher_task_state")),
            "  Last scan age: " + str(legacy.get("scan_age_minutes")) + " minutes",
            "  Failed deliveries: " + str(legacy.get("delivery_failures_last_scan")),
            "  Issues: " + ", ".join(legacy.get("issues") or ["none"]),
            "",
            "V2 DEPLOYMENT — OFFICE RECEIPTS",
            "  Latest deployment: " + str(office["legacy_maintenance"]["deployment"]),
            "  Last installed tag: " + str(office["legacy_maintenance"]["installed_tag"]),
            "  Updated files: " + ", ".join(office["legacy_maintenance"]["installed_component_files"]),
            "  Backup found: " + str(office["legacy_maintenance"]["backup_folder_present"]),
            "  Blocked releases: " + str(len(office["blocked_releases"])),
            "  Diagnosis: " + ", ".join(office["diagnostic_codes"]),
            "",
            "V3 PILOT (SEPARATE STORE)",
            "  Agent: " + v3["agent_version"],
            "  Active V3 pointer: " + str(v3["active"]),
            "  Last V3 deployment: " + str(v3["latest_deployment"]),
            "  Interrupted deployment: " + str(v3["incomplete_transaction"]),
            "  Blocked V3 releases: " + str(len(v3["blocked"])),
            "  V3 version folder: " + str(self.manager.versions),
            "",
            "LAST BLOCKED RELEASE DETAILS",
        ]
        if not failures:
            content.append("  None")
        for item in failures:
            content.extend("  " + k + ": " + str(v) for k, v in item.items())
        content.extend([
            "",
            "CUTOVER STATUS",
            "  V3 does not alter the operating Windows watcher task.",
            "  Activation requires office source/runtime and add-in verification.",
            "  Excel/KMZ rollout remains separate and is NOT installed here.",
        ])
        self._display("\n".join(content))

    def export_diagnostic(self):
        """Save only whitelisted local status codes, never a raw log or secret."""
        if self.busy:
            return
        destination = filedialog.asksaveasfilename(
            title="Save safe local REPORTAPP diagnostics",
            initialfile="reportapp-office-diagnostic.json",
            defaultextension=".json",
            filetypes=[("JSON diagnostic", "*.json")],
            parent=self.root,
        )
        if not destination:
            return
        try:
            report = inspect_office(self.manager.local.parent)
            with Path(destination).open("x", encoding="utf-8") as file:
                json.dump(report, file, indent=2)
        except FileExistsError:
            messagebox.showerror("Existing file protected",
                                 "Choose a new filename. Existing files are never overwritten.")
        except (OSError, ValueError) as exc:
            messagebox.showerror("Export failed", type(exc).__name__)
        else:
            messagebox.showinfo("Safe diagnostic saved",
                                "Review the JSON before sharing. No upload was performed.")

    def stage_package(self):
        if self.busy:
            return
        file = filedialog.askopenfilename(
            title="Select an independently reviewed V3 release",
            filetypes=[("V3 signed-off archive", "*.zip")],
        )
        if not file:
            return
        archive = Path(file).read_bytes()
        try:
            with zipfile.ZipFile(file) as z:
                meta = json.loads(z.read("manifest.json"))
            tag = str(meta.get("tag", ""))
            if not TAG_PATTERN.fullmatch(tag):
                raise ValueError("Not a V3 release")
        except Exception:
            messagebox.showerror("Package rejected", "V3 archive has no valid release manifest.")
            return
        actual_hash = hashlib.sha256(archive).hexdigest()
        typed_tag = simpledialog.askstring(
            "Confirm GitHub approval", f"Archive claims {tag}.\n"
            "Type the exact APPROVED tag from a reviewed GitHub release:",
            parent=self.root,
        )
        if typed_tag != tag:
            messagebox.showwarning("Not approved", "Release tag was not independently confirmed.")
            return
        expected_hash = simpledialog.askstring(
            "Verify release SHA256",
            "Enter the expected 64-character SHA256 from a trusted approval "
            "record (NOT copied from this ZIP's manifest):",
            parent=self.root,
        )
        if expected_hash is None or expected_hash.strip().lower() != actual_hash:
            messagebox.showerror("Integrity check failed", "Approved SHA256 does not match this ZIP.")
            return
        if not messagebox.askyesno(
            "Stage isolated version?",
            f"Pin {tag} and stage in LOCALAPPDATA?\n\n"
            "Only immutable V3 candidate files are written.\n"
            "NO existing watcher, REG data, add-in or Git checkout is changed.",
            parent=self.root,
        ):
            return
        atomic_json(self.manager.policy, {
            "enabled": True, "repository": REPO,
            "approved_tag": tag, "approved_sha256": actual_hash,
            "office_cutover_approved": False,
            "approved_by_operator_utc": self_monitor.dt.datetime.now(
                self_monitor.dt.timezone.utc).isoformat(),
        })
        self._job("Staging approved " + tag,
                  lambda: self.manager.stage(tag, archive, actual_hash),
                  lambda r: messagebox.showinfo(
                      "Staging complete",
                      f"{tag} passed isolated tests.\n"
                      "Office watcher remains unchanged.", parent=self.root
                  ))

    def recover(self):
        if not messagebox.askyesno(
            "Recover V3 transaction?",
            "Restore the recorded previous V3 pointer after an interrupted switch? "
            "No V2 task or records will change.", parent=self.root,
        ):
            return
        self._job("Recovering interrupted V3 pointer", self.manager.recover)

    def rollback(self):
        if not messagebox.askyesno(
            "Restore known-good V3 pointer?",
            "This changes only the V3 active-version pointer. "
            "It does not change the existing surveyor task.", parent=self.root,
        ):
            return
        self._job("Restoring prior V3 pointer", self.manager.rollback)


def main():
    root = tk.Tk()
    Dashboard(root)
    root.mainloop()


if __name__ == "__main__":
    main()
