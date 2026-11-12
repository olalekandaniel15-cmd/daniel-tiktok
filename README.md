# DANIEL TIKTOK 2.0

Python Flask + HTML/CSS + SQLite starter project.

## Included in this build
- Registration/login with hashed passwords
- Short-video upload/feed, views, likes and comments
- Follow/unfollow and creator profiles
- Private text messaging and inbox
- Notifications for follows, likes, comments and messages
- Basic engagement-based feed ranking
- Creator dashboard and demo gift revenue ledger
- Advertising preference consent recording
- Camera preview for live-stream setup
- Camera preview and initial signaling-storage endpoints for call development

## Run locally
1. Install Python 3.10+.
2. Open terminal in this folder.
3. `python -m venv .venv`
4. Activate: Windows `.venv\\Scripts\\activate`; macOS/Linux `source .venv/bin/activate`
5. `pip install -r requirements.txt`
6. `python app.py`
7. Visit http://127.0.0.1:5000

Database `daniel_tiktok_v2.db` is created automatically.

## Owner contact
The registration form shows the requested email and phone as example placeholders:
olalekandaniel15@gmail.com and 08149650556. The owner account is not pre-created; register and set a password yourself.

## Owner payout account configuration
The backend is prepared to read the platform owner's payout destination from private server environment variables. Configure these in your hosting control panel (do not put them in public HTML or JavaScript):

- `OWNER_PAYOUT_PROVIDER=OPay`
- `OWNER_PAYOUT_ACCOUNT_NUMBER` = your account number (enter privately in Render)
- `OWNER_PAYOUT_ACCOUNT_NAME` = your account name (enter privately in Render)

These settings only record the intended payout destination for the platform. They do **not** activate transfers or connect OPay. A verified payment provider integration and a secure admin-only payout workflow are still required before real money can be received or withdrawn. Keep the account details private and confirm the account name/number with OPay before processing payments.

## Important limitations before launch
This is a development starter, not a production-ready global social network.
- Private messages are stored in the database but are not end-to-end encrypted.
- Video calling is a camera preview plus a basic signaling inbox; complete WebRTC peer negotiation, TURN/STUN and abuse controls are still required.
- Live streaming currently offers a local camera preview only. Add a media server (e.g. LiveKit or mediasoup) for multi-viewer streaming.
- Gift buttons create demo ledger entries only; no real money is charged or paid out.
- Recommendation ranking is a simple engagement/following score, not a trained AI model.
- Add CSRF protection, rate limits, moderation/reporting, secure upload scanning, privacy policy, terms, age controls and backups before public deployment.
- Set a strong `SECRET_KEY`, turn off debug mode, use HTTPS and a production WSGI server.
- For real payments, integrate Paystack or Flutterwave and verify payment webhooks server-side. Never trust a browser redirect as proof of payment.
- For advertising, use contextual ads or consent-based personalization. Do not sell private messages, phone numbers, precise location or identifiable watch histories. Provide clear consent and opt-out controls and comply with applicable privacy laws, including Nigeria's NDPA where applicable.


## Deploy to Render (free starter)
1. Upload this folder's contents to a GitHub repository (not the ZIP file itself).
2. In Render, choose **New +** -> **Blueprint** and connect that GitHub repository, or create a **Web Service**.
3. For a Web Service choose **Python**; build command: `pip install -r requirements.txt`; start command: `gunicorn app:app`.
4. Deploy. Render will provide an `https://....onrender.com` URL.
5. In Render's Environment settings, set `OWNER_PAYOUT_PROVIDER`, `OWNER_PAYOUT_ACCOUNT_NUMBER`, and `OWNER_PAYOUT_ACCOUNT_NAME` privately if needed. Do not commit these values to GitHub.
6. Set a strong `SECRET_KEY` in Render if you create the service manually.

**Free-tier data warning:** this starter uses SQLite and stores uploaded videos on the local filesystem. Render free web services have ephemeral storage, so the database and uploaded videos can be lost on redeploy/restart. For a persistent public launch, migrate to a managed PostgreSQL database and object storage (such as S3-compatible storage) before accepting real users or payments. The free instance may also sleep when idle.
