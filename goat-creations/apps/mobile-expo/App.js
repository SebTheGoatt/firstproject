/**
 * GOAT CREATIONS mobile studio (Expo).
 *
 * Two ways to connect, both through `sebastina-core` (the same pipeline as desktop):
 * - "My MuAPI key": the phone calls MuAPI directly with the owner's own key.
 *   For your personal phone only: never ship a build with a key inside it.
 * - "GOAT server": the phone sends a customer access token to the SEBastina
 *   server, which holds the keys and checks Lago credits.
 * Keys and tokens live in the device's secure storage (Android Keystore / iOS Keychain).
 */
import { useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Image,
  KeyboardAvoidingView,
  Linking,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import * as SecureStore from 'expo-secure-store';
import { GOAT_MODULES, SEBastinaClient, SEBastinaEngine } from 'sebastina-core';

const C = {
  canvas: '#0B0C0F',
  inset: '#0F1114',
  panel: '#15171C',
  raised: '#1E2128',
  border: '#2A2E36',
  text: '#E7E9EC',
  dim: '#8C949F',
  gold: '#F2B82E',
  goldSoft: '#3A3014',
  danger: '#F06A5E',
  ok: '#5ED08F',
};

const SERVER_KEY = 'goat_server_url';
const TOKEN_KEY = 'goat_access_token';
const MODE_KEY = 'goat_mode';
const MUAPI_KEY = 'goat_muapi_key';
const MODES = [
  { id: 'direct', label: 'My MuAPI key' },
  { id: 'server', label: 'GOAT server' },
];
// On a phone, 127.0.0.1 is the phone itself: use your computer's network address.
const DEFAULT_SERVER = 'http://192.168.1.10:8787';

export default function App() {
  const [serverUrl, setServerUrl] = useState(DEFAULT_SERVER);
  const [token, setToken] = useState('');
  const [mode, setMode] = useState('direct');
  const [muapiKey, setMuapiKey] = useState('');
  const [showSettings, setShowSettings] = useState(false);
  const [moduleId, setModuleId] = useState('image');
  const [prompt, setPrompt] = useState('A majestic goat climbing a high-tech neon mountain, cinematic');
  const [status, setStatus] = useState({ kind: 'idle', text: 'Ready.' });
  const [result, setResult] = useState(null);

  const module = GOAT_MODULES.find((m) => m.id === moduleId);
  const client = useMemo(() => new SEBastinaClient({ serverUrl, token }), [serverUrl, token]);
  const engine = useMemo(() => new SEBastinaEngine({ apiKey: muapiKey.trim() }), [muapiKey]);
  const busy = status.kind === 'busy';

  // Load saved connection settings once.
  useEffect(() => {
    (async () => {
      try {
        const [savedUrl, savedToken, savedMode, savedKey] = await Promise.all([
          SecureStore.getItemAsync(SERVER_KEY),
          SecureStore.getItemAsync(TOKEN_KEY),
          SecureStore.getItemAsync(MODE_KEY),
          SecureStore.getItemAsync(MUAPI_KEY),
        ]);
        if (savedUrl) setServerUrl(savedUrl);
        if (savedToken) setToken(savedToken);
        if (savedMode) setMode(savedMode);
        if (savedKey) setMuapiKey(savedKey);
        const ready = (savedMode || 'direct') === 'direct' ? !!savedKey : !!savedToken;
        if (!ready) setShowSettings(true);
      } catch {
        setShowSettings(true); // secure storage unavailable (e.g. web preview)
      }
    })();
  }, []);

  async function saveSettings() {
    try {
      await SecureStore.setItemAsync(MODE_KEY, mode);
      await SecureStore.setItemAsync(SERVER_KEY, serverUrl.trim());
      await SecureStore.setItemAsync(TOKEN_KEY, token.trim());
      await SecureStore.setItemAsync(MUAPI_KEY, muapiKey.trim());
    } catch {
      /* not available on this platform: settings last until the app closes */
    }
    if (mode === 'direct') {
      const hasKey = !!muapiKey.trim();
      setStatus(hasKey ? { kind: 'ok', text: 'Saved. Using your MuAPI key.' } : { kind: 'error', text: 'Paste your MuAPI key first.' });
      if (hasKey) setShowSettings(false);
      return;
    }
    setStatus({ kind: 'busy', text: 'Checking the server…' });
    const ok = await client.health();
    setStatus(ok ? { kind: 'ok', text: 'Saved. Server reachable.' } : { kind: 'error', text: `Saved, but can't reach ${serverUrl}.` });
    if (ok) setShowSettings(false);
  }

  async function generate() {
    setStatus({
      kind: 'busy',
      text: module.isMotion ? 'Rendering video… this can take a few minutes.' : 'Generating image…',
    });
    const request =
      module.isMotion
        ? { prompt, isMotion: true, aspectRatio: '9:16', duration: 5 }
        : { prompt, isMotion: false, width: 768, height: 1344 };
    const outcome = mode === 'direct' ? await engine.generateAsset(request) : await client.generate(request);
    if (outcome.success && outcome.data) {
      setResult({ url: outcome.data, isMotion: module.isMotion });
      setStatus({ kind: 'ok', text: `${module.name} finished.` });
    } else {
      setStatus({ kind: 'error', text: outcome.error || 'Something went wrong.' });
    }
  }

  return (
    <KeyboardAvoidingView style={styles.root} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <StatusBar style="light" />
      <View style={styles.header}>
        <View style={styles.brand}>
          <View style={styles.mark}><Text style={styles.markText}>G</Text></View>
          <Text style={styles.wordmark}>GOAT CREATIONS</Text>
        </View>
        <Pressable
          onPress={() => setShowSettings((s) => !s)}
          accessibilityRole="button"
          accessibilityState={{ expanded: showSettings }}
          hitSlop={8}
        >
          <Text style={styles.link}>{showSettings ? 'Close' : 'Settings'}</Text>
        </Pressable>
      </View>

      <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
        {showSettings && (
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Connection</Text>
            <View style={styles.tabs} accessibilityRole="radiogroup">
              {MODES.map((m) => {
                const active = m.id === mode;
                return (
                  <Pressable
                    key={m.id}
                    onPress={() => setMode(m.id)}
                    style={[styles.tab, active && styles.tabActive]}
                    accessibilityRole="radio"
                    accessibilityState={{ checked: active }}
                  >
                    <Text style={[styles.tabText, active && styles.tabTextActive]}>{m.label}</Text>
                  </Pressable>
                );
              })}
            </View>
            {mode === 'direct' ? (
              <>
                <Text style={styles.label}>MuAPI key</Text>
                <TextInput
                  style={styles.input}
                  value={muapiKey}
                  onChangeText={setMuapiKey}
                  autoCapitalize="none"
                  autoCorrect={false}
                  secureTextEntry
                  placeholder="From muapi.ai > API keys"
                  placeholderTextColor={C.dim}
                />
                <Text style={styles.dim}>Kept in this phone's secure storage. Each generation is billed to your MuAPI account.</Text>
              </>
            ) : (
              <>
                <Text style={styles.label}>Server address</Text>
                <TextInput
                  style={styles.input}
                  value={serverUrl}
                  onChangeText={setServerUrl}
                  autoCapitalize="none"
                  autoCorrect={false}
                  keyboardType="url"
                  placeholderTextColor={C.dim}
                />
                <Text style={styles.label}>Access token</Text>
                <TextInput
                  style={styles.input}
                  value={token}
                  onChangeText={setToken}
                  autoCapitalize="none"
                  autoCorrect={false}
                  secureTextEntry
                  placeholder="From your GOAT CREATIONS account"
                  placeholderTextColor={C.dim}
                />
              </>
            )}
            <Button label={mode === 'direct' ? 'Save' : 'Save and test'} onPress={saveSettings} disabled={busy} variant="secondary" />
          </View>
        )}

        <View style={styles.tabs} accessibilityRole="tablist">
          {GOAT_MODULES.map((m) => {
            const active = m.id === moduleId;
            return (
              <Pressable
                key={m.id}
                onPress={() => setModuleId(m.id)}
                style={[styles.tab, active && styles.tabActive]}
                accessibilityRole="tab"
                accessibilityState={{ selected: active }}
              >
                <Text style={[styles.tabText, active && styles.tabTextActive]}>{m.name}</Text>
              </Pressable>
            );
          })}
        </View>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>{module.name}</Text>
          <Text style={styles.dim}>{module.tagline}</Text>
          <Text style={styles.label}>Prompt</Text>
          <TextInput
            style={[styles.input, styles.prompt]}
            value={prompt}
            onChangeText={setPrompt}
            multiline
            maxLength={3000}
            placeholderTextColor={C.dim}
          />
          <Button
            label={busy ? 'Working…' : `Generate with ${module.name}`}
            onPress={generate}
            disabled={busy || !prompt.trim()}
          />
        </View>

        <View style={styles.result}>
          {busy ? (
            <ActivityIndicator color={C.gold} size="large" />
          ) : result ? (
            result.isMotion ? (
              <Button label="Open video" onPress={() => Linking.openURL(result.url)} variant="secondary" />
            ) : (
              <Image source={{ uri: result.url }} style={styles.image} resizeMode="contain" accessibilityLabel={`Generated: ${prompt}`} />
            )
          ) : (
            <View style={styles.empty}>
              <Text style={styles.emptyTitle}>
                <Text style={{ color: C.gold }}>GOAT</Text> CREATIONS
              </Text>
              <Text style={styles.dim}>The Greatest of All Time Open-Source Creative Suite</Text>
            </View>
          )}
        </View>
      </ScrollView>

      <View style={styles.status} accessibilityLiveRegion="polite">
        <Text style={styles.statusModule}>{module.name}</Text>
        <Text
          style={[styles.statusText, status.kind === 'ok' && { color: C.ok }, status.kind === 'error' && { color: C.danger }]}
          numberOfLines={2}
        >
          {status.text}
        </Text>
      </View>
    </KeyboardAvoidingView>
  );
}

function Button({ label, onPress, disabled, variant = 'primary' }) {
  const primary = variant === 'primary';
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityState={{ disabled: !!disabled }}
      style={({ pressed }) => [
        styles.button,
        primary ? styles.buttonPrimary : styles.buttonSecondary,
        pressed && { opacity: 0.85 },
        disabled && { opacity: 0.5 },
      ]}
    >
      <Text style={primary ? styles.buttonPrimaryText : styles.buttonSecondaryText}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: C.canvas },
  header: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingTop: Platform.OS === 'android' ? 40 : 56, paddingBottom: 12, paddingHorizontal: 16,
    backgroundColor: C.panel, borderBottomWidth: 1, borderBottomColor: C.border,
  },
  brand: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  mark: { width: 26, height: 26, borderRadius: 7, backgroundColor: C.gold, alignItems: 'center', justifyContent: 'center' },
  markText: { color: C.canvas, fontWeight: '800', fontSize: 16 },
  wordmark: { color: C.text, fontWeight: '700', letterSpacing: 1.2 },
  link: { color: C.gold, fontWeight: '600', paddingVertical: 6 },
  body: { padding: 16, gap: 14 },
  card: { backgroundColor: C.raised, borderRadius: 12, padding: 14, gap: 8 },
  cardTitle: { color: C.gold, fontWeight: '700', fontSize: 16 },
  label: { color: C.dim, fontSize: 12, marginTop: 4 },
  dim: { color: C.dim, fontSize: 12 },
  input: {
    color: C.text, backgroundColor: C.inset, borderColor: C.border, borderWidth: 1,
    borderRadius: 8, paddingHorizontal: 10, paddingVertical: 10, fontSize: 15,
  },
  prompt: { minHeight: 110, textAlignVertical: 'top' },
  tabs: { flexDirection: 'row', backgroundColor: C.panel, borderRadius: 10, padding: 4, gap: 4 },
  tab: { flex: 1, paddingVertical: 10, borderRadius: 8, alignItems: 'center' },
  tabActive: { backgroundColor: C.goldSoft },
  tabText: { color: C.dim, fontWeight: '600' },
  tabTextActive: { color: C.gold },
  button: { borderRadius: 8, paddingVertical: 12, alignItems: 'center', marginTop: 8, minHeight: 44, justifyContent: 'center' },
  buttonPrimary: { backgroundColor: C.gold },
  buttonSecondary: { borderWidth: 1, borderColor: C.border },
  buttonPrimaryText: { color: C.canvas, fontWeight: '700', fontSize: 15 },
  buttonSecondaryText: { color: C.text, fontWeight: '600', fontSize: 15 },
  result: { minHeight: 260, alignItems: 'center', justifyContent: 'center' },
  image: { width: '100%', aspectRatio: 768 / 1344, borderRadius: 10 },
  empty: { alignItems: 'center', gap: 6 },
  emptyTitle: { color: C.text, fontSize: 26, fontWeight: '300', letterSpacing: 3 },
  status: {
    flexDirection: 'row', gap: 10, paddingHorizontal: 16, paddingTop: 8, paddingBottom: 24,
    backgroundColor: C.panel, borderTopWidth: 1, borderTopColor: C.border,
  },
  statusModule: { color: C.gold, fontWeight: '600', fontSize: 12 },
  statusText: { color: C.dim, fontSize: 12, flex: 1 },
});
