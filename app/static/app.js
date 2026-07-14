function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = atob(base64);
  return Uint8Array.from([...rawData].map((c) => c.charCodeAt(0)));
}

async function enableWebPush() {
  const statusEl = document.getElementById("webpush-status");
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    statusEl.textContent = "Push notifications are not supported in this browser.";
    return;
  }
  try {
    const permission = await Notification.requestPermission();
    if (permission !== "granted") {
      statusEl.textContent = "Permission denied.";
      return;
    }
    const registration = await navigator.serviceWorker.register("/sw.js");
    await navigator.serviceWorker.ready;
    const keyResp = await fetch("/api/push/vapid-public-key");
    const { publicKey } = await keyResp.json();
    const subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(publicKey),
    });
    await fetch("/api/push/subscribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(subscription.toJSON()),
    });
    statusEl.textContent = "Push notifications enabled in this browser.";
  } catch (err) {
    statusEl.textContent = "Failed to enable push: " + err.message;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("webpush-subscribe-btn");
  if (btn) btn.addEventListener("click", enableWebPush);
});
