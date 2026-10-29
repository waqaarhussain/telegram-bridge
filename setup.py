#!/usr/bin/env python3
import asyncio
import json
from pathlib import Path

from telethon import TelegramClient, utils
from telethon.errors import SessionPasswordNeededError
from telethon.tl import types

BASE = Path('/opt/forexpert-bridge')
CONFIG = BASE / 'config.json'
SESSION = str(BASE / 'telegram_session')


def load_config():
    if not CONFIG.exists():
        return {}
    try:
        return json.loads(CONFIG.read_text())
    except Exception:
        return {}


def save_config(cfg):
    CONFIG.write_text(json.dumps(cfg, indent=2))
    CONFIG.chmod(0o600)


def ask_api_id(existing=None):
    if existing:
        return int(existing)
    while True:
        raw = input('Telegram API ID: ').strip()
        try:
            value = int(raw)
            if value > 0:
                return value
        except ValueError:
            pass
        print('API ID must contain numbers only.')


def ask_api_hash(existing=None):
    if existing:
        return existing
    while True:
        value = input('Telegram API Hash: ').strip()
        if value:
            return value
        print('API Hash cannot be blank.')


def entity_kind(entity):
    if isinstance(entity, types.Channel):
        return 'CHANNEL' if getattr(entity, 'broadcast', False) else 'GROUP'
    if isinstance(entity, types.Chat):
        return 'GROUP'
    if isinstance(entity, types.User):
        return 'BOT' if getattr(entity, 'bot', False) else 'USER'
    return 'CHAT'


async def build_dialog_list(client):
    me = await client.get_me()
    items = []
    seen = set()

    self_peer = utils.get_peer_id(me)
    items.append({'peer': self_peer, 'name': 'Saved Messages', 'kind': 'SELF'})
    seen.add(self_peer)

    dialogs = await client.get_dialogs(limit=None)
    for dialog in dialogs:
        peer = utils.get_peer_id(dialog.entity)
        if peer in seen:
            continue
        seen.add(peer)
        name = dialog.name or getattr(dialog.entity, 'username', None) or str(peer)
        items.append({'peer': peer, 'name': name, 'kind': entity_kind(dialog.entity)})

    items.sort(key=lambda x: (x['name'].lower(), x['kind']))
    return items


async def choose_dialog(client, title, forbidden_peer=None):
    items = await build_dialog_list(client)
    while True:
        print('\n' + '=' * 72)
        print(title)
        print('=' * 72)
        query = input('Search chat/channel name (blank = show everything): ').strip().lower()
        matches = [x for x in items if not query or query in x['name'].lower()]
        if forbidden_peer is not None:
            matches = [x for x in matches if x['peer'] != forbidden_peer]
        if not matches:
            print('No matches found.')
            continue

        print()
        for idx, item in enumerate(matches, 1):
            print(f"{idx:4}. [{item['kind']:<7}] {item['name']}")
        print()

        try:
            number = int(input('Select number: ').strip())
        except ValueError:
            print('Invalid selection.')
            continue
        if not (1 <= number <= len(matches)):
            print('Invalid selection.')
            continue

        selected = matches[number - 1]
        print(f"\nSelected: {selected['name']} ({selected['kind']})")
        confirm = input('Use this? [Y/n]: ').strip().lower()
        if confirm in ('', 'y', 'yes'):
            return selected


async def main():
    cfg = load_config()
    print('\n' + '=' * 60)
    print(' Telegram user-account login')
    print('=' * 60 + '\n')

    api_id = ask_api_id(cfg.get('api_id'))
    api_hash = ask_api_hash(cfg.get('api_hash'))
    client = TelegramClient(SESSION, api_id, api_hash)

    print('\nConnecting to Telegram...')
    await client.connect()
    if not await client.is_user_authorized():
        phone = ''
        while not phone:
            phone = input('Telegram phone number (include country code, e.g. +44...): ').strip()
        print('\nRequesting Telegram login code...')
        await client.send_code_request(phone)
        code = input('Telegram login code: ').strip().replace(' ', '')
        try:
            await client.sign_in(phone=phone, code=code)
        except SessionPasswordNeededError:
            # Visible input is intentional: some browser VPS consoles break hidden getpass prompts.
            password = input('Telegram 2FA password: ')
            await client.sign_in(password=password)

    me = await client.get_me()
    display_name = ' '.join(x for x in [getattr(me, 'first_name', ''), getattr(me, 'last_name', '')] if x)
    print('\n' + '=' * 60)
    print(' TELEGRAM LOGIN SUCCESSFUL')
    print('=' * 60)
    print(f'\nLogged in as: {display_name or me.id}')

    source = await choose_dialog(client, 'SELECT PROVIDER SOURCE')
    destination = await choose_dialog(
        client,
        'SELECT EA DESTINATION CHANNEL / GROUP',
        forbidden_peer=source['peer'],
    )

    cfg = {
        'api_id': api_id,
        'api_hash': api_hash,
        'source_peer_id': int(source['peer']),
        'source_name': source['name'],
        'dest_peer_id': int(destination['peer']),
        'dest_name': destination['name'],
    }
    save_config(cfg)

    print('\n' + '=' * 60)
    print(' BRIDGE CONFIGURATION SAVED')
    print('=' * 60)
    print(f"\nProvider source : {source['name']}")
    print(f"EA destination  : {destination['name']}")
    print(f'\nTelegram login session saved at: {SESSION}.session')
    print('Normal VPS/service restarts will not require another Telegram login.')
    await client.disconnect()


if __name__ == '__main__':
    asyncio.run(main())
