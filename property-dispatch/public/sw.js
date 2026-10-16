// public/sw.js - Runs in the background on the customer's phone

// Listen for the push event fired from your Render backend
self.addEventListener('push', function(event) {
  if (!event.data) return;

  // Extract the text content from the notification payload
  const data = event.data.json();

  const options = {
    body: data.body,
    icon: '/icons/icon-192x192.png',      // Path to your business logo badge
    badge: '/icons/badge-72x72.png',     // Tiny icon displayed in the status bar
    vibrate:,            // Vibrate pattern: vibrate, pause, vibrate
    data: {
      url: 'https://onrender.com' // URL opened when clicked
    }
  };

  // Keep the service worker alive until the notification is displayed on the screen
  event.waitUntil(
    self.registration.showNotification(data.title, options)
  );
});

// Action when the customer taps the notification banner on their screen
self.addEventListener('notificationclick', function(event) {
  event.notification.close(); // Dimiss the notification window

  // Reopen or focus their active live service tracker dashboard view
  event.waitUntil(
    clients.openWindow(event.notification.data.url)
  );
});
