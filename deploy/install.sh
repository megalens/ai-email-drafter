#!/usr/bin/env bash
set -euo pipefail

echo "==> Creating directories"
mkdir -p /etc/ai-drafter /var/lib/ai-drafter /var/log/ai-drafter

echo "==> Installing systemd unit"
cp deploy/ai-drafter.service /etc/systemd/system/ai-drafter.service
systemctl daemon-reload

echo "==> Creating secrets.env template (if not exists)"
if [ ! -f /etc/ai-drafter/secrets.env ]; then
    cat > /etc/ai-drafter/secrets.env <<'ENVEOF'
ANTHROPIC_API_KEY=
STATE_ENCRYPTION_KEY=
GOOGLE_OAUTH_CLIENT_SECRETS=
ENVEOF
    chmod 600 /etc/ai-drafter/secrets.env
    echo "    Edit /etc/ai-drafter/secrets.env with your keys"
fi

echo "==> Creating config.toml template (if not exists)"
if [ ! -f /etc/ai-drafter/config.toml ]; then
    cat > /etc/ai-drafter/config.toml <<'TOMLEOF'
[service]
poll_interval_minutes = 5
context_file = "/etc/ai-drafter/context.md"
state_db = "/var/lib/ai-drafter/state.sqlite"

[llm]
model = "claude-sonnet-4-6"
daily_cost_cap_usd = 5.0

[gmail]
poll_max_messages = 50
bootstrap_lookback_days = 1

[logging]
level = "INFO"
file = "/var/log/ai-drafter/service.log"
TOMLEOF
fi

echo "==> Done. Next steps:"
echo "    1. Edit /etc/ai-drafter/secrets.env"
echo "    2. Create /etc/ai-drafter/context.md"
echo "    3. Run OAuth: ai-drafter auth"
echo "    4. systemctl enable --now ai-drafter"
