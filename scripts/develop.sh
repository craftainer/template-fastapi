#!/usr/bin/env bash
# Sets up the `develop` stage on top of Microsoft's generic base
# devcontainer image (which already provides the `vscode` user, git, sudo,
# and curl); Python itself is installed below via `uv`, pinned to the same
# exact version as the builder/runner stages.
set -euo pipefail

python_version=$1
uv_version=$2
claude_code_version=$3
pyright_version=$4
snip_version=$5
rustfs_cli_version=$6
node_version=$7

apt-get update
# postgresql-client/redis-tools give psql/redis-cli for connecting to the
# stack's postgres/redis services (see .devcontainer/stack/postgres and
# .devcontainer/stack/redis's READMEs). Debian's own repo only carries one
# version of each (currently newer than the pinned server images) -- same
# as libpq-dev below, there's no exact-version pin available via apt; a
# newer client talking to an older server is standard practice for both
# tools. RustFS's own CLI (rc) isn't an apt package, so it's installed
# separately below. xz-utils: Node's own release tarballs are .tar.xz.
apt-get install -y --no-install-recommends libpq-dev postgresql-client redis-tools xz-utils
apt-get clean
rm -rf /var/lib/apt/lists/*

curl -LsSf "https://releases.astral.sh/github/uv/releases/download/${uv_version}/uv-installer.sh" \
    | sudo -u vscode env HOME=/home/vscode INSTALLER_NO_MODIFY_PATH=1 sh
ln -s /home/vscode/.local/bin/uv /usr/local/bin/uv
ln -s /home/vscode/.local/bin/uvx /usr/local/bin/uvx

# Installs the exact pinned CPython build (from python-build-standalone) --
# UV_PYTHON in the Dockerfile's develop stage then pins `uv sync` and every
# other uv invocation to it, so it matches the builder/runner stages' own
# python:${PYTHON_VERSION}-slim base image exactly.
sudo -u vscode env HOME=/home/vscode /usr/local/bin/uv python install "$python_version"

curl -fsSL https://claude.ai/install.sh \
    | sudo -u vscode env HOME=/home/vscode bash -s "$claude_code_version"
ln -s /home/vscode/.local/bin/claude /usr/local/bin/claude

# For the pyright-lsp Claude Code plugin — see .claude/README.md.
sudo -u vscode env HOME=/home/vscode /usr/local/bin/uv tool install "pyright==${pyright_version}"
ln -s /home/vscode/.local/bin/pyright /usr/local/bin/pyright
ln -s /home/vscode/.local/bin/pyright-langserver /usr/local/bin/pyright-langserver

# For the snip Claude Code PreToolUse hook — see .claude/README.md. Not on
# PyPI/npm like the tools above, so fetched as a release tarball and
# checksum-verified against the project's own published checksums.txt
# instead of trusting a curl-pipe-to-sh installer.
snip_arch="$(dpkg --print-architecture)"
snip_asset="snip_${snip_version}_linux_${snip_arch}.tar.gz"
snip_tmpdir="$(mktemp -d)"
sudo chmod a+rwx "$snip_tmpdir"
curl -LsSf -o "${snip_tmpdir}/${snip_asset}" \
    "https://github.com/edouard-claude/snip/releases/download/v${snip_version}/${snip_asset}"
curl -LsSf -o "${snip_tmpdir}/checksums.txt" \
    "https://github.com/edouard-claude/snip/releases/download/v${snip_version}/checksums.txt"
(cd "$snip_tmpdir" && grep " ${snip_asset}\$" checksums.txt | sha256sum -c -)
tar -xzf "${snip_tmpdir}/${snip_asset}" -C "$snip_tmpdir" snip
sudo -u vscode install -Dm755 "${snip_tmpdir}/snip" /home/vscode/.local/bin/snip
rm -rf "$snip_tmpdir"
ln -s /home/vscode/.local/bin/snip /usr/local/bin/snip

# For connecting to the s3 stack service (RustFS) -- see
# .devcontainer/stack/s3/README.md. Published as .deb/.rpm release assets
# plus a SHA256SUMS file, not on apt/PyPI/npm, so fetched and
# checksum-verified the same way as snip above.
rustfs_cli_arch="$(dpkg --print-architecture)"
rustfs_cli_asset="rustfs-cli_${rustfs_cli_version}_${rustfs_cli_arch}.deb"
rustfs_cli_tmpdir="$(mktemp -d)"
curl -LsSf -o "${rustfs_cli_tmpdir}/${rustfs_cli_asset}" \
    "https://github.com/rustfs/cli/releases/download/v${rustfs_cli_version}/${rustfs_cli_asset}"
curl -LsSf -o "${rustfs_cli_tmpdir}/SHA256SUMS" \
    "https://github.com/rustfs/cli/releases/download/v${rustfs_cli_version}/SHA256SUMS"
(cd "$rustfs_cli_tmpdir" && grep " ${rustfs_cli_asset}\$" SHA256SUMS | sha256sum -c -)
apt-get install -y --no-install-recommends "${rustfs_cli_tmpdir}/${rustfs_cli_asset}"
rm -rf "$rustfs_cli_tmpdir"

# Node.js, infrastructure tooling only: the clear-thought MCP server in
# ../.mcp.json is the only thing that needs npx. Installed directly from
# nodejs.org's own release tarballs (checksum-verified against that
# release's published SHASUMS256.txt) rather than a devcontainer feature,
# so it's pinned the same way, in the same place, as every other tool in
# this stage -- see the Dockerfile's NODE_VERSION ARG.
node_dpkg_arch="$(dpkg --print-architecture)"
case "$node_dpkg_arch" in
    amd64) node_arch=x64 ;;
    arm64) node_arch=arm64 ;;
    *)
        echo "unsupported architecture for Node.js install: $node_dpkg_arch" >&2
        exit 1
        ;;
esac
node_asset="node-v${node_version}-linux-${node_arch}"
node_tmpdir="$(mktemp -d)"
curl -LsSf -o "${node_tmpdir}/${node_asset}.tar.xz" \
    "https://nodejs.org/dist/v${node_version}/${node_asset}.tar.xz"
curl -LsSf -o "${node_tmpdir}/SHASUMS256.txt" \
    "https://nodejs.org/dist/v${node_version}/SHASUMS256.txt"
(cd "$node_tmpdir" && grep " ${node_asset}.tar.xz\$" SHASUMS256.txt | sha256sum -c -)
mkdir -p /usr/local/lib/nodejs
tar -xJf "${node_tmpdir}/${node_asset}.tar.xz" -C /usr/local/lib/nodejs
rm -rf "$node_tmpdir"
ln -s "/usr/local/lib/nodejs/${node_asset}/bin/node" /usr/local/bin/node
ln -s "/usr/local/lib/nodejs/${node_asset}/bin/npm" /usr/local/bin/npm
ln -s "/usr/local/lib/nodejs/${node_asset}/bin/npx" /usr/local/bin/npx

# `kcadm` reaches the sibling `keycloak` container's Admin REST API from
# the devcontainer -- see .devcontainer/stack/keycloak/README.md. A thin
# curl wrapper rather than the official kcadm.sh, which ships only inside
# Keycloak's full server distribution and needs a JVM neither this stage
# nor the app otherwise requires.
kcadm_tmpfile="$(mktemp)"
sudo chmod a+rwx "$kcadm_tmpfile"
cat > "$kcadm_tmpfile" <<'EOF'
#!/usr/bin/env bash
# Thin curl wrapper for the Keycloak Admin REST API. See
# .devcontainer/stack/keycloak/README.md for usage and required env vars.
set -euo pipefail

if [[ $# -lt 2 ]]; then
    echo "Usage: kcadm METHOD PATH [JSON_BODY]" >&2
    echo "Example: kcadm GET /admin/realms/template-fastapi/users" >&2
    exit 1
fi

method=$1
path=$2
body=${3:-}
base_url=${KEYCLOAK_URL:-http://keycloak:8080}

token=$(curl -sf -X POST "${base_url}/realms/master/protocol/openid-connect/token" \
    -d grant_type=password \
    -d client_id=admin-cli \
    -d "username=${KEYCLOAK_ADMIN}" \
    -d "password=${KEYCLOAK_ADMIN_PASSWORD}" \
    | python3 -c 'import json, sys; print(json.load(sys.stdin)["access_token"])')

curl_args=(-sf -X "$method" "${base_url}${path}" \
    -H "Authorization: Bearer ${token}" \
    -H "Content-Type: application/json")
[[ -n "$body" ]] && curl_args+=(-d "$body")

curl "${curl_args[@]}" | { python3 -m json.tool 2>/dev/null || cat; }
EOF
sudo -u vscode install -Dm755 "$kcadm_tmpfile" /home/vscode/.local/bin/kcadm
rm -f "$kcadm_tmpfile"
ln -s /home/vscode/.local/bin/kcadm /usr/local/bin/kcadm
