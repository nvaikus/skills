# REST gaps: attachments, custom fields

acli cannot upload or download attachments and has no custom-field flags. Both go through Jira REST v3, with the token acli already stores.

## Token

- `$ATLASSIAN_TOKEN` set → use it (email: `$ATLASSIAN_EMAIL` or the config below), skip the keyring.
- Profile and email: `.config/acli/jira_config.yaml` under the binary's HOME (a wrapper's HOME = `~/.claude/atlassian-cli/sites/<alias>`).
- Secret: OS keyring, service `acli`, account `jira:<profile>`. The value starts with `go-keyring-base64:` — strip it, base64-decode the rest.

| OS | Read the secret |
|---|---|
| macOS | `security find-generic-password -s acli -a "jira:<profile>" -w` |
| Linux | `secret-tool lookup service acli username "jira:<profile>"` |
| Windows | Credential Manager, target `acli:jira:<profile>`: CredRead via P/Invoke from PowerShell (`Add-Type`, no modules) |
| Linux, no Secret Service (headless) | none: acli keeps the token encrypted inside `jira_config.yaml` (`token: !!binary`) — not readable; use `$ATLASSIAN_TOKEN` |

- Resolve it into a variable in the same shell call as the request; never echo, print or log it. macOS:
  `TOKEN=$(security find-generic-password -s acli -a "jira:<profile>" -w | sed 's/^go-keyring-base64://' | base64 -d); curl ...`

## Attachments

- acli covers list and delete only: `acli jira workitem attachment list --key <KEY> --json` → `{"attachments": [{id, name, size}]}`.
- Upload:
  `curl -sf -u "$EMAIL:$TOKEN" -H 'X-Atlassian-Token: no-check' -F 'file=@<path>' https://<site>.atlassian.net/rest/api/3/issue/<KEY>/attachments`
- Download (redirects to the binary — `-L` is required):
  `curl -sfL -u "$EMAIL:$TOKEN" -o <file> https://<site>.atlassian.net/rest/api/3/attachment/content/<id>`

## Custom fields

- Create first with the standard flags, then set the field with a PUT:
  `curl -sf -u "$EMAIL:$TOKEN" -X PUT -H 'Content-Type: application/json' https://<site>.atlassian.net/rest/api/3/issue/<KEY> -d '{"fields":{"customfield_<N>":{"value":"<option>"}}}'`
- Option fields take `{"value": "<option name>"}`; text and number fields take the bare value.
- Field id and allowed options: `GET /rest/api/3/issue/createmeta/<PROJECT>/issuetypes` → the type's id → `GET .../issuetypes/<id>?maxResults=200`. Write the ids to memory per project.
- `create --from-json` (template: `create --generate-json`) can carry custom fields under `additionalAttributes`, but then the whole payload, ADF description included, moves into that file — the PUT is simpler.
