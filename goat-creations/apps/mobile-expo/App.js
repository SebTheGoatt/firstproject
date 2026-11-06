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
import { useEffect, useMemo, useRef, useState } from 'react';
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
import { SafeAreaProvider, useSafeAreaInsets, initialWindowMetrics } from 'react-native-safe-area-context';
import * as SecureStore from 'expo-secure-store';
import * as ImagePicker from 'expo-image-picker';
import { ImageManipulator, SaveFormat } from 'expo-image-manipulator';
import {
  GOAT_MODULES,
  SEBastinaClient,
  SEBastinaEngine,
  IMAGE_MODELS,
  VIDEO_MODELS,
  DEFAULT_IMAGE_MODEL,
  DEFAULT_VIDEO_MODEL,
  SKILLS,
  CHARACTER_SKILLS,
  contentIssue,
  skillOutput,
} from 'sebastina-core';

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
const CHARACTER_KEY = 'goat_character';
const MODES = [
  { id: 'direct', label: 'My MuAPI key' },
  { id: 'server', label: 'GOAT server' },
];
const TABS = [
  ...GOAT_MODULES.map((m) => ({ id: m.id, label: m.name })),
  { id: 'skills', label: 'Skills' },
  { id: 'photo', label: 'Photo' },
  { id: 'sebastina', label: 'SEBastina' },
];
// Photos are re-saved before upload: strips hidden metadata (GPS location) and caps size.
const MAX_PHOTO_PX = 2048;
// On a phone, 127.0.0.1 is the phone itself: use your computer's network address.
const DEFAULT_SERVER = 'http://192.168.1.10:8787';

export default function App() {
  return (
    <SafeAreaProvider initialMetrics={initialWindowMetrics}>
      <Studio />
    </SafeAreaProvider>
  );
}

