# Traps (iCloud CalDAV)

Marked (unverified) = expected from protocol/other clients, not yet checked live against iCloud by this tool.

## Kinds and access
- Kind comes from the collection's `resourcetype`: `CS:shared-owner` = shared by me, `CS:shared` = shared with me, `CS:subscribed` = subscription; no `VEVENT` in the component set = Reminders list.
- Access = `current-user-privilege-set` (write/bind/all → rw); if iCloud omits it, the `CS:invite` entry for the user's address decides. Read-only shares still carry `write-properties` (rename/color) - that is not write access. Verified live: a read-write share shows `shared-with-me rw`; read-only shares still unverified.
- Subscriptions added on the Mac/iPhone with "Location: iCloud" appear; ones stored "On My Mac" do not, nor do "Birthdays" / "Siri Suggestions" / delegated Exchange calendars (verified live: no Birthdays/Siri collections over CalDAV; subscriptions unverified).
- iCloud refuses a write the CLI let through (privileges changed since) → HTTP 403 → exit 1 "refused"; rerun `calendars` to see current access.

## Listing
- `list` asks the server to expand recurrences (`expand`); any event still carrying an RRULE is expanded locally. JSON `expanded` says which happened (server vs local). Verified live: iCloud honours `expand`, recurring events come back as `server`.
- Local expansion skips rules with BYHOUR/BYMINUTE/BYSECOND/BYWEEKNO/BYYEARDAY: the event shows once with a `# ` note.
- Subscribed calendars are read from their public feed URL each time; a dead feed is a `# ` note, the rest of the list still prints.
- Range bounds are midnight in the output zone; all-day `end` in output is the last day, inclusive.

## Writing
- Events are stored in the zone they were given (TZID + VTIMEZONE): a 10:00 Lisbon event shows 11:00 to a viewer in Paris. `edit --start` rewrites the event in the output zone; moving only the end keeps its zone.
- Unknown properties (Apple travel time, structured location, attachments) survive `edit`; `--no-alarms` removes alarms on the series, not per device.
- Edit/delete check the ETag: someone (another device) changed it in between → 412, rerun.
- Event in a shared-with-me calendar is owned by the calendar owner: they can change/delete it; the user cannot take it back.
- Deleted by mistake → icloud.com → Account Settings → Data Recovery → Restore Calendars (restores the whole calendar set to an archive, a blunt tool), or re-add from `show -j` output captured earlier.

## Map pins (location)
- Clickable location = `X-APPLE-STRUCTURED-LOCATION;VALUE=URI;X-ADDRESS=..;X-APPLE-RADIUS=..;X-APPLE-REFERENCEFRAME=1;X-TITLE=..:geo:LAT,LON` (+ `GEO`); plain `LOCATION` alone is inert text. Calendar's own `X-APPLE-MAPKIT-HANDLE` is opaque and not written; geo + title is what other clients write (verified live: Calendar on Mac and iPhone opens Maps at the pin without the handle).
- Calendar shows `X-TITLE` as the place name and `X-ADDRESS` below it; `LOCATION` becomes `title\naddress`. Title = the first line / first comma part of `--location` as typed (house number kept); address = the rest, completed with the geocoder's locality and country.
- Lookup: Nominatim (exact, no typo tolerance: `Rua Alameda X` misses), then Photon (fuzzy; accepted only when a word of the address part appears in the hit). Names come in the place's own language. Nominatim allows ~1 request/s: never loop `add` over many locations without pauses.
- `edit --location` re-pins (old pin dropped, also on no match); `--no-geo` drops the pin, keeps the text; `--geo` alone pins the current text. `show` prints `map:` with an Apple Maps link.
