# Push reminders through ntfy

[Svenska](push-reminders.sv.md)

<!-- description: Turn on reminders to the phone. The server sends wake-ups with no content through ntfy, and the phone fetches what to show by itself. -->

Turn on reminders to the phone. The server sends wake-ups with no content through ntfy, and the phone fetches what to show by itself.

1. The API and the push worker both run with `SIDEKICK_PUSH_ENABLED=true`. The worker is a separate process:
   `sidekick-push-worker` (self-hosted: `docker compose --env-file selfhost.env --profile push up -d`; from a
   checkout: `uv run --project backend sidekick-push-worker`). It must keep running.
2. The ntfy app is installed on the phone. When the app is paired and notifications are allowed, it
   registers the phone's UnifiedPush endpoint with the server. The server accepts only an `https` endpoint on
   port 443 whose host is in `SIDEKICK_PUSH_ALLOWED_HOSTS`.
3. The worker sends a small content-free wake-up to that endpoint. The phone wakes, fetches what is due from
   the server, and shows the notification. The lock screen follows your phone's setting for sensitive content.
4. Check it in the app: Settings, "Send test notification" (limited to 5 per hour).

The morning summary is queued from the configured time for a window of two hours, and only if something is due
today or overdue; a due reminder fires `SIDEKICK_PUSH_DUE_LEAD_MINUTES` before the task's clock time. Nothing is
announced in the quiet hours. If the worker was down for longer than the window, the summary is skipped.

By default the phone's ntfy app uses the public ntfy server (ntfy.sh), whose free tier allows roughly 250 messages per
day per sender; the server therefore spaces wake-ups to one phone at least 20 seconds apart
(`SIDEKICK_PUSH_WAKE_MIN_INTERVAL_SECONDS`).

**Own ntfy server.** The self-hosted package includes one (`vps` profile with `--profile push`). It refuses anonymous
reading, so the phone must sign in:

1. Once, from `deploy/selfhost`: `sh ntfy-init.sh`. It writes `ntfy.env`, `ntfy-secrets/sidekick-token` and
   `ntfy-secrets/phone-password` (mode 600) and prints only where they are.
2. In `selfhost.env`, uncomment the three lines under "Own ntfy server" in `selfhost.env.example`: the allowlist
   `SIDEKICK_PUSH_ALLOWED_HOSTS=<your-domain>,ntfy.sh`, `SIDEKICK_PUSH_AUTH_HOST=<your-domain>` and
   `SIDEKICK_PUSH_AUTH_TOKEN` with the content of `ntfy-secrets/sidekick-token`. Recreate the API and start the worker:
   `docker compose --env-file selfhost.env --profile vps --profile push up -d`.
3. In the phone's ntfy app, add `https://<your-domain>` as a server with the user `phone` and the password from
   `ntfy-secrets/phone-password`, and make it the default server. Reopen Sidekick so that it registers with that server.
4. In Sidekick, Settings, "Send test notification". If nothing arrives, see Troubleshooting.
