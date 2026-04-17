# browser_cdp_tool

## Current status

The working extraction logic is now implemented in `browser_cdp_tool.py`.

What is in the Python script now:
- dynamic Robinhood tab discovery via CDP target list
- stdlib-only raw DevTools websocket execution
- extraction of Robinhood auth state from browser storage
- direct authenticated API calls for equities and crypto holdings
- batch quote lookup and market-value calculation logic
- formatted holdings JSON output with retrieval/source metadata
- shallow/deep portfolio modes
- read-only crypto order panel extraction for buy/sell views
- `tabs`, `eval`, and `portfolio` commands

What is **not** in the Python script yet:
- cash/account balances command
- options positions command
- open orders command
- historical performance command

Deep-mode details currently collected:
- per-holding detail page extraction by navigating the live Robinhood tab
- `about`
- `key_statistics`
- `related_lists`
- `trading_trends` for `Robinhood`, `Hedge funds`, and `Insiders`
- `history`
- `people_also_own`

Deep-mode safeguards currently present:
- shallow is the default mode
- deep must be explicitly requested with `--mode deep` or `--deep`
- deep mode defaults to enriching only the top 5 holdings by market value
- full deep enrichment across all holdings requires explicit `--deep-full`
- per-detail delay is configurable with `--detail-delay-seconds`
- capped validation / partial deep runs are supported with `--max-deep-holdings`
- JSON artifact-first workflow avoids repeat queries from downstream consumers

Read-only crypto panel command:
- `browser_cdp_tool crypto-panel --symbol BTC --side buy`
- `browser_cdp_tool crypto-panel --symbol BTC --side sell`

Current crypto panel extraction fields:
- `panel_title`
- `headline_price_usd`
- `lines`
- `inputs`
- `selects`
- `buttons`
- `field_map`
- `detail_url`
- `page_title`
- `spread_modal` when available

Safety boundary:
- this command is read-only
- it does not click `Review order`, `Submit buy`, or `Submit sell`
- it may switch between buy/sell tabs and inspect visible UI state only

What is in the bash wrapper now:
- per-run DIL log files under `_shared/domains/${DOMAIN_NAME}/logs/browser_cdp_tool/`
- per-run DIL data artifacts under `_shared/domains/${DOMAIN_NAME}/data/browser_cdp_tool/`
- action-based filenames of the form `<script_name>.<action>.<YYYYMMDD-HHMMSS>.<ext>`
- stable latest-per-action data artifact files
- richer start/end log banners with timestamps, duration, file paths, git identifiers, Obsidian links, and stdout/stderr capture
- default gridless `portfolio` report emitted to console and log unless suppressed with `--quiet-report`
- compact per-holding trends generated from intraday historical data in a 16-cell connector-style line spark renderer for a lighter visual profile

## Correct query methods determined from live Robinhood tab

These were determined by querying the active `Investing | Robinhood` page via Chrome DevTools Protocol on port `9222`.

### 1. Find the Robinhood tab via CDP

Use:
- `http://127.0.0.1:9222/json/list`

Identify the page entry with:
- `title: "Investing | Robinhood"`
- `url: "https://robinhood.com/?classic=1"`

Important fields:
- `id`
- `webSocketDebuggerUrl`

Example page target used during validation:
- `ws://127.0.0.1:9222/devtools/page/07010C2127005FDEF5B4637629CF160B`

### 2. Use raw DevTools websocket when `agent-browser --cdp` is unreliable

`agent-browser` help was available, but `agent-browser --cdp 9222 ...` did not connect reliably in this session even though the CDP endpoint itself was live.

Working fallback:
- connect directly to the target page's `webSocketDebuggerUrl`
- send `Runtime.evaluate`
- set `awaitPromise: true` when evaluating async JavaScript
- set `returnByValue: true` when expecting JSON/string results

This method successfully read:
- page title and text
- window globals
- localStorage auth state
- performance resource URLs

