self.addEventListener("push", (event) => {
  let data = { title: "Entracte", body: "Time for a break!" };
  if (event.data) {
    try {
      data = event.data.json();
    } catch (e) {
      data.body = event.data.text();
    }
  }
  event.waitUntil(self.registration.showNotification(data.title, { body: data.body }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(clients.openWindow("/"));
});
