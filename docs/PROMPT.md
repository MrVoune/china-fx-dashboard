# Prompt used to produce the dashboard

Tool: Claude Code (Claude desktop app, Code tab). The assignment text was supplied as an image; the conversation had two phases.

## Phase 1: scoping (discussion before building)

> Help me complete this assignment. We can first discuss the approach. I want to build a dashboard for China.

Follow-up decisions given to the agent:

> 1. The core question is fine. 2. English only. 3. Yes, use my connected GitHub account. 4. Let's discuss the indicators further, and combine them with our earlier assignment (international cost of capital). I care more about exchange rates, interest rates, the real exchange rate (RER) and the like.
>
> The foreign-reserves indicator can be replaced with productivity data; add both GDP and PMI. Use direct downloads from the Federal Reserve and BIS instead, no API key.

Core question agreed on: *Is the renminbi under depreciation pressure, and how do interest-rate and inflation gaps with the US shape its nominal and real value?*

## Phase 2: build instruction (what the agent was asked to deliver)

> Build a static, English-only dashboard for China with 4-8 indicators from primary sources or international organisations (Fed H.10, BIS, OECD, World Bank, NBS, US Treasury, ChinaBond). For every chart show units, frequency, source, latest observation date, exchange-rate quotation convention, and any transformation. Refresh automatically on a schedule using GitHub Actions and host on GitHub Pages. Show the last successful refresh time separately from each series' latest observation date. No API keys. Verify at least one observation from every series against its original source via an independent path, and keep a log demonstrating a successful refresh.

Design constraints applied: one y-axis per chart (no dual axes), fixed colour per entity (China blue, US orange), legend plus direct end labels, table view for each chart, light/dark themes, mobile layout.