### 3. Inspect storage and resource activity first

Useful probes:

- `localStorage.getItem("web:auth_state")`
- `Object.keys(localStorage)`
- `performance.getEntriesByType("resource")`

Key discovery:
- Robinhood auth state was present in `localStorage["web:auth_state"]`

This JSON contained:
- `access_token`
- `read_only_secondary_access_token`
- `token_type`
- `user_uuid`

The direct in-page `fetch(..., { credentials: "include" })` calls returned unauthenticated responses in this session.

Working approach:
- extract token from `web:auth_state`
- make direct HTTPS requests outside the browser context
- pass `Authorization: Bearer <token>`

Prefer the read-only secondary token when possible.

## Working Robinhood endpoints

### Equities positions

Owned stock and ETF positions:
- `https://api.robinhood.com/positions/?account_number=<ACCOUNT_NUMBER>&nonzero=true`

Important fields returned per position:
- `instrument_id`
- `symbol`
- `quantity`
- `average_buy_price`
- `account_number`
- `type`

This is the primary authoritative list of nonzero equity holdings.

### Equity quotes

Current quote lookup for equities:
- `https://api.robinhood.com/marketdata/quotes/?bounds=24_5&ids=<instrument_id_csv>&include_bbo_source=true&include_inactive=false`

Preferred price selection order used:
1. `last_extended_hours_trade_price`
2. `last_trade_price`
3. `previous_close`

Important fields:
- `instrument_id`
- `symbol`
- `last_trade_price`
- `last_extended_hours_trade_price`
- `previous_close`

### Crypto holdings

Owned crypto positions:
- `https://nummus.robinhood.com/holdings/`

Important fields returned per holding:
- `currency.code`
- `currency.name`
- `currency_pair_id`
- `quantity`
- `quantity_available`
- `quantity_staked`

This is the authoritative list of crypto holdings.

Notable correction confirmed from API data:
- `TRUMP` is crypto, because it appears under `nummus` holdings with `currency.type = "cryptocurrency"`

### Crypto quotes

Current crypto quote lookup:
- `https://api.robinhood.com/marketdata/forex/quotes/?ids=<currency_pair_id_csv>`

Preferred price selection order used:
1. `mark_price`
2. `ask_price`
3. `bid_price`

Important fields:
- `id` (matches `currency_pair_id`)
- `symbol` like `TRUMPUSD`
- `mark_price`
- `ask_price`
- `bid_price`

## Working data assembly logic

### Final holdings algorithm

1. Read Robinhood tab target from CDP.
2. Read `localStorage["web:auth_state"]` from the Robinhood page.
3. Parse token JSON.
4. Query equities positions endpoint.
5. Query crypto holdings endpoint.
6. Collect all equity `instrument_id` values.
7. Collect all crypto `currency_pair_id` values.
8. Query equity quote endpoint in batch.
9. Query crypto quote endpoint in batch.
10. Join position rows to quote rows by ID.
11. Calculate `market_value_usd = quantity * selected_price`.
12. Sort descending by market value.

### Formatting notes

Use string formatting appropriate to the asset class and magnitude.

Observed good formatting rules:
- stocks >= 1 USD price: `2` decimals
- crypto under 1 USD: `4` or `8` decimals as needed
- quantities should preserve fractional ownership without trailing noise

Examples where extra precision matters:
- `SHIB` price should not round to `0.00`
- `BTC` quantity should preserve very small fractional units

### Value caveat

The derived holdings total from positions plus live quotes in this session was about `$1,992.37`.

This is **not** the same as the top-level Robinhood account figure visible in the page body during earlier DOM extraction.

Possible reasons:
- the page shows broader account value than just these owned positions
- some assets or account buckets are represented elsewhere
- some UI value may include cash, interest-bearing cash, managed products, or other account types

Do not assume page-level portfolio total equals just `positions + nummus holdings`.

