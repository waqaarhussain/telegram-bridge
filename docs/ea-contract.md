# EA message contract

The bridge posts plain-text structured messages into the selected destination Telegram channel. The MT5 EA reads that destination with its existing Telegram reader bot.

## Signal

```text
FXP_EVENT=SIGNAL
PROVIDER_ID=<source-peer>_<telegram-message-id>
SIDE=BUY|SELL
ENTRY1=<provider first entry-zone price>
ENTRY2=<provider second entry-zone price>
TP1=<provider TP1>
TP2=<provider TP2>
SL=<provider SL>
```

A new signal is a waiting workflow only. The EA does not enter until `TP1_HIT` is received for the same provider ID.

## Entry trigger

```text
FXP_EVENT=TP1_HIT
PROVIDER_ID=<same-id>
```

The bridge maps ordinary TP1-hit wording and provider wording such as `Manually close TP1 ...` to this event.

## SL hit

```text
FXP_EVENT=SL_HIT
PROVIDER_ID=<same-id>
```

Before TP1 this cancels the waiting workflow. If the provider ID is already live, the EA can apply its live-workflow close behaviour.

## Break-even / manual close / generic close

```text
FXP_EVENT=BREAK_EVEN_HIT
PROVIDER_ID=<same-id>
```

```text
FXP_EVENT=MANUAL_TP2_CLOSE
PROVIDER_ID=<same-id>
```

```text
FXP_EVENT=CLOSE
PROVIDER_ID=<same-id>
```

All are exact-provider-ID events. Identical-price signals remain independent because each original Telegram post has a different Telegram message ID.

## Change TP2

```text
FXP_EVENT=CHANGE_TP2
PROVIDER_ID=<same-id>
TP2=<new provider TP2>
```

The bridge also refreshes the full `SIGNAL` payload with the amended TP2. The EA applies its configured Gold Worse TP buffer to the provider TP2.

## Self-heal

For a management reply, the bridge follows Telegram's reply chain back to the original XAU/USD signal and re-sends the full `SIGNAL` before the management event. This allows the EA to rebuild a workflow if the original post arrived while the bridge/EA was offline.
