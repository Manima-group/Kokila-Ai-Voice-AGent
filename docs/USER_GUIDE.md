# Kokila User Guide

## Signing in
- **New organization:** open the app → **Start free trial** → company, your name, work email, password (10+ characters with letters and digits). You become the organization's Company Admin and land on the **Overview**.
- **Existing account:** **Sign in** with your email and password. Team members get a temporary password from their admin.
- After five wrong passwords the account locks for 15 minutes. Password-reset email is not available yet; ask your admin to re-invite you.

## Overview — "What would you like to do?"
Two product cards: **Calling Agent** and **Business Assistant**, with live figures when available. A card marked **Locked** is not in your organization's subscription: admins see **Upgrade or request access**, others are asked to contact their admin. The Integrations strip shows which apps are really connected (green dot). Use **Back to Overview** or the product switcher to move between products without signing in again.

## Calling Agent
Overview · AI Agent Builder · Voice testing · Phone numbers · Call history (transcripts, recordings) · Outbound campaigns · Contacts · Leads · Appointments · Analytics · Automations.
Typical path: **AI Agent Builder → New agent** (pick a template) → edit greeting, languages, rules, knowledge → **Publish** → **Voice testing → Run simulation** (mock mode, no real call) → **Phone numbers** → assign the agent. Outbound campaigns only dial contacts with recorded consent for the campaign purpose, between 9 AM and 9 PM IST.

## Business Assistant
- **Business mode:** ask "What were today's sales?", "Which products are low in stock?", "How many invoices are overdue?". Answers come only from connected systems and show KPI cards, charts, tables, a CSV download and the data source. **Quick reports** work even when the AI model is not configured.
- Actions that change data (e.g. creating a follow-up task) show an **Approval needed** card; nothing changes until you press **Approve**.
- **Personal mode:** private chats, reminders and memory. When the assistant suggests remembering something, it is saved only if you press **Remember**; delete memories any time.
- **Voice:** the microphone starts **muted**. Press the mic button to talk; press again to mute (capture stops immediately). The speaker button mutes spoken replies without stopping text answers. Speaking while Kokila talks interrupts it. Choose Telugu, Hindi or English in the language menu; quality depends on your browser (Chrome or Edge recommended).
- **Preferences** (Business Assistant → Home): language, response length, and — if your plan includes it — a custom assistant name and wake phrase (works only while the tab is open and the mic is unmuted).

## Integrations
Integrations → choose a connector → enter the requested details → **Save and test**. Only a successful test marks it Connected. **Test connection** re-checks; **Revoke** deletes stored credentials. See `docs/INTEGRATION_GUIDE.md`.

## Notifications, billing, settings
- The bell shows reminders and "caller asked for a human" alerts.
- **Billing:** plan, minutes used, upgrades (Razorpay), invoices. Plans activate only after Razorpay confirms payment.
- **Settings:** organization profile, outbound emergency stop, telecom compliance profile, data retention, links to **Team** and **Audit log**.
- **Sign out** from the profile menu (top right).
