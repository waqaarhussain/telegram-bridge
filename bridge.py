#!/usr/bin/env python3
import asyncio
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

from telethon import TelegramClient, events, utils

BASE = Path('/opt/forexpert-bridge')
CONFIG = BASE / 'config.json'
SESSION = str(BASE / 'telegram_session')
DBFILE = BASE / 'bridge.sqlite3'
VERSION = '2.1'


def load_config():
    if not CONFIG.exists():
        raise RuntimeError('config.json missing. Run bridge-config.')
    return json.loads(CONFIG.read_text())


CFG = load_config()
API_ID = int(CFG['api_id'])
API_HASH = CFG['api_hash']
SOURCE_PEER_ID = int(CFG['source_peer_id'])
DEST_PEER_ID = int(CFG['dest_peer_id'])

client = TelegramClient(SESSION, API_ID, API_HASH)
db = sqlite3.connect(DBFILE)
db.execute('PRAGMA journal_mode=WAL')
db.execute('''
CREATE TABLE IF NOT EXISTS processed_messages (
    source_peer INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    PRIMARY KEY(source_peer, message_id)
)
''')
db.execute('''
CREATE TABLE IF NOT EXISTS workflows (
    provider_id TEXT PRIMARY KEY,
    root_message_id INTEGER NOT NULL,
    side TEXT NOT NULL,
    entry1 REAL NOT NULL,
    entry2 REAL NOT NULL,
    tp1 REAL NOT NULL,
    tp2 REAL NOT NULL,
    sl REAL NOT NULL,
    state TEXT NOT NULL,
    updated_at INTEGER NOT NULL
)
''')
db.commit()

TERMINAL_STATES = {'cancelled', 'closed'}


def clean(text):
    return (text or '').replace('\r', '\n').replace('–', '-').replace('—', '-').replace('−', '-')


def fmt(value):
    out = f'{float(value):.10f}'.rstrip('0').rstrip('.')
    return out or '0'


def already_processed(message_id):
    row = db.execute(
        'SELECT 1 FROM processed_messages WHERE source_peer=? AND message_id=?',
        (SOURCE_PEER_ID, int(message_id)),
    ).fetchone()
    return row is not None


def mark_processed(message_id):
    db.execute(
        'INSERT OR IGNORE INTO processed_messages(source_peer,message_id) VALUES(?,?)',
        (SOURCE_PEER_ID, int(message_id)),
    )
    db.commit()


def provider_id(root_message_id):
    return f'{abs(SOURCE_PEER_ID)}_{int(root_message_id)}'


def workflow_get(pid):
    row = db.execute(
        'SELECT provider_id,root_message_id,side,entry1,entry2,tp1,tp2,sl,state,updated_at FROM workflows WHERE provider_id=?',
        (pid,),
    ).fetchone()
    if not row:
        return None
    keys = ('provider_id','root_message_id','side','entry1','entry2','tp1','tp2','sl','state','updated_at')
    return dict(zip(keys, row))


def workflow_upsert(pid, root_message_id, signal, state=None):
    existing = workflow_get(pid)
    next_state = state or (existing['state'] if existing else 'waiting')
    db.execute('''
        INSERT INTO workflows(provider_id,root_message_id,side,entry1,entry2,tp1,tp2,sl,state,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(provider_id) DO UPDATE SET
            root_message_id=excluded.root_message_id,
            side=excluded.side,
            entry1=excluded.entry1,
            entry2=excluded.entry2,
            tp1=excluded.tp1,
            tp2=excluded.tp2,
            sl=excluded.sl,
            state=excluded.state,
            updated_at=excluded.updated_at
    ''', (
        pid, int(root_message_id), signal['side'], signal['entry1'], signal['entry2'],
        signal['tp1'], signal['tp2'], signal['sl'], next_state, int(time.time()),
    ))
    db.commit()


def workflow_set_state(pid, state):
    db.execute('UPDATE workflows SET state=?, updated_at=? WHERE provider_id=?', (state, int(time.time()), pid))
    db.commit()


def workflow_set_tp2(pid, tp2):
    db.execute('UPDATE workflows SET tp2=?, updated_at=? WHERE provider_id=?', (float(tp2), int(time.time()), pid))
    db.commit()


def signal_from_workflow(wf):
    return {
        'side': wf['side'],
        'entry1': wf['entry1'],
        'entry2': wf['entry2'],
        'tp1': wf['tp1'],
        'tp2': wf['tp2'],
        'sl': wf['sl'],
    }


