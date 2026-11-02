# CG4002 Visualiser — AR Pokemon Game + SSH/MQTT Communications

This repository contains only the C# source scripts for the Unity AR game.
Scenes, models, prefabs, NuGet DLLs, ProjectSettings, and Unity-generated
`.meta` files are **not versioned** — each team member recreates them locally
by following this guide.

---

## Prerequisites

- **Unity Hub** + **Unity 6** (6000.x)
- **Android Build Support** module (Unity Hub → Installs → Add Modules)
- Android device with **ARCore** support (or iOS with ARKit)
- **NuGetForUnity** (for MQTTnet / SSH.NET packages)

---

## Step 1: Create Unity Project

1. Open Unity Hub → **New Project**
2. Select **3D (URP)** template (Universal Render Pipeline)
3. Name: `CG4002-Pokemon-AR`
4. Create Project

## Step 2: Install Unity Packages

### Unity Registry Packages

Open **Window → Package Manager**, switch to "Unity Registry", and install:

| Package | Purpose |
|---------|---------|
| AR Foundation | Cross-platform AR abstraction |
| ARCore XR Plugin | Android AR support |
| ARKit XR Plugin | iOS AR support (optional) |
| XR Plugin Management | AR device management |
| TextMeshPro | UI text rendering |

### Niantic Spatial SDK

1. **Window → Package Manager** → **+** → **Add package by name**
2. Enter: `com.nianticspatial.nsdk` version **4.1.0**
3. After import: **Niantic → Spatial SDK → Configure Project** to auto-fix settings

Provides: Semantic Segmentation (terrain detection), Depth & Occlusion, Meshing (3D surface reconstruction).

### NuGet Packages (via NuGetForUnity)

Install NuGetForUnity first (add via git URL: `https://github.com/GlitchEnzo/NuGetForUnity.git?path=/src/NuGetForUnity`).

Then **NuGet → Manage NuGet Packages** and install:

| Package | Version | Notes |
|---------|---------|-------|
| **MQTTnet** | **4.3.7.x** | Must be v4.x — v5 dropped netstandard and Unity won't load it |
| **SSH.NET** | latest | SSH tunnel to Ultra96 |

NuGetForUnity auto-resolves dependencies (`Microsoft.Bcl.AsyncInterfaces`, `BouncyCastle.Cryptography`, etc.) into `Assets/Packages/`.

## Step 3: Import Scripts

Copy `visualiser/Assets/Scripts/` into your Unity project's `Assets/Scripts/`.

```
Assets/
├── StreamingAssets/
│   └── secrets.json               # Generated — see "Connection Setup" below
├── Scripts/                       # ← copy from this repo
│   ├── Core/
│   │   ├── GameState.cs           # FSM: Idle→Encounter→Catch/Battle→Result
│   │   ├── GestureData.cs         # Data contracts + static event bus
│   │   └── PokemonData.cs         # ScriptableObject for Pokemon stats & model
│   ├── Networking/
│   │   ├── NetworkManager.cs      # Singleton — MQTT lifecycle → GestureEvents
│   │   └── SshMqttClient.cs       # SSH tunnels + MQTT client (plain C#)
│   ├── AR/
│   │   └── PokemonSpawner.cs      # Lightship mesh + semantic terrain spawn
│   ├── Battle/
│   │   ├── BattleManager.cs       # Singleton — turn-based battle + pokeball throw
│   │   └── CatchManager.cs        # Singleton — reticle aim + catch sequence
│   ├── UI/
│   │   ├── BattleHUD.cs           # HP bars, move/action tiles, battle messages
│   │   └── EncounterNotification.cs  # "Wild X appeared!" fade popup
│   └── Debug/
│       ├── MockInputController.cs # Keyboard gesture simulation
│       └── OnScreenControls.cs    # On-screen touch buttons (auto-created at runtime)
├── Models/                        # Create locally — see Step 5
│   ├── Pokemon/                   # .fbx models per Pokemon
│   └── Pokeball/                  # Pokeball .fbx
├── Animations/                    # Animator Controllers per Pokemon
├── Prefabs/                       # Pokemon prefabs, Pokeball prefab, Mesh prefab
├── Materials/                     # Materials for models
└── VFX/                           # Particle effects (sparkle, smoke, fizzle)
```

