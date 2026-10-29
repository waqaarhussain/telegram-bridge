# Telegram Bridge

Self-hosted Telegram user-session bridge for provider signals. It watches one Telegram source channel, filters and normalises supported provider messages, follows reply chains, and forwards clean provider-ID events into the Telegram channel read by the MT5 EA.

The current provider profile is the **ForeXpert XAU/USD** workflow used by the paired MT5 EA. The repository name is intentionally generic so the provider parser can be changed later without rebuilding the VPS plumbing.

The bridge logs in as your normal Telegram account, so it can read private/paid channels that your account can access. No Telegram bot token is required on the VPS.

## Install

Use a fresh or compatible Ubuntu VPS with root/sudo access. Before first install, create a Telegram API ID and API hash under **my.telegram.org → API development tools**.

```bash
curl -fsSL https://raw.githubusercontent.com/waqaarhussain/telegram-bridge/main/install.sh | sudo bash
```

The installer:

- Installs Python and Telethon
- Prompts for Telegram API ID/hash on first setup
- Logs into your Telegram account by phone/code/2FA where required
- Lists/searches all chats, groups and channels your account can access
- Lets you select the provider source and EA destination
- Saves the Telegram user session locally on the VPS
- Installs a persistent `systemd` service
- Creates `sudo update-live` for future GitHub updates
- Creates `sudo bridge-config` to change source/destination later

Normal VPS or service restarts do not require another Telegram login while the saved session remains valid.

## Current ForeXpert provider profile

Only valid XAU/USD provider workflows are converted into MT5-friendly messages.

Supported flow:

- New `BUY` / `SELL` XAU/USD Entry Zone signal → store/forward as a waiting workflow
- `TP1 Hit` → trigger the exact provider-ID trade
- `Manually close TP1` and common wording variations → treated as `TP1_HIT`
- `SL Hit` → cancel/close the exact provider-ID workflow
- `Break even Hit` → exact provider-ID close
- `Manually close TP2` → exact provider-ID close
- Generic command-style `Close` / `Close now` / `Close trade` / `Exit now` → exact provider-ID close
- `Change TP2`, `Update TP2`, `New TP2`, `TP2 changed/updated`, `TP is now`, `Change take profit`, and similar wording → exact provider-ID TP2 update

Messages for other pairs, adverts, results chatter, promotions and unrelated provider updates are ignored.

## Provider IDs and duplicate handling

Every original provider Telegram post gets a stable ID built from:

```text
<source-chat-id>_<telegram-message-id>
```

Two separate signals with **identical Entry Zone, TP1, TP2 and SL** are still two different workflows because Telegram gives each original post its own message ID.

The same Telegram message cannot be processed twice, and duplicate TP1 events for an already-triggered provider ID are ignored.

## Reply-chain matching and self-heal

Provider updates often contain very little context, for example:

```text
TP1 Hit +160 Pips ✅
```

The bridge follows Telegram's `reply_to_message` chain back to the original XAU/USD setup and uses that original message's provider ID.

If the original signal arrived while the VPS/EA was offline, a later actionable reply can rebuild the signal from Telegram first and then send the management event. This is the self-heal path used for missed original posts.

Terminal workflows that the bridge has already recorded as cancelled/closed are not deliberately resurrected.

## MT5 destination contract

Example waiting signal:

```text
FXP_EVENT=SIGNAL
PROVIDER_ID=1001763334593_41605
SIDE=SELL
ENTRY1=4029
ENTRY2=4024
TP1=4005
TP2=3999
SL=4031
```

Example trigger:

```text
FXP_EVENT=TP1_HIT
PROVIDER_ID=1001763334593_41605
```

Example TP2 update:

```text
FXP_EVENT=CHANGE_TP2
PROVIDER_ID=1001763334593_41605
TP2=3986
```

See [`docs/ea-contract.md`](docs/ea-contract.md) for the full message contract.

## Operation

Live logs:

```bash
sudo journalctl -u forexpert-bridge -f
```

Status:

```bash
sudo systemctl status forexpert-bridge --no-pager
```

Change the provider source or EA destination without recreating the Telegram login:

```bash
sudo bridge-config
```

Update to the latest GitHub version:

```bash
sudo update-live
```

## Files and service

For compatibility with the existing live deployment, the on-VPS path and systemd service still use the legacy `forexpert-bridge` name. This can be renamed later as a separate migration without affecting the public repo name.

```text
/opt/forexpert-bridge/
├── .venv/
├── bridge.py
├── setup.py
├── reconfigure.sh
├── requirements.txt
├── config.json                  # local only, never committed
├── telegram_session.session     # local only, never committed
└── bridge.sqlite3               # local workflow/processed-message state

/etc/systemd/system/forexpert-bridge.service
/usr/local/sbin/update-live
/usr/local/sbin/bridge-config
```

## Security

The Telegram `.session` file is effectively a logged-in Telegram session. Treat it like a credential.

- Keep the VPS private and patched
- Do not commit `config.json`, API hashes, Telegram sessions or the local SQLite database
- Do not share the session file
- The installer stores local credentials/state under `/opt/forexpert-bridge/` with root-only permissions
- The public GitHub repository contains code only, not your Telegram account secrets or selected chat IDs

## Requirements

- Ubuntu 22.04/24.04 or compatible Debian-based VPS
- Root or sudo access
- Python 3 with venv support
- Outbound HTTPS access to Telegram, GitHub and Ubuntu package repositories
- Telegram account that can already access the provider channel
- Telegram API ID/hash created under `my.telegram.org`
- Destination Telegram channel/group that your account can post to
- MT5 EA configured to read the destination channel

## Repository layout

```text
telegram-bridge/
├── .gitignore
├── README.md
├── bridge.py
├── setup.py
├── install.sh
├── reconfigure.sh
├── requirements.txt
├── forexpert-bridge.service
└── docs/
    └── ea-contract.md
```

## Notes

This bridge does not execute trades itself. It only converts selected Telegram provider messages into structured events for the MT5 EA. Trading behaviour, risk sizing, SL buffers, Worse TP handling, commission logic and broker execution remain inside the EA.