def parse_signal(text):
    upper = clean(text).upper()
    if not re.search(r'\bXAU\s*/?\s*USD\b', upper):
        return None

    side_match = re.search(r'\b(BUY|SELL)\b', upper)
    entry_match = re.search(
        r'ENTRY\s*ZONE\s*[:=\-]?\s*([0-9]+(?:\.[0-9]+)?)\s*(?:/|\bTO\b|\-)\s*([0-9]+(?:\.[0-9]+)?)',
        upper,
        re.I | re.S,
    )
    tp1_match = re.search(r'\bTP\s*1\s*[:=\-]?\s*([0-9]+(?:\.[0-9]+)?)', upper, re.I)
    tp2_match = re.search(r'\bTP\s*2\s*[:=\-]?\s*([0-9]+(?:\.[0-9]+)?)', upper, re.I)
    sl_match = re.search(
        r'(?:STOP\s*LOSS|S\s*/?\s*L|\bSL\b)\s*[:=\-]?\s*([0-9]+(?:\.[0-9]+)?)',
        upper,
        re.I,
    )
    if not all((side_match, entry_match, tp1_match, tp2_match, sl_match)):
        return None

    return {
        'side': side_match.group(1),
        'entry1': float(entry_match.group(1)),
        'entry2': float(entry_match.group(2)),
        'tp1': float(tp1_match.group(1)),
        'tp2': float(tp2_match.group(1)),
        'sl': float(sl_match.group(1)),
    }


def parse_tp2_change(text):
    upper = clean(text).upper()
    patterns = [
        r'\b(?:CHANGE|UPDATE|MODIFY|ADJUST|SET|NEW)\s+(?:THE\s+)?TP\s*2(?:\s+TP)?\s*(?:TO|AT|=|:)?\s*([0-9]+(?:\.[0-9]+)?)',
        r'\bTP\s*2\s+(?:CHANGED|UPDATED|MODIFIED|ADJUSTED|MOVED|SET)\s*(?:TO|AT|=|:)?\s*([0-9]+(?:\.[0-9]+)?)',
        r'\bTP\s*2\s*(?:IS\s+NOW|NOW)\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)',
        r'\b(?:CHANGE|UPDATE|MODIFY|ADJUST|SET|NEW)\s+(?:THE\s+)?(?:TAKE\s+PROFIT|TP)\s*(?:TO|AT|=|:)?\s*([0-9]+(?:\.[0-9]+)?)',
        r'\b(?:TAKE\s+PROFIT|TP)\s+(?:IS\s+NOW|NOW)\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)',
    ]
    for pattern in patterns:
        m = re.search(pattern, upper, re.I)
        if m:
            return float(m.group(1))
    return None


def classify_update(text):
    upper = clean(text).upper()

    # Provider may manually close TP1 instead of saying TP1 HIT.
    # For this strategy, that is the trigger to enter now.
    if (
        re.search(r'\b(?:MANUALLY\s+|MANUAL\s+)?CLOSE\s+(?:THE\s+)?TP\s*1\b', upper)
        or re.search(r'\b(?:MANUALLY\s+|MANUAL\s+)?CLOSED\s+(?:THE\s+)?TP\s*1\b', upper)
        or re.search(r'\bTP\s*1\s+(?:IS\s+|HAS\s+BEEN\s+)?(?:MANUALLY\s+)?CLOSED\b', upper)
        or re.search(r'\b(?:MANUALLY\s+|MANUAL\s+)?CLOSE\s+(?:THE\s+)?FIRST\s+TP\b', upper)
        or re.search(r'\b(?:MANUALLY\s+|MANUAL\s+)?CLOSE\s+(?:THE\s+)?FIRST\s+TAKE\s+PROFIT\b', upper)
        or re.search(r'\bFIRST\s+(?:TP|TAKE\s+PROFIT)\s+(?:IS\s+|HAS\s+BEEN\s+)?CLOSED\b', upper)
    ):
        return 'TP1_HIT'

    if (
        re.search(r'\bMANUALLY\s+CLOSE\s+TP\s*2\b', upper)
        or re.search(r'\bMANUAL\s+CLOSE\s+TP\s*2\b', upper)
    ):
        return 'MANUAL_TP2_CLOSE'

    if (
        'BREAK EVEN HIT' in upper
        or 'BREAKEVEN HIT' in upper
        or 'BREAK-EVEN HIT' in upper
        or re.search(r'\bBE\s+HIT\b', upper)
    ):
        return 'BREAK_EVEN_HIT'

    if (
        'STOP LOSS HIT' in upper
        or 'STOPLOSS HIT' in upper
        or re.search(r'\bSL\s+HIT\b', upper)
    ):
        return 'SL_HIT'

    if (
        'TP1 HIT' in upper
        or 'TP 1 HIT' in upper
        or 'TP1HIT' in upper
        or 'TP1 REACHED' in upper
        or 'TP 1 REACHED' in upper
    ):
        return 'TP1_HIT'

    # Deliberately command-shaped only. Result chatter such as "closed +500 pips"
    # does not match these expressions.
    if (
        re.search(r'^\s*(?:PLEASE\s+)?(?:CLOSE|EXIT)(?:\s+(?:THIS|THE))?\s*(?:TRADE|POSITION)?\s*(?:NOW)?\s*[!✅❌⚠️.]*\s*$', upper)
        or re.search(r'\b(?:MANUALLY|MANUAL)\s+CLOSE\s+(?:THE\s+)?(?:TRADE|POSITION)\b', upper)
        or re.search(r'\bCLOSE\s+(?:THE\s+)?(?:TRADE|POSITION)\s+NOW\b', upper)
        or re.search(r'\bEXIT\s+(?:THE\s+)?(?:TRADE|POSITION)\s+NOW\b', upper)
    ):
        return 'CLOSE'

    return None