## Step 4: Configure AR Settings

1. **Edit → Project Settings → XR Plug-in Management**
   - Android tab: Enable **ARCore**
   - iOS tab: Enable **ARKit** (if needed)

2. **Edit → Project Settings → Player**
   - Android:
     - Minimum API Level: **Android 7.0 (API 24)**
     - Scripting Backend: **IL2CPP**
     - Target Architectures: **ARM64**
   - Graphics APIs: **Vulkan** (Unity 6 default, supported by Lightship 4.x)

3. **Niantic → Spatial SDK → Configure Project** (auto-fixes Lightship requirements)

---

## Step 5: Create 3D Models, Animators, and Prefabs

### 5a: Import Pokemon Models

1. Download `.fbx` models (see [Model Resources](#3d-model-resources) below)
2. Place in `Assets/Models/Pokemon/<PokemonName>/`
3. Keep poly count low (< 10k triangles per model) for mobile performance

### 5b: Create Animator Controllers

For **each** Pokemon model, create an Animator Controller in `Assets/Animations/`:

1. Right-click `Assets/Animations/` → **Create → Animator Controller**
2. Name it `<PokemonName>Controller` (e.g. `LucarioController`)
3. Open it and add these **parameters**:

| Parameter | Type | Used for |
|-----------|------|----------|
| `isWalking` | Bool | Ground idle animation |
| `isFlying` | Bool | Flying idle animation |
| `isAttacking` | Trigger | Attack animation |
| `isHit` | Trigger | Damage taken animation |
| `isFainted` | Trigger | Faint/death animation |
| `breakFree` | Trigger | Escape from pokeball |

4. Add states and transitions:

```
Entry → Idle
Idle → Walk        (isWalking = true)
Walk → Idle        (isWalking = false)
Idle → Fly         (isFlying = true)
Fly → Idle         (isFlying = false)
Any State → Attack (isAttacking trigger)
Any State → Hit    (isHit trigger)
Any State → Faint  (isFainted trigger)
Any State → BreakFree (breakFree trigger)
Attack → Idle      (auto on exit)
Hit → Idle         (auto on exit)
BreakFree → Idle   (auto on exit)
```

5. Drag animation clips from the imported `.fbx` into the appropriate states
6. For move-specific animations, add additional trigger parameters matching `MoveData.animationTrigger` values

### 5c: Create Pokemon Prefabs

For each Pokemon:

1. Drag the `.fbx` model into the scene
2. Attach the corresponding **Animator Controller** to its `Animator` component
3. Adjust scale if needed
4. Drag from the Hierarchy into `Assets/Prefabs/` to save as a prefab
5. Delete the instance from the scene

### 5d: Create Pokeball Prefab

1. Import or create a Pokeball `.fbx` model in `Assets/Models/Pokeball/`
2. Drag into scene, adjust scale
3. Save as prefab in `Assets/Prefabs/Pokeball`

### 5e: Create VFX Prefabs

Create three particle-system prefabs in `Assets/VFX/`:

| Prefab | Used for | Suggested look |
|--------|----------|----------------|
| `SparkleVFX` | Catch success | Bright sparkle burst |
| `SmokeVFX` | Pokeball hit/impact | Puff of smoke |
| `FizzleVFX` | Catch miss | Small fizzle particles |

Each should be a GameObject with a **Particle System** component. Set **Play On Awake = true**, **Looping = false**, and a short duration (0.5–1s). They are instantiated at runtime and destroyed after playing.

### 5f: Create PokemonData ScriptableObjects

For each Pokemon:

1. Right-click in Project → **Create → Pokemon → Pokemon Data**
2. Fill in the fields:

| Field | Description |
|-------|-------------|
| `pokemonName` | Display name (e.g. "Lucario") |
| `pokedexNumber` | Pokedex # |
| `primaryType` / `secondaryType` | PokemonType enum |
| `maxHP`, `attack`, `defense`, `speed` | Base stats |
| `spawnBehavior` | Ground, Flying, or Stationary |
| `spawnScale` | World-space scale factor |
| `baseCatchRate` | 0.0–1.0 (higher = easier to catch) |
| `modelPrefab` | Drag the Pokemon prefab from Step 5c |
| `moves[0–3]` | Configure 4 MoveData entries (see below) |

Each **MoveData** entry has:

| Field | Description |
|-------|-------------|
| `moveName` | Display name (e.g. "Punch") |
| `moveType` | PokemonType for type-based tile coloring |
| `power` | Damage value |
| `accuracy` | 0–100 hit chance |
| `isProtect` | true for Guard/Protect moves |
| `animationTrigger` | Animator trigger name for this move |

**Recommended starter set:**

| Pokemon | Role | Type | Catch Rate | Moves |
|---------|------|------|------------|-------|
| Lucario | Player | Fighting | — | Punch, Downward Swipe, Uppercut, Guard (isProtect=true) |
| Eevee | Wild (easy) | Normal | 0.8 | — |
| Machop | Wild (battle) | Fighting | 0.5 | — |

---

## Step 6: Scene Setup (step-by-step)

Create a new scene (**File → New Scene → Basic**), then build this hierarchy.

### 6a: AR Foundation Objects

1. **AR Session**
   - Create empty GameObject, name it `AR Session`
   - Add component: `AR Session`

2. **XR Origin**
   - Create empty GameObject, name it `XR Origin`
   - Add component: `XR Origin`
   - Create a child `AR Camera`:
     - **Tag: MainCamera** (critical — scripts use `Camera.main`)
     - Add components:
       - `AR Camera Manager`
       - `AR Camera Background`
       - `AR Occlusion Manager` (Lightship depth occlusion)
       - `AR Semantic Segmentation Manager` (Lightship terrain detection)
   - Create a child `AR Mesh Manager`:
     - Add component: `AR Mesh Manager`
     - Create a **Mesh Prefab**: empty GameObject with `MeshFilter` + `MeshRenderer` + `MeshCollider`, save to `Assets/Prefabs/LightshipMesh`
     - Assign it to `AR Mesh Manager` → **Mesh Prefab**
     - Enable **Generate Colliders** (so `Physics.Raycast` works on the mesh)

### 6b: Manager GameObjects

Create an empty parent `--- Managers ---` (optional, for organization), then create these children:

| GameObject Name | Component to Add | Inspector Setup |
|----------------|------------------|-----------------|
| `GameStateManager` | `GameStateManager.cs` | No fields to set |
| `NetworkManager` | `NetworkManager.cs` | Set **Model Id** to your FireBeetle ID (empty = accept all). Set **Minimum Confidence** (default 0). |
| `BattleManager` | `BattleManager.cs` | **Player Pokemon**: drag a PokemonData asset. **Pokeball Prefab**: drag Pokeball prefab. **Reticle UI**: drag the Reticle GameObject (created in 6c). **Throw Arc** / **Max Jiggles** / **Jiggle Interval**: tune to taste. |
| `CatchManager` | `CatchManager.cs` | **Pokeball Prefab**: drag Pokeball prefab. **Reticle UI**: drag the Reticle GameObject. **Sparkle VFX**: drag SparkleVFX prefab. **Smoke VFX**: drag SmokeVFX prefab. **Fizzle VFX**: drag FizzleVFX prefab. |
| `PokemonSpawner` | `PokemonSpawner.cs` | Populate **Grass Pool**, **Sky Pool**, **Default Pool** arrays with PokemonData assets. Tune **Spawn Distance**, **Spawn Cooldown**, **Terrain Detection Threshold**. |

### 6c: UI Canvas

1. Create **GameObject → UI → Canvas**
   - Render Mode: **Screen Space - Overlay**
   - Add a **Canvas Scaler** (Scale With Screen Size, reference 1920×1080)

2. Under Canvas, create **BattleHUD** (empty GameObject + `BattleHUD.cs`):

   Build this child hierarchy and wire each to the matching `[SerializeField]` slot:

   ```
   BattleHUD                          → battleHUDPanel (self)
   ├── PlayerHP Panel                 → (layout group)
   │   ├── PlayerNameText (TMP)       → playerNameText
   │   ├── PlayerHPBar (Slider)       → playerHPBar
   │   └── PlayerHPText (TMP)         → playerHPText
   ├── WildHP Panel
   │   ├── WildNameText (TMP)         → wildNameText
   │   ├── WildHPBar (Slider)         → wildHPBar
   │   └── WildHPText (TMP)           → wildHPText
   ├── MovePanel                      → movePanel
   │   ├── MoveTile0 (Image + TMP)    → moveTiles[0], moveTileTexts[0], moveTileImages[0]
   │   ├── MoveTile1                  → moveTiles[1], moveTileTexts[1], moveTileImages[1]
   │   ├── MoveTile2                  → moveTiles[2], moveTileTexts[2], moveTileImages[2]
   │   └── MoveTile3                  → moveTiles[3], moveTileTexts[3], moveTileImages[3]
   ├── ActionPanel                    → actionPanel
   │   ├── CatchTile (Image + TMP)    → catchTile
   │   ├── PokemonTile                → pokemonTile
   │   ├── ItemTile                   → itemTile
   │   └── RunTile                    → runTile
   ├── PromptText (TMP)              → promptText ("What will X do?")
   └── MessageText (TMP)             → messageText
   ```

   Each **MoveTile** is a GameObject with an `Image` component (for type-colored background) and a child `TextMeshProUGUI` (for the move name). Wire the `Image` to `moveTileImages[n]` and the `TMP` to `moveTileTexts[n]`.

   Each **ActionTile** is similar (Image + TMP child). Wire to `catchTile`, `pokemonTile`, `itemTile`, `runTile`.

   The `battleHUDPanel` field should reference the BattleHUD GameObject itself (it gets toggled via `SetActive`).

3. Under Canvas, create **EncounterNotification** (empty GameObject + `EncounterNotification.cs`):

   ```
   EncounterNotification              → notificationPanel (self)
   ├── PokemonNameText (TMP)          → pokemonNameText
   ├── TerrainTypeText (TMP)          → terrainTypeText
   └── ExclamationIcon (Image)        → exclamationIcon
   ```

   A `CanvasGroup` is auto-added at runtime for fade animation. Set the panel to **inactive by default**.

4. Under Canvas, create **Reticle**:
   - Add an `Image` component with a crosshair sprite
   - Anchor to center of screen
   - Set **inactive by default**
   - Drag this into both `BattleManager` → Reticle UI and `CatchManager` → Reticle UI, and `BattleHUD` → Reticle Object

### 6d: Debug Objects

Create an empty parent `--- Debug ---`, then:

| GameObject | Component | Notes |
|------------|-----------|-------|
| `MockInput` | `MockInputController.cs` | Keyboard controls. Toggle `enableMockInput` in Inspector. |
| `OnScreenControls` | `OnScreenControls.cs` | **Must be a child of the Canvas** (uses `GetComponentInParent<Canvas>`). Buttons are auto-created at runtime. |

### Final scene hierarchy

```
Scene Root
├── AR Session                        (AR Session)
├── XR Origin                         (XR Origin)
│   ├── AR Camera                     (MainCamera tag, AR Camera Manager,
│   │                                  AR Camera Background, AROcclusionManager,
│   │                                  ARSemanticSegmentationManager)
│   └── AR Mesh Manager               (ARMeshManager → mesh prefab)
├── --- Managers ---
│   ├── GameStateManager              (GameStateManager.cs)
│   ├── NetworkManager                (NetworkManager.cs)
│   ├── BattleManager                 (BattleManager.cs)
│   ├── CatchManager                  (CatchManager.cs)
│   └── PokemonSpawner                (PokemonSpawner.cs)
├── --- UI ---
│   └── Canvas                        (Screen Space - Overlay)
│       ├── BattleHUD                 (BattleHUD.cs + full child UI)
│       ├── EncounterNotification     (EncounterNotification.cs + children)
│       ├── Reticle                   (Image, centered, default inactive)
│       └── OnScreenControls          (OnScreenControls.cs)
└── --- Debug ---
    └── MockInput                     (MockInputController.cs)
```

**Save the scene** (Ctrl+S / Cmd+S) immediately after setup, and save frequently.

---

## Step 7: Connection Setup

### Generate secrets.json

Option A — use the repo setup script:
```bash
./setup.sh
```

Option B — manual:
```bash
export SOC_USERNAME=your_soc_user
export SOC_PASSWORD=your_soc_pass
export MQTT_USER=your_mqtt_user
export MQTT_PASSWORD=your_mqtt_pass
python3 visualiser/Tools/write_connection_settings.py \
  --key ~/.ssh/esp32_key \
  --output visualiser/Assets/StreamingAssets/secrets.json
```

Copy the generated `secrets.json` into your Unity project's `Assets/StreamingAssets/`.

### Ultra96 side

Run the broker and `python comms/main.py` from `ultra96/`, with existing Python dependencies and MQTT credentials. The phone reaches the broker through SSH jump-host and Ultra96 tunnels.

---

## Step 8: Test in Editor

Press **Play**. The `MockInputController` shows keyboard controls in the top-left corner:

| Key | Action |
|-----|--------|
| `A` | Aim (show reticle) |
| `C` | Catch throw (fire pokeball) |
| `X` | Cancel (hide reticle) |
| `B` | Battle entry (pokeball throw) |
| `1`–`4` | Battle moves 1–4 |
| `R` | Reset to Idle |

`OnScreenControls` creates touch buttons at runtime for on-device testing.

## Step 9: Build to Device

1. **File → Build Settings**
2. Switch platform to Android (or iOS)
3. **Add your scene** to "Scenes in Build"
4. Click **Build and Run**
5. Grant camera permissions on device

---

## Network Protocol

Ultra96 publishes non-retained MQTT messages to `ultra96/<model_id>/inference`.
`SshMqttClient` subscribes; `NetworkManager.Update()` drains its queue,
validates/filters messages, and raises game events on Unity's main thread.

Payload format:

```json
{
  "action": "BATTLE_MOVE",
  "gesture_id": 2,
  "confidence": 0.94,
  "timestamp": 1692345678000
}
```

`timestamp` is Unix time in **milliseconds**. Extra diagnostic fields (`model_id`, `predicted_action`, `window_shape`, etc.) are ignored by Unity.

### Gesture mapping

| Classifier label | Physical gesture | action | gesture_id |
|---|---|---|---|
| `PUNCH` | Punch | `BATTLE_MOVE` | 1 |
| `DOWNWARD_SWIPE` | Downward swipe | `BATTLE_MOVE` | 2 |
| `UPPERCUT` | Uppercut | `BATTLE_MOVE` | 3 |
| `GUARD` | Fist, arm crossing chest | `BATTLE_MOVE` | 4 |
| `FLEE` | U-turn | `BATTLE_ACTION` | 1 |
| `SWITCH_POKEMON` | Back left pocket reach | `BATTLE_ACTION` | 2 |
| `USE_ITEM` | Front left pocket reach | `BATTLE_ACTION` | 3 |
| `AIM` | Throwing arm raised to shoulder | `ARM_PULLBACK` | 0 |
| `THROW` | Throw from Aim position | `CATCH_THROW` | 0 |
| `STOP_AIMING` | Arm returns to neutral | `CANCEL` | 0 |
| `NEUTRAL` | Relaxed arm down | No action* | — |

`GestureSequence` in `ultra96/comms/visualiser_protocol.py` owns per-device
sequencing. It accepts Aim followed by Throw, then requires Stop Aim or Neutral
before another gesture. Stop Aim before Throw cancels; *Neutral also emits
`CANCEL` when returning from an active catch sequence, otherwise it sends nothing.
Throw without Aim is ignored. Repeated windows of a held gesture emit only one
message until a different gesture is accepted or confident Neutral resets it.
Stop Aim while already neutral is ignored and does not clear that repeat filter.
All transitions, including Neutral/reset, require confidence at or above 90%
by default. A rejected MQTT publish leaves the sequence unchanged so a later
valid prediction can retry. MQTT QoS 0 acceptance does not confirm AR delivery.
Touch does not change Throw into battle entry in this gesture set.

For live testing, `ultra96/comms/tests/gesture_demo.py` uses the same inference
path and shows the current prediction, explicit decision reason, last sent
gesture, and sequence state in fixed dashboard rows. See
[`ultra96/comms/tests/README.md`](../ultra96/comms/tests/README.md) for commands
and the test procedure. The 256-sample inference window and 25-sample hop are
unchanged.

`NetworkManager` translates Aim into `BATTLE_CATCH` preparation followed by `ARM_PULLBACK`; catch preparation is ignored in the encounter phase. Configure Pokemon move slots to match this order (Guard/Protect in slot 4).

### All supported actions

| action | gesture_id | Trigger |
|--------|-----------|---------|
| `ARM_PULLBACK` | 0 | Arm draws back (show reticle) |
| `CATCH_THROW` | 0 | Overhead throw release (fire pokeball) |
| `POKEBALL_THROW` | 0 | UI/debug battle entry (not in classifier set) |
| `BATTLE_MOVE` | 1–4 | Punch / Swipe / Uppercut / Guard |
| `BATTLE_ACTION` | 1–4 | Run / Switch / Item / Catch |
| `CANCEL` | 0 | Cancel action |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│  FireBeetle / IMU Sensors                           │
│  (Worn on wrists/body)                              │
└──────────────┬──────────────────────────────────────┘
               │ Sensor data (Bluetooth/WiFi)
               ▼
┌─────────────────────────────────────────────────────┐
│  Ultra96 / Laptop (AI Pipeline)                     │
│  - Gesture recognition model (DPU)                  │
│  - Classifies: punch, block, throw, pullback, etc.  │
└──────────────┬──────────────────────────────────────┘
               │ MQTT JSON over SSH
               ▼
┌─────────────────────────────────────────────────────┐
│  Phone (Unity 6 AR App + Niantic Spatial SDK 4.1)   │
│  ┌─────────────────────────────────────────────┐    │
│  │ NetworkManager → GestureEvents              │    │
│  │      ↓                                      │    │
│  │ GameStateManager (FSM)                      │    │
│  │      ↓ Phase transitions                    │    │
│  │ CatchManager / BattleManager                │    │
│  │      ↓ Animations + VFX                     │    │
│  │ Lightship: Semantic Segmentation            │    │
│  │      ↓ Terrain-aware Pokemon spawning       │    │
│  │ Lightship: Depth Occlusion + Meshing        │    │
│  │      ↓ Pokemon hidden behind real objects   │    │
│  │ AR Camera + 3D Pokemon Models               │    │
│  └─────────────────────────────────────────────┘    │
│  + Haptic feedback (vibration on hit)               │
└─────────────────────────────────────────────────────┘
```

---

## 3D Model Resources

- **Spriters Resource**: https://models.spriters-resource.com/ (animated models)
- **Sketchfab**: Search "Pokemon low poly" (check licenses)
- Recommended format: **.fbx** (best Unity compatibility with animations)
- Keep poly count low (< 10k triangles per model) for mobile performance
