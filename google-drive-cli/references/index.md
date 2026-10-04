# Text index facts

## Shape
- `~/.claude/gdrive/<profile>/index/<mount-relative path>.md`, one per file of the profile's mount scope (folders are directories). Outside every mount: grep never touches Drive.
- Header between `---` lines: `id`, `md5` (`-` for Google files), `modified`, `path`, `address` (for `gdrive` commands), `extractor`, `indexed`. Body = extracted text.
- Google files carry the mount's export suffix: Doc `Name.docx.md`, Sheet `Name.xlsx.md`, Slides `Name.pptx.md`. Forms/Sites/shortcuts are not in the mount → not indexed.
- Same name twice in a folder (Drive allows it; case-insensitive on macOS/Windows) → `name@<id>` in the index path; the mount itself shows only one of them.
- `/` inside a Drive name appears as `／` (U+FF0F), as in the mount.
- A `/` profile: `index/My Drive/...`, `index/Shared with me/...`, `index/Shared drives/<name>/...` - same layout as the mount. Sections other than My Drive only after `index include` (config `index_sections`); `exclude` deletes that section's texts.
- Shared with me is flat: only the top shared items, their subfolders below them. An item shared to you inside a folder also shared to you shows under that folder only.

## Freshness
- Background service every 5 min (`gdrive index service`): Drive Changes API from the stored cursor → only changed files are downloaded. `index status` `age_min` > 15 = service not running, machine was asleep, or login expired (see `logs/index-<profile>.log`).
- Unchanged checksum = no download. Rename/move = only the .md moves. Trash/delete/leaving the scope = .md removed.
- Remounting a different WHAT changes the scope → the next run wipes and rebuilds the whole index.
- Changing sections, or the first run after a `/` mount switched to the three-folder layout, relists metadata only: existing texts are moved (`My Drive/` prefix), nothing re-downloaded. An old-layout `/` mount keeps the old index paths until `gdrive mount` upgrades it.
- Changes API (user corpus) carries Shared-with-me changes too (new shares, owner renames/edits); Shared drives need `includeItemsFromAllDrives`, set when one is included.
- A big Shared-with-me folder of photos = one OCR call each: include it only when needed.
- A write through the mount reaches Drive ~5 s after close; `index update <path>` before `gdrive sync` re-reads the OLD version.

## Extraction
- docx/xlsx/pptx: own zip+XML reader (xlsx: cached values of formulas, CSV per sheet; pptx: slide text + speaker notes). Google Docs → Drive export `text/markdown` (falls back to text/plain), Sheets → every tab via the Sheets API as CSV, Slides → text/plain.
- PDF: `pdftotext` if on PATH (Homebrew/poppler-utils; not installed by gdrive). No pdftotext, or < 10 letters of text (a scan) → Google OCR. Images → Google OCR.
- Google OCR = copy converted to a Google Doc named `.gdrive-index-ocr-<id>` in My Drive root, exported, deleted at once; marked with appProperties `gdriveIndexTemp=1`, leftovers older than 15 min are swept at the start of every run. One can flash by in a mounted My Drive root.
- Config per profile: `index_max_mb` (50; bigger files → metadata line only), `ocr` (`auto`|`off`), `ocr_max_mb` (20).
- Failed extraction → the .md holds `name · type · size` + `(text not indexed: reason)`, retried only when the file changes. Network/429/5xx failures are retried on the next run.
- Google export caps a Doc/Slides export at 10 MB (`exportSizeLimitExceeded` → metadata line).
- Images above 10 MB skip OCR (metadata line, not an error): Drive converts a 10.0 MB JPEG, rejects 11.1 MB with `413 Request Too Large` (live). Big camera photos are never text-indexed.

## Pending live verification (no real account tested yet)
- OCR limits of files.copy→Google Doc (file size, pages converted), `ocrLanguage` need for Cyrillic scans.
- `text/markdown` export availability; Sheets per-tab volume on large sheets; Changes API behavior for children of a trashed folder (handled by path recompute either way).
