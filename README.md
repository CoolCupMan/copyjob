# CopyJob 1.1.2 — volume-aware Windows backup jobs

Application ID: `org.copyjob.desktop`. Each installation has an independent UUID,
configuration, log and scheduled task. Intended platform: Windows 10/11 with Windows
PowerShell 5.1, WMI/CIM and Task Scheduler. The application is unsigned.

## Install and configure

1. Extract the EXE to a writable folder on an internal disk. For another independent
   installation, choose **Install independent instance…**. Do not move an installation
   after registering its task; remove and re-enable startup if its location changes.
2. **Refresh volumes**. Windows volume GUIDs are displayed alongside labels and current
   drive letters. This lists Windows-visible internal, USB and external volumes;
   locked/unformatted media and network shares are not universally discoverable.
3. Add one job per copy operation. Choose a **trigger volume** to run when that volume
   has a drive letter. Choose optional **source volume** and **destination volume** IDs
   so paths follow those volumes when their letters change. In volume-relative fields,
   enter `Documents`, `Backups\Documents`, or `.` for the root. Full drive paths
   such as `E:\Backups\Documents` are accepted too: saving converts them to
   `Backups\Documents` relative to the selected volume. The selected Volume-ID
   controls the drive, even if its current letter differs from the pasted path.
   With no volume selected, full paths stay fixed. Use **Preview paths** to check
   the resolved source, destination and source availability without copying or
   enabling an automatic job.
4. Choose engine, switches, delay and retry interval. Enable **automatic job**, then
   **Save job**. **Copy now** runs the selected saved settings immediately.
5. Select **Enable login startup**. This registers and starts a limited, interactive
   per-user task named `CopyJob-<UUID>`. It launches the EXE with `--background`, with
   no settings window or copy console. Closing settings leaves this monitor running.

The monitor reads saved settings and WMI `Win32_Volume` inventory every three seconds.
It waits for drive-letter assignment by Windows or third-party tools, then resolves
paths from GUIDs. Already-present volumes are checked after login/restart too. A job
runs once when its selected trigger volume becomes available or changes drive letter.
Source/destination file contents, folder existence changes, copy options and folder-path
edits do not retrigger a successful job while that trigger drive remains connected.
With no explicit trigger volume, the destination volume/drive is used. Existing drives
are checked once when the monitor starts after login/restart; failed jobs retry after
the configured interval. Jobs within one monitor run sequentially. A per-job named
mutex prevents the same job running simultaneously from the GUI and the monitor.
Use separate destinations for independent jobs/instances; different jobs targeting
one destination are not coordinated. Sleep and long copies can delay detection;
an unplug/replug entirely between scans may be missed.

## Optional persistent WMI consumer and preferred letters

**Export WMI setup…** creates a readable, instance-specific `.ps1`. First enable login
startup, then run the exported script in **Windows PowerShell 5.1 as administrator**:

```powershell
& 'C:\path\CopyJob-WMI-Setup.ps1'
```

Normal PowerShell execution policy applies; no bypass is installed. The permanent
local WMI filter watches `__InstanceCreationEvent` for new `Win32_LogicalDisk` instances (drive arrival / letter assignment), ignoring
free-space updates caused by folder-content changes. After upgrading, re-export and
rerun WMI setup to update an existing permanent filter.
Its consumer only invokes Windows `schtasks.exe /Run` for this instance's limited user
task. It does not execute the user's EXE/scripts as SYSTEM. Existing unrelated WMI
consumers, including the supplied `TestConsumer`, are left unchanged. If those still
run old copy scripts, disable them separately to avoid duplicate old/new jobs.

Optionally save a **preferred trigger letter** (D–Z) per trigger volume before export.
The admin setup then installs a separate SYSTEM startup task with an immutable
encoded action containing only those volume/letter mappings. Every five seconds it
rechecks those volumes, restoring their preferred letters when available. It never
takes occupied letters or changes Windows boot/system volumes. This task can assign
letters before sign-in; **copying still starts after the configured user signs in**.
Letter enforcement can conflict with third-party letter managers: choose one desired
mapping. Assignment does not format, unlock or decrypt disks. Reformatting a volume
may change its GUID, requiring updated settings. Re-export and rerun the admin setup
when changing preferred mappings; editing JSON alone does not update the SYSTEM task.
The one-time **Assign trigger letter…** button requests UAC and immediately assigns
an available letter; it does not install an automatic mapping rule.

