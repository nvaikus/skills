# Traps (mounts, sync folders, Drive naming)

## Mount
- Writes go to the local VFS cache and upload ~5 s after the file is closed. rclone does NOT upload queued writes on unmount (live-proven) → `umount` exits 3 listing them; `umount --force` keeps them in `~/.cache/gdrive/<profile>/<id>/` and they upload when the same WHAT is mounted at the same dir again.
- Reading a file downloads it whole into the cache first (`--vfs-cache-mode full`); huge files take time and cache space. The cache cap is per mount; old unused files are evicted.
- Remote changes appear within ~1 min (directory cache + Drive change polling).
- macOS: when rclone dies, the NFS mount point stays attached and anything touching it (ls, cd, Finder, `du`) can hang uninterruptibly. `gdrive status` → `stale` → run `gdrive mount <what> <dir>` again (force-unmounts, restarts) or `gdrive umount <dir> --force`. Never probe a stale dir with ls.
- The macOS LaunchAgent (`--persist`) starts the mount at login only; a crash is not auto-restarted (restart cannot heal the wedged mount point).
- A LaunchAgent loaded with `launchctl bootstrap` may never start on its own (`launchctl print` shows `pended nondemand spawn = speculative`, `runs = 0`): gdrive kickstarts right after bootstrap. An agent stuck like that from an older gdrive → rerun `gdrive mount --persist` / `gdrive index service`.
- `umount` exit 1 "busy": a shell/editor has its cwd or open files inside; cd out / close them.
- The macOS mount is case-insensitive; Drive is not: two files differing only by case show as one.

## Google-native files
- Docs/Sheets/Slides appear as `Name.docx/.xlsx/.pptx` exports with no size on Drive. Linux/Windows `mount` reads them only because it runs `--vfs-cache-mode writes` (`full` serves them as 0 bytes, live-proven on Linux); macOS nfsmount shows 0 bytes and reads them EMPTY (NFS has no direct IO; no rclone flag helps, live-proven): read via `gdrive doc cat` / `sheet get`, not the mount. Editing and saving one uploads a NEW Office file next to the Google file. Use `gdrive doc|sheet`; a mount path to the export is accepted by them.

## Sync folder (`--mode sync`)
- Two-way `rclone bisync` on `gdrive sync` only - nothing moves in between.
- Google Docs/Sheets/Slides are skipped (`--drive-skip-gdocs`): use `gdrive doc|sheet`.
- Both sides changed → both kept, renamed `*.conflict1` / `*.conflict2`.
- A pass that would delete more than half of the files aborts (exit 1, nothing deleted): check what vanished before retrying.

## Paths
- Duplicate names in one folder are legal on Drive → exit 2 lists `name@id`; use that as the path component.
- A name containing `/` can only be addressed as `name@id` or by URL.
- "Shared with me" is a flat list, not a folder: `shared-with-me:/<Name>/...`; two shared items with one name → `Name@<id>`. Nothing can be created at its top: `doc new` exits 2; a file saved at the mount's `Shared with me/` top is uploaded by rclone to the My Drive ROOT and vanishes from `Shared with me/` (live-proven) - save under `My Drive/` or inside a shared folder.
- Items shared view/comment-only: reads work, writes exit 2 ("ask the owner for edit access") or fail to upload from the mount.
- The `/` mount's `Shared drives/` list is fixed at mount time: a newly joined Shared drive shows after `gdrive mount` again.
