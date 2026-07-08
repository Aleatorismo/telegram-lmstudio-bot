# AGENTS.md

## Project Summary

This project is a local bridge between a Telegram bot and an LM Studio model.

- Telegram traffic must go through the local HTTP proxy at `http://127.0.0.1:7890`.
- LM Studio traffic is local HTTP and must bypass the proxy.
- The bot uses long polling, not webhook delivery.
- Private chats are supported. Group-chat logic is not implemented.

## Runtime Flow

Main entrypoint: `main.py`

Startup flow:

1. Load and validate environment/config.
2. Set `NO_PROXY` / `no_proxy` so LM Studio local traffic stays direct.
3. Create persistent session store.
4. Create chat logger.
5. Create Telegram application and LM Studio client.
6. Start Telegram polling.

If Telegram startup fails with `telegram.error.NetworkError`, the process cleans up the failed application, waits, and retries.
If Telegram polling enters repeated network failure, the process cleans up and rebuilds the Telegram application.
Recoverable Telegram lifecycle errors such as an uninitialized `ExtBot` are treated as restart signals instead of process-fatal errors.

## Core Files

- `main.py`
  Starts the process, owns restart loop, catches startup `NetworkError` and recoverable Telegram lifecycle errors, cleans up failed applications, recreates the Telegram app when needed.

- `config.py`
  Loads `.env` / environment variables and validates all settings.

- `telegram_bot.py`
  Builds the Telegram application, handles `/start`, `/reset`, private text messages, long replies, and polling-error recovery signals.

- `lmstudio_client.py`
  Calls LM Studio OpenAI-compatible `/chat/completions`.

- `session_store.py`
  Stores per-user conversation memory in a single JSON state file with atomic replace-on-write semantics.

- `chat_logger.py`
  Writes human-readable chat transcripts to per-user text files.

## State and Persistence

There are two distinct local persistence layers:

- `SESSION_STORE_PATH`
  Machine-oriented JSON state file for conversation memory.
  This is the source of truth for context restoration across restarts.
  Keyed by Telegram `user_id`.

- `CHAT_LOG_DIR`
  Human-readable per-user `.txt` transcripts.
  Intended for inspection, not for context recovery.

`/reset` clears the current user's session memory from `SESSION_STORE_PATH` and appends a reset marker to that user's chat log file.

## Session Model

Conversation memory is per Telegram user ID.

- No shared memory between users.
- No dependence on Telegram chat history backfill.
- The bot does not read historical messages from Telegram servers.
- The bot only uses:
  - current inbound Telegram message
  - locally stored session history
  - configured system prompt

`MAX_HISTORY_MESSAGES` limits stored OpenAI-style message items, not turns.
One completed turn typically adds two items:

- one `user`
- one `assistant`

## LM Studio Request Shape

Base payload always includes:

- `model`
- `messages`
- `temperature`
- `max_tokens`
- `stream: false`

Optional sampling parameters are only sent when configured and non-empty:

- `top_p`
- `top_k`
- `min_p`
- `presence_penalty`

If these are unset in `.env`, they are omitted from the payload entirely so LM Studio preset values remain in effect.

## Telegram Networking Rules

Telegram uses explicit proxy configuration via `HTTPXRequest(proxy=...)`.

- Proxy target comes from `TELEGRAM_PROXY` or fallback `HTTP_PROXY` / `HTTPS_PROXY`.
- `trust_env=False` is used for Telegram HTTP clients.
- LM Studio also uses `trust_env=False`, so local HTTP requests do not accidentally inherit system proxy behavior.

## Recovery Behavior

There are two different Telegram recovery paths:

1. Startup/bootstrap failure
   If `run_polling()` fails during initial Telegram bootstrap because the proxy chain is down, `main.py` catches `telegram.error.NetworkError`, performs best-effort application cleanup, waits `TELEGRAM_RESTART_DELAY`, and retries from scratch.

2. Runtime polling failure
   If polling repeatedly hits `NetworkError` inside a rolling time window, `telegram_bot.py` marks the app for restart and stops the current polling loop. `main.py` then performs best-effort application cleanup and rebuilds the Telegram application.

3. Telegram lifecycle state failure
   If `python-telegram-bot` raises a recoverable lifecycle `RuntimeError`, such as `ExtBot is not properly initialized` or `Application is not initialized`, `main.py` treats it as a restart signal, cleans up the current application, and creates a fresh application on the next loop.

Important implementation detail:

- `run_polling(..., close_loop=False)` is required.
- The outer restart loop depends on the event loop staying open across bot restarts.
- Cleanup is best-effort: if `Application.stop()` or `Application.shutdown()` raises because the object is only partially initialized, the failure is logged at debug level and the next loop still creates a new application instance.

## Message Handling

- Only private text messages are processed.
- Empty text is rejected.
- Long replies are split to respect Telegram message size limits.
- While LM Studio is generating, the bot periodically sends `typing...`.

## Key Config Variables

Required:

- `TELEGRAM_BOT_TOKEN`
- `LMSTUDIO_MODEL`
- Telegram proxy via `TELEGRAM_PROXY` or `HTTP_PROXY` / `HTTPS_PROXY`

Important defaults:

- `LMSTUDIO_BASE_URL=http://127.0.0.1:1234/v1`
- `LMSTUDIO_TIMEOUT=900`
- `MAX_HISTORY_MESSAGES=20`
- `CHAT_LOG_DIR=chat_logs`
- `SESSION_STORE_PATH=session_store.json`
- `TELEGRAM_TYPING_INTERVAL=4`
- `TELEGRAM_NETWORK_ERROR_THRESHOLD=4`
- `TELEGRAM_NETWORK_ERROR_WINDOW=120`
- `TELEGRAM_RESTART_DELAY=3`

## Running

Typical local run:

```powershell
conda activate telegram-lmstudio-bot
python main.py
```

## Tests

Test suite location: `tests/`

Coverage areas currently include:

- config parsing and defaults
- optional LM Studio sampling parameters
- polling recovery threshold logic
- Telegram application cleanup during restart
- recoverable Telegram lifecycle error handling
- session persistence and user isolation
- chat log writing
- reply splitting
- restart-safe polling wrapper behavior

Run tests with:

```powershell
pytest
```

## Maintenance Notes

- Keep `session_store.json` if you want to preserve conversation memory across restarts.
- Deleting `chat_logs/` does not delete actual conversation memory.
- Deleting `session_store.json` resets all persisted memory for all users.
- If changing restart logic, re-check startup failure, runtime polling failure, recoverable lifecycle failure, and best-effort cleanup paths.
- If changing LM Studio request fields, preserve the rule that unset optional sampling parameters must not be sent.