async def resolve_peer(peer_id):
    me = await client.get_me()
    if utils.get_peer_id(me) == peer_id:
        return me
    async for dialog in client.iter_dialogs():
        if utils.get_peer_id(dialog.entity) == peer_id:
            return dialog.entity
    raise RuntimeError(f'Could not resolve Telegram peer {peer_id}')


async def find_original_signal(message, source_entity, max_depth=20):
    current = message
    visited = set()
    for _ in range(max_depth):
        reply_id = getattr(current, 'reply_to_msg_id', None)
        if not reply_id:
            return None, None
        reply_id = int(reply_id)
        if reply_id in visited:
            return None, None
        visited.add(reply_id)
        parent = await client.get_messages(source_entity, ids=reply_id)
        if not parent:
            return None, None
        signal = parse_signal(parent.raw_text or '')
        if signal:
            return parent, signal
        current = parent
    return None, None


async def send_to_ea(destination_entity, payload):
    await client.send_message(destination_entity, payload, parse_mode=None, link_preview=False)


def build_signal_payload(pid, signal):
    return (
        'FXP_EVENT=SIGNAL\n'
        f'PROVIDER_ID={pid}\n'
        f"SIDE={signal['side']}\n"
        f"ENTRY1={fmt(signal['entry1'])}\n"
        f"ENTRY2={fmt(signal['entry2'])}\n"
        f"TP1={fmt(signal['tp1'])}\n"
        f"TP2={fmt(signal['tp2'])}\n"
        f"SL={fmt(signal['sl'])}"
    )


async def sync_signal(destination_entity, pid, root_message_id, signal, force_state=None):
    existing = workflow_get(pid)
    if existing and existing['state'] in TERMINAL_STATES:
        return False
    state = force_state or (existing['state'] if existing else 'waiting')
    workflow_upsert(pid, root_message_id, signal, state=state)
    await send_to_ea(destination_entity, build_signal_payload(pid, signal))
    return True


