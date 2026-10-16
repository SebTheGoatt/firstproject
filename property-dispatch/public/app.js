// public/app.js - Runs on the customer's active web page dashboard

// Utility to convert the standard VAPID public key string safely into an array format for the browser
function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - base64String.length % 4) % 4);
  const base64 = (base64String + padding).replace(/\-/g, '+').replace(/_/g, '/');
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

// Main function to trigger when a customer opts into notifications
async function initPushNotificationSetup() {
  // Check if the customer's browser supports service workers and push notifications
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    console.warn('Push messaging is not supported in this browser.');
    return;
  }

  try {
    // 1. Wait for the Service Worker to register and become active
    const registration = await navigator.serviceWorker.ready;

    // 2. Request explicit lock-screen permission from the user
    const permission = await Notification.requestPermission();
    if (permission !== 'granted') {
      console.log('Notification permission was denied by user.');
      return;
    }

    // 3. Define your public identity verification key (generated via npx web-push)
    const publicVapidKey = 'YOUR_PUBLIC_VAPID_KEY_HERE'; 
    const convertedKey = urlBase64ToUint8Array(publicVapidKey);

    // 4. Create the secure cryptographic push delivery token mapping 
    const subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true, // Guarantees every notification payload generates a visible UI pop-up
      applicationServerKey: convertedKey
    });

    // 5. Fetch the active user's session details from your Supabase client
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) return console.error('No logged-in client discovered.');

    // 6. Push the generated token straight into your Supabase database table
    const { error } = await supabase
      .from('client_push_subscriptions')
      .insert([
        { 
          user_id: user.id, 
          subscription_json: subscription.toJSON() // Converts the crypto credentials to clean JSON
        }
      ]);

    if (error) throw error;
    console.log('Secure Device Push Token logged successfully to Supabase.');

  } catch (err) {
    console.error('Failed to configure device push registration profile:', err);
  }
}
