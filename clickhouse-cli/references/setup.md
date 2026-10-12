# Setup: install, connections, remote servers

## Install

| OS | Command |
|---|---|
| Debian / Ubuntu | official apt repo, then `sudo apt-get install -y clickhouse-client` (steps below) |
| RHEL / Fedora | `sudo yum-config-manager --add-repo https://packages.clickhouse.com/rpm/clickhouse.repo && sudo yum install -y clickhouse-client` |
| macOS | `brew install --cask clickhouse` |
| Any, no package manager | `curl https://clickhouse.com/ \| sh` → `./clickhouse` in the current dir; move it onto PATH |

- apt repo:
  ```sh
  curl -fsSL https://packages.clickhouse.com/rpm/lts/repodata/repomd.xml.key | sudo gpg --dearmor -o /usr/share/keyrings/clickhouse-keyring.gpg
  echo "deb [signed-by=/usr/share/keyrings/clickhouse-keyring.gpg arch=$(dpkg --print-architecture)] https://packages.clickhouse.com/deb stable main" | sudo tee /etc/apt/sources.list.d/clickhouse.list
  sudo apt-get update && sudo apt-get install -y clickhouse-client
  ```
- `clickhouse-client` pulls `clickhouse-common-static` (~800 MB single binary, all tools); no server is installed or started.
- Client newer than the server is fine (native protocol negotiates).

## Connections (one per server)

- Config file, first found: `~/.clickhouse-client/config.xml` or `.yaml`, `~/.config/clickhouse/config.xml`; or `-C <file>`.
  ```xml
  <config>
    <connections_credentials>
      <connection>
        <name>prod</name>
        <hostname>ch.example.com</hostname>
        <port>9440</port>
        <secure>1</secure>
        <user>reader</user>
        <password from_env="CLICKHOUSE_PROD_PASSWORD"/>
        <database>default</database>
      </connection>
    </connections_credentials>
  </config>
  ```
- Password: `from_env` only; the user exports `CLICKHOUSE_<NAME>_PASSWORD` from their secret store (macOS Keychain → env; Linux → a mode-600 env file sourced by the shell). Never a literal in the file, never `--password` on argv (visible in `ps`). One-off: `CLICKHOUSE_USER` / `CLICKHOUSE_PASSWORD` env.
- Ask the user for a read-only DB user for exploration work; record which connection is which in memory.

## Ports and protocols

- `clickhouse client` speaks only the native protocol: 9000 plain, 9440 TLS (`--secure` / `<secure>1</secure>`).
- 8123 / 8443 are HTTP. Pointing the client there fails with `Unexpected packet from server ... (expected Hello or Exception, got 72)`. Native port not reachable → SSH tunnel to it (`ssh -N -L 9000:127.0.0.1:9000 <host>`, then `<hostname>127.0.0.1</hostname>`), or plain HTTP: `curl -sS --data-binary "<sql> FORMAT TSVWithNames" -u "$USER_NAME:$PASSWORD" http://<host>:8123/`.
- Server in a container with only HTTP published: the native port still listens inside the container network (`podman|docker inspect <ctr>` → IP; changes on recreate).

## ClickHouse Cloud

- Querying a service = the same client: host `<id>.<region>.<provider>.clickhouse.cloud`, `--secure` (9440), user `default` unless the user made another.
- Managing services (create, scale, stop, API keys, ClickPipes, managed Postgres) = `clickhousectl` (official, https://github.com/ClickHouse/clickhousectl; `curl -fsSL https://clickhouse.com/cli | sh`, or `pipx install clickhousectl`). Auth: `clickhousectl cloud auth login` (browser, read-only) or `CLICKHOUSE_CLOUD_API_KEY` / `CLICKHOUSE_CLOUD_API_SECRET` env (read/write). Commands from its `--help`.
