#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="keylol-tg"
APP_USER="keylol"
APP_GROUP="keylol"
APP_DIR="/opt/keylol-tg"
UNIT_PATH="/etc/systemd/system/${APP_NAME}.service"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

log() {
    printf '[%s] %s\n' "$APP_NAME" "$*"
}

fail() {
    printf '[%s] 错误：%s\n' "$APP_NAME" "$*" >&2
    exit 1
}

[[ "$(id -u)" -eq 0 ]] || fail "请使用 sudo 执行：sudo $0"
[[ -f "$SCRIPT_DIR/main.py" && -f "$SCRIPT_DIR/pyproject.toml" ]] || fail "请从项目仓库目录运行此脚本。"
[[ -f "$SCRIPT_DIR/.env.example" ]] || fail "找不到 .env.example。"
[[ -f "$SCRIPT_DIR/systemd/keylol-tg.service" ]] || fail "找不到 systemd/keylol-tg.service。"
command -v systemctl >/dev/null 2>&1 || fail "系统未找到 systemctl。"

UV_BIN="$(command -v uv || true)"
[[ -n "$UV_BIN" ]] || fail "找不到 uv。请先为系统安装 uv，并确保 root 的 PATH 中包含 uv，然后重新运行。"

if ! getent group "$APP_GROUP" >/dev/null; then
    groupadd --system "$APP_GROUP"
fi
if ! id "$APP_USER" >/dev/null 2>&1; then
    useradd --system --gid "$APP_GROUP" --home-dir "$APP_DIR" --no-create-home --shell /usr/sbin/nologin "$APP_USER"
fi

install -d -o "$APP_USER" -g "$APP_GROUP" -m 0750 "$APP_DIR"

# 更新程序文件，但保留机器本地的配置、运行数据和虚拟环境。
tar -C "$SCRIPT_DIR" \
    --exclude='./.git' \
    --exclude='./.venv' \
    --exclude='./.env' \
    --exclude='./data' \
    --exclude='./__pycache__' \
    -cf - . | tar -C "$APP_DIR" -xf -

ENV_CREATED=0
if [[ ! -f "$APP_DIR/.env" ]]; then
    install -o "$APP_USER" -g "$APP_GROUP" -m 0600 "$APP_DIR/.env.example" "$APP_DIR/.env"
    ENV_CREATED=1
fi
install -d -o "$APP_USER" -g "$APP_GROUP" -m 0750 "$APP_DIR/data"
chown -R "$APP_USER:$APP_GROUP" "$APP_DIR"
chmod 0600 "$APP_DIR/.env"

log "使用 uv 安装项目依赖……"
runuser -u "$APP_USER" -- "$UV_BIN" sync --project "$APP_DIR" --frozen

# 使用检测到的 uv 绝对路径，避免 systemd 无法读取交互式 shell 的 PATH。
install -d -m 0755 /etc/systemd/system
awk -v uv="$UV_BIN" '
    /^ExecStart=/ { print "ExecStart=" uv " run main.py"; next }
    { print }
' "$APP_DIR/systemd/keylol-tg.service" > "$UNIT_PATH"
chmod 0644 "$UNIT_PATH"
systemctl daemon-reload

if [[ "$ENV_CREATED" -eq 1 ]]; then
    log "已安装，但尚未启动服务。请先编辑 $APP_DIR/.env 填入配置。"
    log "配置完成后运行：sudo systemctl enable --now $APP_NAME"
else
    systemctl enable --now "$APP_NAME"
    log "服务已安装并启动。查看状态：sudo systemctl status $APP_NAME"
fi
