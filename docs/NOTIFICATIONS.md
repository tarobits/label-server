# Notifications

[All guides](README.md) · [Project overview](../README.md)

Alerts tell you when printing needs attention or a request needs a decision. You can read notifications inside the app. Email and phone alerts need extra setup; ask your administrator if these options are unavailable.

## For administrators: connect an alert service

Notifications are stored in the app even when no delivery endpoint is configured.
Administrators add endpoints under **Administration**, choosing ntfy or email
and the event types. For ntfy, supply a server base URL
(for example `https://ntfy.example.com`), topic, and optional access token.
For email, supply a recipient address.
Tokens stay on the server; editing an endpoint can preserve, replace or clear its token.
Set `LABEL_PUBLIC_URL` to the browser-reachable server address for notification links.

## Choose which alerts to send

Each endpoint routes by event type and printer scope. Choose specific printers or
distribution groups, use **Select all** to capture only current physical printers, or explicitly
enable **All current and future printers**. Group scopes also receive operational
alerts from their member printers as membership changes; select groups manually.
With no scope selected, printer-related event
types are disabled and cleared. General alerts remain global; pending-request
summaries are global without a scope and narrow to selected destinations otherwise.
Administrator-managed endpoint filters do not use application roles or access levels. Configure ntfy
topic subscription permissions separately to control who can read each topic.

## Choose alert priority

For ntfy endpoints, set a severity per event type using ntfy's
[message priorities](https://docs.ntfy.sh/publish/#message-priority): Min, Low,
Normal, High, or Urgent. Empty cartridges, blocked printers and batch reviews
default to High; general alerts, waiting tape reminders and pending requests
default to Normal.

## Delivery and retries

A notification can go to several matching endpoints. Each delivery retries
independently of other endpoints and printing. Changing, disabling or deleting an
endpoint cancels its pending deliveries. Delivery may repeat after a crash; this
does not duplicate a print.

## Set up personal emails

Users can enable personal emails under **Account settings** after verifying their
recovery address. Printer alerts require Moderator or Full access to their destination;
physical printer alerts require direct printer access. Pending-request summaries
are available to administrators. Account alerts go only to their intended recipient.
Personal deliveries recheck current access, account status, and the verified email
before each attempt. Personal subscriptions are separate from administrator endpoints.

## Customize alerts for each printer

Both administrator endpoints and personal subscriptions support **Per-printer
event types**. Customize a printer to replace the default cartridge, blocker,
batch-review, and tape-waiting choices for that device. Clear all its events to
silence it, or turn off customization to restore the defaults. Other printers,
including future additions covered by an all-printers selection, keep the defaults.
Overrides apply to physical printer events, including those received through a
selected printer group. Group-wide waiting reminders, general alerts, and
pending-request summaries retain the default choices. Each customized ntfy event
also has a priority selector: use Min through Urgent or **Default** to inherit the
endpoint's priority for that event type. Combined tape-waiting reminders use the
highest priority among the destinations included in the message. Personal overrides
still require direct Moderator or Full access to the printer.

## For administrators: email setup

Personal emails and password recovery require a configured mail service.
Follow [email configuration](DEPLOYMENT.md#email-configuration).
For older notification settings, see [legacy configuration migrations](DEPLOYMENT.md#legacy-configuration-migrations).
If a recovery email fails to arrive after a server restart, request another link.

## Remind people to change tape

Waiting reminders are optional per tape profile. They begin when a destination
reaches its threshold without the required tape installed and repeat at the
configured interval, defaulting to 24 hours. Snooze and silence survive restarts.
Silence lasts until the waiting episode ends; disable the profile's reminders to
turn them off persistently.

## Connect other applications

Interactive API schemas are at <http://localhost:8000/docs>. API clients sign in,
retain the session cookie, and send `X-CSRF-Token` on mutations. Use
`Idempotency-Key` for retry-safe job submissions: the same key and input return
the original job; changed input returns HTTP 409. Intentional reprints need a new
key. See [REST integrations](INTEGRATIONS.md) for bundled clients and HomeBox.
