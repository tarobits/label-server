# Use the app on a phone or tablet

[All guides](README.md) · [Project overview](../README.md)

You do not need an app-store download. Open the address supplied by your administrator in your browser, then add it to your Home Screen. Printing still needs a connection to the server.

## Add to your Home Screen

Open the production site over HTTPS. On iPhone or iPad, use Safari's Share menu
and choose **Add to Home Screen** (enable **Open as Web App** if offered). On Android,
use Chrome's **Install app** or **Add to Home screen** menu item. Launch the installed
app from its icon to open Taro's Label Room in its own window.

## When the server is unavailable

After a successful visit has cached the app, opening it during a connection,
server, or reverse-proxy outage shows **The label server is currently unable to be
reached.** Choose **Retry**, or leave the app open for automatic recovery. An
already-open editor keeps its unsaved work in memory during an outage; reloading
or closing the app does not save that work. A first visit during an outage may
still show the browser's or hosting provider's error page.

## App updates

When a new frontend is ready, **App update ready** offers **Reload** or **Later**.
Only the window where Reload is chosen reloads, and the template editor's unsaved
changes warning still applies. Save other form changes before reloading. Updates
can also activate after all existing app windows and site tabs close.

The service worker caches the public app shell and build assets only. API
responses and account data stay out of its cache, and failed print submissions
are never replayed automatically.

## Enable phone notifications

After [configuring Web Push](DEPLOYMENT.md#push-notifications), open **Account
settings → Push notifications** on each device to enable alerts, select printer/event
preferences, and send a test. iPhone/iPad notifications require a Home Screen app on
iOS/iPadOS 16.4 or later. Device subscriptions can be removed from account settings;
signing out or losing the associated session stops new delivery.