async def main():
    await client.connect()
    if not await client.is_user_authorized():
        print('ERROR: Telegram session is not authorised. Run: sudo bridge-config', flush=True)
        sys.exit(1)

    source_entity = await resolve_peer(SOURCE_PEER_ID)
    destination_entity = await resolve_peer(DEST_PEER_ID)

    print('=' * 72, flush=True)
    print(f'Telegram Bridge ONLINE v{VERSION} self-heal', flush=True)
    print(f"Provider : {CFG.get('source_name')} ({SOURCE_PEER_ID})", flush=True)
    print(f"EA chat  : {CFG.get('dest_name')} ({DEST_PEER_ID})", flush=True)
    print('=' * 72, flush=True)

    async def handle(event):
        message = event.message
        if not message:
            return
        message_id = int(message.id)
        if already_processed(message_id):
            return
        text = message.raw_text or ''

        try:
            # New source signal. Separate Telegram posts always get separate provider IDs,
            # even when all prices are identical.
            signal = parse_signal(text)
            if signal:
                pid = provider_id(message_id)
                existing = workflow_get(pid)
                if not existing or existing['state'] not in TERMINAL_STATES:
                    workflow_upsert(pid, message_id, signal, state=existing['state'] if existing else 'waiting')
                    await send_to_ea(destination_entity, build_signal_payload(pid, signal_from_workflow(workflow_get(pid))))
                    print(
                        f"SIGNAL -> provider_id={pid} {signal['side']} XAUUSD "
                        f"entry={fmt(signal['entry1'])}/{fmt(signal['entry2'])} "
                        f"tp1={fmt(signal['tp1'])} tp2={fmt(signal['tp2'])} sl={fmt(signal['sl'])}",
                        flush=True,
                    )
                else:
                    print(f'SIGNAL IGNORED terminal workflow -> provider_id={pid} state={existing["state"]}', flush=True)
                mark_processed(message_id)
                return

            tp2_change = parse_tp2_change(text)
            action = classify_update(text)
            if tp2_change is None and action is None:
                preview = clean(text).replace('\n', ' ').strip()
                if len(preview) > 140:
                    preview = preview[:137] + '...'
                print(f'IGNORED msg={message_id}: {preview}', flush=True)
                mark_processed(message_id)
                return

            root, root_signal = await find_original_signal(message, source_entity)
            if not root or not root_signal:
                label = 'CHANGE_TP2' if tp2_change is not None else action
                print(f'IGNORED {label} msg={message_id}: not linked to a valid XAU/USD signal', flush=True)
                mark_processed(message_id)
                return

            pid = provider_id(root.id)
            existing = workflow_get(pid)

            # If the bridge/EA missed the original signal while offline, recover its
            # full values from Telegram before sending the management event.
            if existing and existing['state'] in TERMINAL_STATES:
                print(f'IGNORED terminal workflow -> provider_id={pid} state={existing["state"]}', flush=True)
                mark_processed(message_id)
                return

            effective_signal = root_signal.copy()
            if existing:
                effective_signal['tp2'] = existing['tp2']

            if tp2_change is not None:
                effective_signal['tp2'] = tp2_change
                workflow_upsert(pid, root.id, effective_signal, state=existing['state'] if existing else 'waiting')
                await send_to_ea(destination_entity, build_signal_payload(pid, effective_signal))
                await send_to_ea(destination_entity, f'FXP_EVENT=CHANGE_TP2\nPROVIDER_ID={pid}\nTP2={fmt(tp2_change)}')
                print(f'CHANGE_TP2 -> provider_id={pid} tp2={fmt(tp2_change)}', flush=True)
                mark_processed(message_id)
                return

            # Re-sync before every actionable reply. On the EA this refreshes/rebuilds
            # the same provider-ID workflow instead of creating a different trade.
            await sync_signal(destination_entity, pid, root.id, effective_signal)
            existing = workflow_get(pid)

            if action == 'TP1_HIT':
                if existing and existing['state'] == 'triggered':
                    print(f'TP1_HIT DUPLICATE IGNORED -> provider_id={pid}', flush=True)
                    mark_processed(message_id)
                    return
                await send_to_ea(destination_entity, f'FXP_EVENT=TP1_HIT\nPROVIDER_ID={pid}')
                workflow_set_state(pid, 'triggered')

            elif action == 'SL_HIT':
                await send_to_ea(destination_entity, f'FXP_EVENT=SL_HIT\nPROVIDER_ID={pid}')
                workflow_set_state(pid, 'closed' if existing and existing['state'] == 'triggered' else 'cancelled')

            elif action in {'BREAK_EVEN_HIT', 'MANUAL_TP2_CLOSE', 'CLOSE'}:
                await send_to_ea(destination_entity, f'FXP_EVENT={action}\nPROVIDER_ID={pid}')
                workflow_set_state(pid, 'closed')

            print(f'{action} -> provider_id={pid} reply_msg={message_id} root_msg={root.id}', flush=True)
            mark_processed(message_id)

        except Exception as exc:
            # Do not mark failures as processed, so a transient send failure is visible
            # and can be retried/replayed instead of silently disappearing.
            print(f'ERROR processing msg={message_id}: {type(exc).__name__}: {exc}', flush=True)

    client.add_event_handler(handle, events.NewMessage(chats=source_entity))
    await client.run_until_disconnected()


if __name__ == '__main__':
    asyncio.run(main())