The WMI hook and optional assignment task persist across reboots. Polling covers
startup, delayed assignment and events that WMI does not deliver. Availability and
Windows permissions still matter; no program can guarantee copying inaccessible media.

## Copy engines and options

- `xcopy`: invokes the Windows-installed `xcopy.exe`, not bundled legacy versions.
  Checkboxes expose common switches; **Show installed XCOPY options** displays that
  machine's actual help. Additional options support `/D:MM-DD-YYYY`,
  `/EXCLUDE:"C:\My Files\exclude.txt"`, `/SPARSE:Y` and other supported parameter forms.
  Newer switches such as `/COMPRESS`, `/SPARSE` and `/NOCLONE` depend on Windows version
  and filesystem. Unsupported combinations fail with logged native output.
- `/I` and `/Y` are enforced for unattended jobs. `/W` and `/-Y` are visible but rejected
  because they wait for interactive input. `/L` previews a job; `/Z` enables XCOPY's
  restartable transfer mode. `/D` avoids overwriting files with newer timestamps.
  Flags `/O`, `/X`, `/B`, `/G`, etc. retain their native Windows semantics/permissions.
  `/C` requests continuing after errors, so read the log even after native success.
  Exit 0 means copied, 1 means no matching files, and 2/4/5 are failure/cancellation.
- `builtin`: the original timestamp-based engine. Copies missing/older destination
  files, skips source links and rejects linked ancestors/destination links. XCOPY
  checkboxes do not affect this engine.
- `powershell`: choose an existing absolute `.ps1` path. This launches your selected
  finite copy script, not a drive-watcher loop. The script receives environment
  variables `COPYJOB_SOURCE`, `COPYJOB_DESTINATION` and `COPYJOB_JOB_ID`. It runs under
  the user's existing execution policy without elevation or policy bypass. Use
  terminating errors / nonzero exit codes for failures. The app cannot guarantee
  behavior of custom scripts or stop independently spawned child processes.

Source and destination must be separate, non-nested folders. No built-in deletion or
mirror mode is provided. XCOPY can overwrite files according to your switches. No
process killing, task-folder ACL changes or automatic execution of uploaded scripts
is performed. Log output is appended beside the EXE (`copyjob.log`), without rotation.
For active browser profiles, close the browser first; no VSS snapshot is performed.
Cancellation does not roll back completed copies. Configuration survives reboot;
successful files are not a transaction/checkpoint database. `/Z` is available where
native XCOPY supports transfer resumption.

## Pause, remove, upgrade

**Pause / resume background** persists a pause marker. An active automatic copy finishes;
manual copies remain available. To stop the monitor and remove login startup, choose
**Remove login startup**. If WMI/preferred-letter setup was installed, first run the
same exported setup script as administrator with `-Remove`:

```powershell
& 'C:\path\CopyJob-WMI-Setup.ps1' -Remove
```

This removes only this instance's WMI binding/filter/consumer and assignment task.
Then remove login startup, close the app and delete its installation folder.
Stopping a task during native copying may leave a partial destination file. Existing
1.0 configurations migrate to a disabled built-in job. For an in-place upgrade, stop
background startup before replacing the EXE; preserve `instance.json`, then enable
startup again. Parallel versions should use independent installations/UUIDs.

## Build and validation

Use the existing checkout; no extra worktree is needed. Runtime Python code uses the
standard library. On Windows with Python 3.12 and Tk:

```powershell
python -m unittest discover -s tests -v
python tests/windows_gui_smoke.py
python -m pip install -r requirements-build.txt
python -m PyInstaller --clean --noconfirm --onefile --windowed --name CopyJob --version-file version_info.txt --add-data "wmi_setup.ps1;." app.py
```

The GitHub Actions `Windows EXE` workflow builds the same artifact. The supplied EXE
was built using Windows Python under Wine. Automated tests cover volume remapping,
delayed-letter prerequisites, retries, reconnect scheduling, flags and the copy engine.
A GUI integration check uses actual native XCOPY with mocked volume inventory because
Wine does not implement Windows CIM inventory. Packaged GUI startup is checked under
Wine. **Actual WMI registration, UAC letter assignment, Task Scheduler and reboot
behavior require a native Windows test and are not verified by Wine.**