## Additional useful endpoints discovered from Robinhood network activity

These may be useful for future `browser_cdp_tool` functionality:

- `https://api.robinhood.com/accounts/`
- `https://api.robinhood.com/accounts/?default_to_all_accounts=true`
- `https://api.robinhood.com/accounts/?default_to_all_accounts=true&include_managed=true&include_multiple_individual=true&is_default=false`
- `https://api.robinhood.com/portfolios/<ACCOUNT_NUMBER>/`
- `https://nummus.robinhood.com/accounts/`
- `https://nummus.robinhood.com/portfolios/<UUID>/`
- `https://bonfire.robinhood.com/accounts/<ACCOUNT_NUMBER>/unified/`
- `https://bonfire.robinhood.com/portfolio/<ACCOUNT_NUMBER>/positions_v2?instrument_type=EQUITY&positions_location=HOME_TAB`
- `https://api.robinhood.com/options/aggregate_positions/?account_numbers=<ACCOUNT_NUMBER>&nonzero=True`
- `https://api.robinhood.com/orders/`
- `https://api.robinhood.com/options/orders/?account_numbers=<ACCOUNT_NUMBER>&states=...`
- `https://api.robinhood.com/combo/orders/?account_numbers=<ACCOUNT_NUMBER>&states=...`
- `https://bonfire.robinhood.com/portfolio/performance/<ACCOUNT_NUMBER>?chart_style=PERFORMANCE&chart_type=historical_portfolio&display_span=day&include_all_hours=true`
- `https://bonfire.robinhood.com/crypto/details/position/<currency_pair_id>/`
- `https://api.robinhood.com/discovery/lists/default/`
- `https://api.robinhood.com/discovery/lists/user_items/`

Likely future features enabled by these endpoints:
- cash and account balances
- account metadata and account selection
- options holdings
- open orders
- historical performance
- watchlists
- crypto position details

## Practical implementation notes for the script

### Recommended architecture

Implement these internal steps in `browser_cdp_tool.py`:

1. `list_tabs_via_http()`
2. `find_robinhood_tab()`
3. `eval_via_websocket(target_ws_url, expression, await_promise=False)`
4. `get_robinhood_auth_state()`
5. `http_get_json(url, bearer_token)`
6. `get_equity_positions(account_number, token)`
7. `get_crypto_holdings(token)`
8. `get_equity_quotes(instrument_ids, token)`
9. `get_crypto_quotes(currency_pair_ids, token)`
10. `build_holdings_summary(...)`

### Avoid relying on DOM scraping for holdings

The DOM approach is fragile because:
- visible text includes watchlists and non-holdings content
- number parsing is ambiguous
- the layout is highly dynamic
- market values and quantities are not reliably grouped in text nodes

Use authenticated API-backed extraction instead.

### Avoid assuming tab index stability

The older script calls:
- `tab 0`

This is brittle.

Use title/url matching from `http://127.0.0.1:9222/json/list` to find the Robinhood page dynamically.

### Security handling

Auth tokens extracted from storage are highly sensitive.

Implementation guidance:
- do not print raw tokens to stdout
- do not log raw tokens in DIL logs
- if logging is needed, redact token values
- prefer in-memory use only

## What should be moved into the actual script next

Minimum next implementation set:
- replace DOM-based `portfolio` logic with token-backed API extraction
- resolve Robinhood tab dynamically by title/url
- read `web:auth_state` over raw CDP websocket
- batch quote lookup for equities and crypto
- return clean JSON with:
  - `symbol`
  - `type`
  - `quantity`
  - `price_usd`
  - `market_value_usd`
- optionally include account cash in a separate command, not mixed into holdings

## Answer to the direct question

Is the working logic all stored in our script now?

No.

The current script still contains the earlier DOM-scraping portfolio logic. The correct API-backed query method and token extraction flow are documented here, but still need to be implemented into `browser_cdp_tool.py`.
