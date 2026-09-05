# Microsoft Family Safety — Home Assistant integration (fixed fork)

A working fork of the archived Home Assistant custom integration
[`pantherale0`/`Mycrosys-Solutions`/`ha-familysafety`](https://github.com/Mycrosys-Solutions/ha-familysafety)
(domain `family_safety`). It exposes Microsoft Family Safety data — per-account
screen time and per-application usage (Windows / Xbox / mobile) — as Home
Assistant sensors, so you can track and automate on your family's device usage.

The upstream project was archived in October 2025 and its config-flow login
stopped working for many users. This fork fixes the login so the integration can
be set up again through the normal Home Assistant UI.

## What was broken

During setup the OAuth login often redirected to
`https://login.live.com/oauth20_desktop.srf?removed=true` — with **no `code=`** —
so Home Assistant reported `invalid_auth` and configuration failed. This happens
when the browser is already signed in to a Microsoft account: the authorization
request short-circuits and never returns an authorization code.

## What was fixed

1. **Login flow (the important one).** The authorization URL now includes
   `prompt=login`, which forces a clean sign-in and reliably returns a real
   `?code=...` on `oauth20_desktop.srf`. Paste that URL back into the config flow
   and setup completes — no external tools or pre-obtained tokens required.
2. **Home Assistant 2026.x compatibility.** Replaced the removed `FlowResult`
   with `ConfigFlowResult` and the removed `async_timeout` with the built-in
   `asyncio.timeout`, so the integration loads on current Home Assistant.
   (Verified by importing every module against Home Assistant 2026.7.0 +
   `pyfamilysafety==1.1.2`.)
3. **Optional refresh-token path.** For advanced / headless setups you can paste
   an existing Microsoft Family Safety `refresh_token` instead of doing the OAuth
   step. This is optional — the normal login flow above is all most users need.

## Installation (HACS)

1. HACS → three-dot menu → **Custom repositories**.
2. Add this repository's URL, category **Integration**. Download it.
3. Restart Home Assistant.
4. Settings → Devices & Services → **Add Integration** → *Microsoft Family Safety*.
5. Open the sign-in link shown in the dialog, log in with the **family organizer**
   Microsoft account, and when you land on the (blank) `oauth20_desktop.srf?code=…`
   page, copy the **full URL** and paste it into the **OAuth response URL** field.
   Do this promptly — the code is short-lived.
6. The integration creates screen-time and app-usage sensors per family member.

> Tip: if you still see `removed=true`, open the link in a fresh private/incognito
> window so no existing Microsoft session interferes.

## Credits & license

Fork of [`ha-familysafety`](https://github.com/Mycrosys-Solutions/ha-familysafety)
by pantherale0 / Mycrosys-Solutions, built on the
[`pyfamilysafety`](https://github.com/pantherale0/pyfamilysafety) library.
Licensed under the **MIT License** (see `LICENSE`); the original copyright is
retained.

This is a community fix and is not affiliated with or endorsed by Microsoft.

## Offline CI

GitHub Actions validates the tracked source inventory in `.github/source-check.json`.
Run `python -m pip install -r .github/requirements-ci.txt` followed by
`python .github/scripts/validate_source.py`. Python, JSON, YAML and shell files are
parsed without importing application code. Update the inventory when adding files.
Actions and dependencies are pinned. Passing syntax checks does not establish live
service behavior; CI must not use account credentials, private data or devices.

The official pinned hassfest action also validates integration metadata. There are
15 source/metadata files in the syntax inventory and no functional unit tests yet.
Neither check authenticates to Microsoft or proves OAuth, token refresh or sensor
updates against the live service.

Setup descriptions in all three translations use URL placeholders supplied by
the config flow, as required by hassfest. The rendered help and Microsoft login
links, including `prompt=login` and the OAuth redirect/scope, are unchanged.
