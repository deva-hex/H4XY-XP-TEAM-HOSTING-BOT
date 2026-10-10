# H4XY XP TEAM — Premium Hosting Telegram Bot

A single-process Telegram bot project for a hosting-selling workflow. The bot uses **aiogram 3** and **Firebase Firestore** and is configured for deployment as a persistent worker on Railway or in a Docker container.

> **Important:** GitHub stores your source code and runs the validation workflow. It is not a reliable always-on host for a Telegram long-polling bot. Push this repository to GitHub, then deploy the repository to Railway (or run the Docker image on your VPS).

## Features

- Premium-style Telegram inline menus and user profile/wallet views.
- Starter plans for Python, PHP, Node.js and Java; plans are seeded into Firestore on first run.
- Orders, renewals, support tickets, plan management, order review and delivery of hosting details by an admin.
- Wallet top-up request flow: amount → enabled payment method → UPI/QR or configured gateway checkout → screenshot → UTR/reference ID → admin review.
- Admin controls for UPI/gateway enable/disable, UPI ID/name, QR image, gateway API key/URL, plans, pending orders, balance requests, tickets, statistics and maintenance mode.
- Firestore transaction for wallet top-up approval to prevent duplicate credits on double-click/retry.
- GitHub Actions syntax/deployment-config validation on pushes and pull requests.

## Repository layout

```text
.
├── bot.py
├── requirements.txt
├── Procfile
├── railway.json
├── Dockerfile
├── .env.example
├── .gitignore
└── .github/workflows/validate.yml
```

## 1. Create and configure Firebase

1. Create a Firebase project in the Firebase console.
2. Create a **Cloud Firestore** database.
3. In Project settings → Service accounts, generate a private service-account key for server-side use.
4. Keep that JSON private. Do **not** commit it to GitHub or send it in chat.
5. For local development, save it as `firebase-service-account.json` in the project directory. The `.gitignore` excludes this file.

The bot will create its collections and starter plans when it starts. It uses collections including `users`, `plans`, `orders`, `balance_requests`, `settings` and `tickets`.

## 2. Configure Telegram

1. Create a bot with Telegram's `@BotFather` and copy its token.
2. Get your numeric Telegram user ID and use it as `ADMIN_ID`.
3. Never publish the bot token. If it has been exposed, revoke it with BotFather and create a new one.

## 3. Run locally

Python 3.11 or 3.12 is recommended.

```bash
python -m venv .venv
# Linux / macOS / Termux shell:
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with your values. The project loads `.env` locally; hosted platforms should use their Variables/Secrets settings. Set at minimum:

- `BOT_TOKEN`
- `ADMIN_ID`
- `GOOGLE_APPLICATION_CREDENTIALS` pointing to your service-account JSON, **or** `FIREBASE_SERVICE_ACCOUNT_JSON` containing the full JSON as a single environment-variable value.

Then run:

```bash
python bot.py
```

In Telegram, use `/start`; as the configured admin, use `/admin`.

## 4. Deploy from GitHub to Railway

1. Create a **private** GitHub repository and upload these project files. Do not upload `.env`, service-account JSON, API keys or real tokens.
2. In Railway, create a new project and deploy from the GitHub repository.
3. Railway should detect Python/Nixpacks. `railway.json` defines the worker start command as `python bot.py`.
4. In Railway service → Variables, add:

   - `BOT_TOKEN` — Telegram bot token
   - `ADMIN_ID` — your numeric Telegram user ID
   - `FIREBASE_SERVICE_ACCOUNT_JSON` — the **entire service-account JSON** as a single JSON value
   - optional `ADMIN_CONTACT`, `UPI_ID`, `UPI_NAME`, `CURRENCY`, `LOG_LEVEL`

5. Deploy/redeploy. Check Railway deployment logs for `Starting H4XY XP TEAM HOSTING with Firebase Firestore`.
6. Open the bot in Telegram and send `/start`; test admin commands with `/admin`.

For a VPS/Docker deployment, build with `docker build -t h4xy-hosting-bot .`, then run the container with the same required environment variables and a secure Firebase credential configuration.

## 5. Payment setup

Open Telegram `/admin` → **Payment Settings**:

- Toggle UPI and gateway on/off.
- Set UPI ID and receiver name.
- Upload a QR image. Users are sent that image during the UPI top-up flow.
- Set the gateway API key and HTTPS create-order endpoint if you have valid credentials for a supported provider.

For wallet top-up, the user selects an amount and method, sends a screenshot/photo, then submits the UTR/reference ID. The request remains pending until an admin checks the payment and approves it. Wallet balance is credited only after approval.

### Gateway note

The optional `FamGateway` code is a third-party integration, **not an official FamPay API**. Its create-order request/response format may differ by provider/account. Do not enable it with a random endpoint or unverified credentials. Confirm the provider's current documentation and test in a sandbox first. This project does not claim automatic payment verification from a screenshot, UTR, or checkout redirect; admin must verify the transaction in the provider/bank dashboard before approval. A production-grade automatic flow requires a verified signed webhook/status API and idempotency checks.

## 6. GitHub Actions

The workflow in `.github/workflows/validate.yml` runs on push and pull request. It checks Python syntax and validates `railway.json`. It does not run the bot or need production credentials.

## Security and operational notes

- Never commit real Telegram tokens, Firebase service-account keys, gateway keys, QR files containing private information, or `.env`.
- Use a private repository and restrict repository collaborators.
- The bot currently uses Telegram long polling, so deploy only one active worker instance per bot token to avoid duplicate polling conflicts.
- Firestore is the source of truth for orders and balances. Back up Firestore regularly.
- Hosting provisioning itself is manual: an admin delivers server/hosting details to the customer after verifying payment. This bot does not create VPS containers or deploy customer apps automatically.
- Run a real test with a test Telegram account and a small transaction before accepting customer payments.

## Troubleshooting

- **`BOT_TOKEN` missing:** add it to Railway Variables or your local shell.
- **`ADMIN_ID environment variable missing`:** set your numeric Telegram user ID.
- **Firebase credentials missing/invalid:** check the JSON formatting, private key newlines, and Firestore permissions.
- **Firestore permission/API error:** confirm Firestore is enabled and the service-account key belongs to the intended Firebase project.
- **Gateway checkout error:** confirm the provider's actual endpoint, API key, request schema and response fields. UPI/manual review remains the fallback when enabled.