function Studio() {
  const insets = useSafeAreaInsets();
  const [serverUrl, setServerUrl] = useState(DEFAULT_SERVER);
  const [token, setToken] = useState('');
  const [mode, setMode] = useState('direct');
  const [muapiKey, setMuapiKey] = useState('');
  const [imageModel, setImageModel] = useState(DEFAULT_IMAGE_MODEL);
  const [videoModel, setVideoModel] = useState(DEFAULT_VIDEO_MODEL);
  // In server mode, only the models the server allows (null = not fetched yet).
  const [serverModels, setServerModels] = useState(null);
  const [serverSkills, setServerSkills] = useState(null);
  // SEBastina's saved look: { url } of the reference portrait made by "Design SEBastina".
  const [character, setCharacter] = useState(null);
  const [showSettings, setShowSettings] = useState(false);
  const [moduleId, setModuleId] = useState('image');
  const [prompt, setPrompt] = useState('A majestic goat climbing a high-tech neon mountain, cinematic');
  const [status, setStatus] = useState({ kind: 'idle', text: 'Ready.' });
  const [result, setResultState] = useState(null);
  // Shown image's real shape, so thumbnails (16:9) and portraits both fit.
  const [resultRatio, setResultRatio] = useState(null);
  const scrollRef = useRef(null);
  const setResult = (value) => {
    setResultRatio(null);
    setResultState(value);
    // Bring the finished piece into view (it sits below the form).
    if (value) setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 250);
  };

  // `module` is ImageGOAT/MotionGOAT; undefined on the Skills and Photo tabs.
  const module = GOAT_MODULES.find((m) => m.id === moduleId);
  const tabLabel = TABS.find((t) => t.id === moduleId)?.label ?? '';
  const client = useMemo(() => new SEBastinaClient({ serverUrl, token }), [serverUrl, token]);
  const engine = useMemo(() => new SEBastinaEngine({ apiKey: muapiKey.trim() }), [muapiKey]);
  const busy = status.kind === 'busy';
  const catalog = module?.isMotion ? VIDEO_MODELS : IMAGE_MODELS;
  const models = mode === 'server' && serverModels?.length ? catalog.filter((m) => serverModels.includes(m.id)) : catalog;
  const chosenModel = module?.isMotion ? videoModel : imageModel;
  const setChosenModel = module?.isMotion ? setVideoModel : setImageModel;
  const category = moduleId === 'photo' ? 'photo' : moduleId === 'sebastina' ? 'character' : 'create';
  const catalogSkills = category === 'character' ? CHARACTER_SKILLS.filter((s) => (character ? s.needsCharacter : !s.needsCharacter)) : SKILLS;
  const skills = catalogSkills.filter(
    (s) => s.category === category && (mode !== 'server' || (serverSkills ?? []).includes(s.id)),
  );
  const model = models.find((m) => m.id === chosenModel) ?? models[0];

  // Load saved connection settings once.
  useEffect(() => {
    (async () => {
      try {
        const [savedUrl, savedToken, savedMode, savedKey, savedCharacter] = await Promise.all([
          SecureStore.getItemAsync(SERVER_KEY),
          SecureStore.getItemAsync(TOKEN_KEY),
          SecureStore.getItemAsync(MODE_KEY),
          SecureStore.getItemAsync(MUAPI_KEY),
          SecureStore.getItemAsync(CHARACTER_KEY),
        ]);
        if (savedCharacter) {
          try {
            setCharacter(JSON.parse(savedCharacter));
          } catch {
            /* ignore a damaged saved value */
          }
        }
        if (savedUrl) setServerUrl(savedUrl);
        if (savedToken) setToken(savedToken);
        if (savedMode) setMode(savedMode);
        if (savedKey) setMuapiKey(savedKey);
        const ready = (savedMode || 'direct') === 'direct' ? !!savedKey : !!savedToken;
        if (!ready) {
          setShowSettings(true);
          setStatus({ kind: 'idle', text: 'Step 1: paste your MuAPI key above and tap Save.' });
        }
      } catch {
        // Secure storage unavailable (e.g. web preview): start at Settings.
        setShowSettings(true);
        setStatus({ kind: 'idle', text: 'Step 1: paste your MuAPI key above and tap Save.' });
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
      if (!muapiKey.trim()) {
        setStatus({ kind: 'error', text: 'Paste your MuAPI key first (muapi.ai > Dashboard > API keys).' });
        return;
      }
      setStatus({ kind: 'busy', text: 'Checking your key with MuAPI…' });
      const check = await engine.checkKey();
      if (check.ok) {
        const balance = check.balance !== undefined ? ` Balance: $${check.balance.toFixed(2)}.` : '';
        setStatus({ kind: 'ok', text: `Key works.${balance} You're ready to create.` });
        setShowSettings(false);
      } else {
        setStatus({ kind: 'error', text: check.error || 'MuAPI did not accept that key.' });
      }
      return;
    }
    setStatus({ kind: 'busy', text: 'Checking the server…' });
    const ok = await client.health();
    if (ok) {
      setServerModels(await client.allowedModels());
      setServerSkills(await client.allowedSkills());
    }
    setStatus(ok ? { kind: 'ok', text: 'Saved. Server reachable.' } : { kind: 'error', text: `Saved, but can't reach ${serverUrl}.` });
    if (ok) setShowSettings(false);
  }

  /** True when a key (or server token) is set; otherwise opens Settings and says what to do. */
  function ready() {
    const ok = mode === 'direct' ? !!muapiKey.trim() : !!token.trim();
    if (!ok) {
      setShowSettings(true);
      setStatus({
        kind: 'error',
        text: mode === 'direct' ? 'First paste your MuAPI key in Settings (top of the screen) and tap Save.' : 'First paste your access token in Settings and tap Save.',
      });
    }
    return ok;
  }

  async function saveCharacter(url) {
    const value = url ? { url, savedAt: new Date().toISOString() } : null;
    setCharacter(value);
    try {
      if (value) await SecureStore.setItemAsync(CHARACTER_KEY, JSON.stringify(value));
      else await SecureStore.deleteItemAsync(CHARACTER_KEY);
    } catch {
      /* not available on this platform: kept until the app closes */
    }
    setStatus(value ? { kind: 'ok', text: "SEBastina's look is saved. Every SEBastina Skill now uses it." } : { kind: 'idle', text: 'Design a new look for SEBastina.' });
  }

  async function generate() {
    if (!ready()) return;
    setStatus({
      kind: 'busy',
      text: module.isMotion ? 'Rendering video… this can take a few minutes.' : 'Generating image…',
    });
    const request =
      module.isMotion
        ? { prompt, isMotion: true, model: model?.id, aspectRatio: '9:16', duration: 5 }
        : { prompt, isMotion: false, model: model?.id, width: 768, height: 1344 };
    const outcome = mode === 'direct' ? await engine.generateAsset(request) : await client.generate(request);
    if (outcome.success && outcome.data) {
      setResult({ url: outcome.data, isMotion: module.isMotion, label: module.name });
      setStatus({ kind: 'ok', text: `${module.name} finished with ${model?.name ?? 'the default model'}.` });
    } else {
      setStatus({ kind: 'error', text: outcome.error || 'Something went wrong.' });
    }
  }

  /** Upload the photo if the Skill needs one, then run it (directly or through the server). */
  async function runSkill(skill, inputs, photo) {
    if (!ready()) return;
    if (skill.category === 'character') {
      const issue = Object.values(inputs).map((v) => contentIssue(String(v))).find(Boolean);
      if (issue) {
        setStatus({ kind: 'error', text: issue });
        return;
      }
    }
    let photoUrl;
    try {
      if (skill.needsPhoto) {
        if (!photo) {
          setStatus({ kind: 'error', text: `${skill.name} needs a photo.` });
          return;
        }
        setStatus({ kind: 'busy', text: 'Uploading photo…' });
        const file = { uri: photo.uri, name: 'photo.jpg', type: 'image/jpeg' };
        photoUrl = mode === 'direct' ? await engine.uploadImage(file) : await client.uploadImage(file);
      }
    } catch (error) {
      setStatus({ kind: 'error', text: error?.message || 'Upload failed.' });
      return;
    }
    const isVideo = skillOutput(skill) === 'video';
    const steps = skill.steps.length > 1 ? ` (${skill.steps.length} steps)` : '';
    setStatus({ kind: 'busy', text: `Running ${skill.name}${steps}…${isVideo ? ' Videos can take a few minutes.' : ''}` });
    const request = { skillId: skill.id, inputs, photoUrl, characterUrl: character?.url };
    const outcome = mode === 'direct' ? await engine.runSkill(request) : await client.runSkill(request);
    if (outcome.success && outcome.data) {
      setResult({ url: outcome.data, isMotion: outcome.kind === 'video', label: skill.name, skillId: skill.id });
      setStatus({ kind: 'ok', text: `${skill.name} finished.` });
    } else {
      setStatus({ kind: 'error', text: outcome.error || 'Something went wrong.' });
    }
  }

  return (
    <KeyboardAvoidingView style={styles.root} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <StatusBar style="light" />
      <View style={[styles.header, { paddingTop: insets.top + 12 }]}>
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

      <ScrollView ref={scrollRef} contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
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

        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          style={styles.tabsScroll}
          contentContainerStyle={styles.tabs}
          accessibilityRole="tablist"
        >
          {TABS.map((t) => {
            const active = t.id === moduleId;
            return (
              <Pressable
                key={t.id}
                onPress={() => setModuleId(t.id)}
                style={[styles.tab, active && styles.tabActive]}
                accessibilityRole="tab"
                accessibilityState={{ selected: active }}
              >
                <Text style={[styles.tabText, styles.tabTextSmall, active && styles.tabTextActive]} numberOfLines={1}>
                  {t.label}
                </Text>
              </Pressable>
            );
          })}
        </ScrollView>

        {category === 'character' && (
          <View style={styles.card}>
            <Text style={styles.cardTitle}>SEBastina</Text>
            <Text style={styles.dim}>
              {character
                ? 'Her saved look is used in every SEBastina Skill below, so she looks the same everywhere.'
                : 'An original character for your brand. Describe her once, then save the portrait you like.'}
            </Text>
            {character && (
              <View style={styles.photoRow}>
                <Image source={{ uri: character.url }} style={styles.portrait} accessibilityLabel="SEBastina's saved look" />
                <View style={{ flex: 1 }}>
                  <Text style={styles.chipNote}>Always an adult, always fully clothed and safe-for-work.</Text>
                  <Button label="Design a new look" onPress={() => saveCharacter(null)} disabled={busy} variant="secondary" />
                </View>
              </View>
            )}
          </View>
        )}

        {!module ? (
          <SkillPanel
            key={category}
            skills={skills}
            category={category}
            busy={busy}
            onRun={runSkill}
            onError={(text) => setStatus({ kind: 'error', text })}
            emptyText={
              mode === 'server'
                ? 'This server offers no Skills yet. The owner turns them on with SEBASTINA_SERVER_SKILLS.'
                : 'No Skills here.'
            }
          />
        ) : (
        <View style={styles.card}>
          <Text style={styles.cardTitle}>{module.name}</Text>
          <Text style={styles.dim}>{module.tagline}</Text>
          <Text style={styles.label}>Model</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips}>
            {models.map((m) => {
              const active = m.id === model?.id;
              return (
                <Pressable
                  key={m.id}
                  onPress={() => setChosenModel(m.id)}
                  style={[styles.chip, active && styles.chipActive]}
                  accessibilityRole="radio"
                  accessibilityState={{ checked: active }}
                  accessibilityLabel={`${m.name}, ${m.note}`}
                >
                  <Text style={[styles.chipName, active && styles.tabTextActive]}>{m.name}</Text>
                  <Text style={styles.chipNote}>{m.note}</Text>
                </Pressable>
              );
            })}
          </ScrollView>
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
        )}

        <View style={styles.result}>
          {busy ? (
            <ActivityIndicator color={C.gold} size="large" accessibilityLabel="Working" />
          ) : result ? (
            result.isMotion ? (
              <Button label={result.label ? `Open ${result.label} video` : 'Open video'} onPress={() => Linking.openURL(result.url)} variant="secondary" />
            ) : (
              <Image
                source={{ uri: result.url }}
                style={[styles.image, resultRatio ? { aspectRatio: resultRatio } : { height: 360 }]}
                resizeMode="contain"
                onLoad={(e) => {
                  const { width, height } = e.nativeEvent.source ?? {};
                  if (width && height) setResultRatio(width / height);
                }}
                accessibilityLabel={result.label ? `Result of ${result.label}` : `Generated: ${prompt}`}
              />
            )
          ) : null}
          {!busy && result && result.skillId === 'design-character' && !character && (
            <View style={{ width: '100%', gap: 8 }}>
              <Button label="Use this look for SEBastina" onPress={() => saveCharacter(result.url)} />
              <Text style={[styles.chipNote, { textAlign: 'center' }]}>Not quite right? Change the words and run Design again.</Text>
            </View>
          )}
          {!busy && !result && (
            <View style={styles.empty}>
              <Text style={styles.emptyTitle}>
                <Text style={{ color: C.gold }}>GOAT</Text> CREATIONS
              </Text>
              <Text style={styles.dim}>The Greatest of All Time Open-Source Creative Suite</Text>
            </View>
          )}
        </View>
      </ScrollView>

      <View style={[styles.status, { paddingBottom: insets.bottom + 10 }]} accessibilityLiveRegion="polite">
        <Text style={styles.statusModule}>{tabLabel}</Text>
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

/** Skills and photo tools: pick one, fill its fields, add a photo if needed, run. */
function SkillPanel({ skills, category, busy, onRun, onError, emptyText }) {
  const [selectedId, setSelectedId] = useState(skills[0]?.id);
  const [inputs, setInputs] = useState({});
  const [photo, setPhoto] = useState(null);
  const skill = skills.find((s) => s.id === selectedId) ?? skills[0];

  if (!skill) {
    return (
      <View style={styles.card}>
        <Text style={styles.dim}>{emptyText}</Text>
      </View>
    );
  }

  async function pickPhoto() {
    try {
      const picked = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], quality: 1, exif: false });
      if (picked.canceled || !picked.assets?.length) return;
      const asset = picked.assets[0];
      const context = ImageManipulator.manipulate(asset.uri);
      if (asset.width > MAX_PHOTO_PX || asset.height > MAX_PHOTO_PX) {
        context.resize(asset.width >= asset.height ? { width: MAX_PHOTO_PX } : { height: MAX_PHOTO_PX });
      }
      const rendered = await context.renderAsync();
      const saved = await rendered.saveAsync({ compress: 0.85, format: SaveFormat.JPEG });
      setPhoto(saved);
    } catch (error) {
      onError(`Couldn't open that photo: ${error?.message ?? error}`);
    }
  }

  const missing = skill.fields.find((f) => !f.fallback && !(inputs[f.id] ?? '').trim());
  const output = skillOutput(skill);

  return (
    <View style={styles.card}>
      <Text style={styles.cardTitle}>{category === 'photo' ? 'Photo tools' : 'Skills'}</Text>
      <Text style={styles.dim}>
        {category === 'photo' ? 'Start from one of your photos.' : 'One-tap recipes: fill in a few words, get a finished piece.'}
      </Text>
      <View style={styles.skillList} accessibilityRole="radiogroup">
        {skills.map((s) => {
          const active = s.id === skill.id;
          return (
            <Pressable
              key={s.id}
              onPress={() => setSelectedId(s.id)}
              style={[styles.skillRow, active && styles.chipActive]}
              accessibilityRole="radio"
              accessibilityState={{ checked: active }}
              accessibilityLabel={`${s.name}. ${s.description}`}
            >
              <View style={{ flex: 1 }}>
                <Text style={[styles.chipName, active && styles.tabTextActive]}>{s.name}</Text>
                <Text style={styles.chipNote}>{s.description}</Text>
              </View>
              <Text style={styles.badge}>{skillOutput(s) === 'video' ? 'VIDEO' : 'IMAGE'}</Text>
            </Pressable>
          );
        })}
      </View>

      {skill.fields.map((f) => (
        <View key={f.id}>
          <Text style={styles.label}>
            {f.label}
            {f.fallback ? ' (optional)' : ''}
          </Text>
          <TextInput
            style={styles.input}
            value={inputs[f.id] ?? ''}
            onChangeText={(text) => setInputs((prev) => ({ ...prev, [f.id]: text }))}
            placeholder={f.placeholder}
            placeholderTextColor={C.dim}
            maxLength={600}
            accessibilityLabel={f.label}
          />
        </View>
      ))}

      {skill.needsPhoto && (
        <View style={styles.photoRow}>
          {photo ? (
            <Image source={{ uri: photo.uri }} style={styles.thumb} accessibilityLabel="Chosen photo" />
          ) : (
            <View style={[styles.thumb, styles.thumbEmpty]}>
              <Text style={styles.chipNote}>No photo</Text>
            </View>
          )}
          <View style={{ flex: 1 }}>
            <Button label={photo ? 'Change photo' : 'Choose photo'} onPress={pickPhoto} disabled={busy} variant="secondary" />
          </View>
        </View>
      )}

      <Button
        label={busy ? 'Working…' : `Run ${skill.name}`}
        onPress={() => onRun(skill, inputs, photo)}
        disabled={busy || !!missing || (skill.needsPhoto && !photo)}
      />
      <Text style={styles.chipNote}>
        {skill.steps.length > 1 ? `${skill.steps.length} steps · ` : ''}
        {output === 'video' ? 'Makes a video' : 'Makes an image'}
        {missing ? ` · Fill in "${missing.label}"` : ''}
      </Text>
    </View>
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
  tabsScroll: { flexGrow: 0 },
  portrait: { width: 84, height: 112, borderRadius: 10 },
  tab: { paddingVertical: 10, paddingHorizontal: 14, borderRadius: 8, alignItems: 'center', minWidth: 76 },
  chips: { gap: 8, paddingVertical: 2 },
  chip: { borderWidth: 1, borderColor: C.border, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 8, minHeight: 44, justifyContent: 'center' },
  chipActive: { borderColor: C.gold, backgroundColor: C.goldSoft },
  chipName: { color: C.text, fontWeight: '600', fontSize: 14 },
  chipNote: { color: C.dim, fontSize: 11, marginTop: 2 },
  tabActive: { backgroundColor: C.goldSoft },
  tabText: { color: C.dim, fontWeight: '600' },
  tabTextActive: { color: C.gold },
  tabTextSmall: { fontSize: 13 },
  skillList: { gap: 8, marginTop: 4 },
  skillRow: {
    flexDirection: 'row', alignItems: 'center', gap: 10, borderWidth: 1, borderColor: C.border,
    borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10, minHeight: 56,
  },
  badge: { color: C.dim, fontSize: 10, fontWeight: '700', letterSpacing: 1 },
  photoRow: { flexDirection: 'row', alignItems: 'center', gap: 12, marginTop: 4 },
  thumb: { width: 64, height: 64, borderRadius: 8 },
  thumbEmpty: { borderWidth: 1, borderColor: C.border, alignItems: 'center', justifyContent: 'center' },
  button: { borderRadius: 8, paddingVertical: 12, alignItems: 'center', marginTop: 8, minHeight: 44, justifyContent: 'center' },
  buttonPrimary: { backgroundColor: C.gold },
  buttonSecondary: { borderWidth: 1, borderColor: C.border },
  buttonPrimaryText: { color: C.canvas, fontWeight: '700', fontSize: 15 },
  buttonSecondaryText: { color: C.text, fontWeight: '600', fontSize: 15 },
  result: { minHeight: 260, alignItems: 'center', justifyContent: 'center' },
  image: { width: '100%', borderRadius: 10 },
  empty: { alignItems: 'center', gap: 6 },
  emptyTitle: { color: C.text, fontSize: 26, fontWeight: '300', letterSpacing: 3 },
  status: {
    flexDirection: 'row', gap: 10, paddingHorizontal: 16, paddingTop: 8, paddingBottom: 24,
    backgroundColor: C.panel, borderTopWidth: 1, borderTopColor: C.border,
  },
  statusModule: { color: C.gold, fontWeight: '600', fontSize: 12 },
  statusText: { color: C.dim, fontSize: 12, flex: 1 },
});
