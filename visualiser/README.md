# CG4002 Visualiser — AR game and communications

This folder combines the former `pokemon-ar/` game source with the SSH/MQTT API.
Both `NetworkManager.cs` and `SshMqttClient.cs` live in `Assets/Scripts/Networking/`.
`NetworkManager` loads connection settings, creates and manages `SshMqttClient`,
and delivers gestures through the existing `GestureEvents` bus. The gameplay
scripts remain unchanged.
This repository contains scripts and documentation to import into a
separately created Unity project. Scenes, models, prefabs, package binaries,
ProjectSettings and Unity-generated `.meta` files stay local.

## Live comms quick start

1. Run the repository root `./setup.sh`. It now also writes the ignored
   `visualiser/Assets/StreamingAssets/secrets.json` used by `NetworkManager`.
   Run it from this worktree when preparing this version. For Unity-only settings,
   export `SOC_USERNAME`, `SOC_PASSWORD`, `MQTT_USER`, `MQTT_PASSWORD`, then run
   `python3 visualiser/Tools/write_connection_settings.py --key ~/.ssh/esp32_key --output visualiser/Assets/StreamingAssets/secrets.json`.
2. Copy `visualiser/Assets/Scripts/` into your Unity project's `Assets/Scripts/`,
   and copy the generated `secrets.json` into `Assets/StreamingAssets/`. Unity
   creates `.meta` files locally. Include the MQTTnet and SSH.NET assemblies and
   their dependencies from the comms project. The client uses MQTTnet's
   `MqttFactory`/`PayloadSegment` API and SSH.NET's `ConnectAsync` API.
3. Add `NetworkManager` to the scene's NetworkManager object. It creates
   `SshMqttClient` and connects using MQTT over TCP through the SSH tunnels.
   No transport selection or additional networking component is required.
4. Set **Model Id** to your FireBeetle ID to select a player/device. Empty accepts
   all devices for single-device demos. **Minimum Confidence** defaults to zero.
   `NetworkManager.IsConnected` and `Status` report the connection. `Reconnect()`
   reconnects; application pause/disable cancels the connection, and resume/enable
   restarts it. Haptic/config commands use `NetworkManager.Client.SendHapticAsync`
   and `SendConfigAsync` through the same connection.
5. On Ultra96, run the broker and `python comms/main.py`
   from `ultra96/`, with the existing Python dependencies and MQTT credentials.
   This connects to the local broker on port 1883. The phone reaches that broker
   through the existing SSH jump-host and Ultra96 tunnels.

`main.py` still uses random placeholder inference. This integration defines the
eleven-label comms contract using the existing training/FPGA class order.
The model hookup remains separate from this integration.
Do not interpret game `gesture_id` values as neural-network class indices.

NetworkManager prepares the existing battle catch handler before dispatching
Aim, so Aim → Throw works without a separate Catch button. Existing gameplay
semantics otherwise apply: U-turn requests Run (the game currently asks for a
second Run to confirm), and the pocket actions currently show the game's
"Coming Soon" messages. Actual menus, model retraining and game rules are outside
this comms integration. The new physical set has no battle-entry gesture;
`POKEBALL_THROW` remains available through the existing UI/debug controls.

## Unity setup

## Prerequisites

- **Unity Hub** + **Unity 6** (6000.x)
- **Android Build Support** module (install via Unity Hub > Installs > Add Modules)
- Android device with **ARCore** support (or iOS with ARKit)

---

## Step 1: Create Unity Project

1. Open Unity Hub → New Project
2. Select **3D (URP)** template (Universal Render Pipeline)
3. Name: `CG4002-Pokemon-AR`
4. Create Project

## Step 2: Install Required Packages

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

1. Open **Window → Package Manager**
2. Click **+** → **Add package by name**
3. Enter: `com.nianticspatial.nsdk` version **4.1.0**
4. Alternatively, add to `Packages/manifest.json`:
   ```json
   "com.nianticspatial.nsdk": "4.1.0"
   ```
5. After import, go to **Niantic → Spatial SDK → Configure Project** to auto-fix project settings

The Niantic Spatial SDK 4.1.0 provides:
- **Semantic Segmentation** (on-device terrain classification: grass, water, sky, etc.)
- **Depth & Occlusion** (Pokemon hide behind real objects)
- **Meshing** (3D reconstruction of physical surfaces for accurate placement)

## Step 3: Import Scripts

Copy `visualiser/Assets/Scripts/` into your Unity project's `Assets/Scripts/` folder. Include the comms dependencies and generated connection
settings described above. The layout below includes folders you create locally;
only the C# sources in Scripts are versioned under `visualiser/Assets/`.
Unity-generated `.meta` files and locally created assets are ignored by this repo.

```
Assets/
├── StreamingAssets/               # Generated secrets.json (ignored by Git)
├── Scripts/
│   ├── Core/
│   │   ├── GameState.cs          # FSM: Idle→Encounter→Catch/Battle→Result
│   │   ├── GestureData.cs        # Data contracts + event system
│   │   └── PokemonData.cs        # ScriptableObject for Pokemon stats
│   ├── Networking/
│   │   ├── NetworkManager.cs     # Settings, lifecycle, transport → GestureEvents
│   │   └── SshMqttClient.cs      # SSH tunnels and MQTT API
│   ├── AR/
│   │   └── PokemonSpawner.cs     # Lightship mesh + semantic spawn
│   ├── Battle/
│   │   ├── BattleManager.cs      # Turn-based battle logic
│   │   └── CatchManager.cs       # Reticle aiming + Pokeball throw + capture sequence
│   ├── UI/
│   │   ├── BattleHUD.cs          # HP bars, move panel, messages, reticle
│   │   └── EncounterNotification.cs  # "Wild X appeared!" popup
│   └── Debug/
│       └── MockInputController.cs # Keyboard shortcuts for testing
├── Models/
│   ├── Pokemon/                   # Place .fbx/.gltf models here
│   └── Pokeball/                  # Pokeball model
├── Animations/                    # Animator Controllers
├── Prefabs/                       # Pokemon prefabs with animators
├── Materials/
└── VFX/                           # Particle effects (sparkles, smoke, fizzle)
```

## Step 4: Scene Setup

Create a scene with this hierarchy:

```
Scene Root
├── AR Session                     (Add: AR Session component)
├── XR Origin                      (Add: XR Origin component)
│   ├── AR Camera                  (Tag: MainCamera)
│   │   ├── AR Camera Manager
│   │   ├── AR Camera Background
│   │   ├── AROcclusionManager              ← Lightship depth occlusion
│   │   └── ARSemanticSegmentationManager   ← Lightship terrain detection
│   └── AR Mesh Manager            (Add: ARMeshManager + mesh prefab with MeshCollider)
├── --- Managers ---
│   ├── GameStateManager           (Add: GameStateManager.cs)
│   ├── NetworkManager             (Add: NetworkManager.cs)
│   ├── BattleManager              (Add: BattleManager.cs)
│   ├── CatchManager               (Add: CatchManager.cs)
│   └── PokemonSpawner             (Add: PokemonSpawner.cs)
├── --- UI ---
│   └── Canvas (Screen Space - Overlay)
│       ├── BattleHUD              (Add: BattleHUD.cs)
│       │   ├── PlayerHP Panel
│       │   ├── WildHP Panel
│       │   ├── MovePanel
│       │   └── MessageText
│       ├── EncounterNotification  (Add: EncounterNotification.cs)
│       └── Reticle                (Image: crosshair, centered, default inactive)
└── --- Debug ---
    └── MockInput                  (Add: MockInputController.cs)
```

### Lightship Mesh Prefab Setup

1. Create an empty GameObject, add `MeshFilter`, `MeshRenderer`, and `MeshCollider`
2. Save as prefab in `Assets/Prefabs/LightshipMesh`
3. Assign to `ARMeshManager` → Mesh Prefab field
4. Enable **Generate Colliders** on `ARMeshManager` so `Physics.Raycast` can hit the mesh

## Step 5: Configure AR

1. **Edit → Project Settings → XR Plug-in Management**
   - Android tab: Enable **ARCore**
   - iOS tab: Enable **ARKit** (if needed)

2. **Edit → Project Settings → Player**
   - Android:
     - Minimum API Level: **Android 7.0 (API 24)**
     - Scripting Backend: **IL2CPP**
     - Target Architectures: **ARM64**
   - Other Settings:
     - Graphics APIs: **Vulkan** (Unity 6 default, supported by Lightship 4.x)

3. **Niantic → Spatial SDK → Configure Project** (auto-fixes Lightship requirements)

## Step 6: Create Pokemon Assets

1. Import 3D models (.fbx) into `Assets/Models/Pokemon/`
2. For each Pokemon model:
   - Create an **Animator Controller** in `Assets/Animations/`
   - Add states: Idle, Walk, Attack, Hit, Faint, BreakFree
   - Add trigger parameters: `isAttacking`, `isHit`, `isFainted`, `breakFree`
   - Add bool parameters: `isWalking`, `isFlying`
3. Create a **Prefab** (drag model to scene, attach Animator, drag to `Assets/Prefabs/`)
4. Create a **PokemonData** ScriptableObject:
   - Right-click in Project → Create → Pokemon → Pokemon Data
   - Fill in stats, assign the prefab, set catch rate

### Recommended Starter Pokemon (Fighting type for gesture demo):

| Pokemon | Role | Moves |
|---------|------|-------|
| Lucario | Player's Pokemon | Configure slots for Punch, Downward Swipe, Uppercut, Guard |
| Eevee | Wild (easy catch) | - |
| Machop | Wild (battle) | - |

## Step 7: Wire Up References

In the Inspector for each Manager:
- **PokemonSpawner**: Assign `ARSemanticSegmentationManager`, populate terrain pools (grassPool, waterPool, flyingPool, defaultPool)
- **BattleManager**: Assign the player's PokemonData ScriptableObject
- **CatchManager**: Assign Pokeball prefab, VFX prefabs (sparkle, smoke, fizzle), reticle UI object
- **BattleHUD**: Assign all UI text/slider references, reticle GameObject
- **NetworkManager**: Set Model Id and optional Minimum Confidence.

## Step 8: Check Gameplay in Unity Editor
Just press Play. The MockInputController shows controls in top-left:
- `A` = Aim (show reticle)
- `C` = Catch throw (fire Pokeball)
- `X` = Cancel (hide reticle)
- `B` = Battle entry
- `1-4` = Battle moves
- `R` = Reset

## Step 9: Build to Device

1. **File → Build Settings**
2. Switch platform to Android (or iOS)
3. Add your scene to "Scenes in Build"
4. Click **Build and Run**
5. Grant camera permissions on device

---

## Network Protocol

Ultra96 publishes a non-retained MQTT message to `ultra96/<model_id>/inference`.
`SshMqttClient` subscribes, then `NetworkManager.Update()` drains its queue,
validates/filters messages and raises the existing game events on Unity's main thread.
NetworkManager ignores telemetry/status topics when dispatching gestures.

The gameplay payload is:

```json
{
  "action": "BATTLE_MOVE",
  "gesture_id": 2,
  "confidence": 0.94,
  "timestamp": 1692345678000
}
```

`timestamp` is Unix time in **milliseconds**, not the device's uptime. Live
messages also include `model_id`, `predicted_action`, `window_shape`,
`sample_sequence`, `sample_timestamp_ms`, `skipped_windows`, and the legacy
`timestamp_ms` alias. Unity ignores these extra diagnostic fields.

### New gesture set → JSON

| Classifier label | Physical gesture | action | gesture_id |
|---|---|---|---|
| `PUNCH` | Punch | `BATTLE_MOVE` | 1 |
| `DOWNWARD_SWIPE` | Downward swipe | `BATTLE_MOVE` | 2 |
| `UPPERCUT` | Uppercut | `BATTLE_MOVE` | 3 |
| `GUARD` | Fist, arm crossing chest | `BATTLE_MOVE` | 4 |
| `FLEE` | U-turn | `BATTLE_ACTION` | 1 |
| `SWITCH_POKEMON` | Back left pocket reach | `BATTLE_ACTION` | 2 |
| `USE_ITEM` | Front left pocket reach | `BATTLE_ACTION` | 3 |
| `AIM` | Throwing right arm raised to shoulder level | `ARM_PULLBACK` | 0 |
| `THROW` | Throw from Aim position | `CATCH_THROW` | 0 |
| `STOP_AIMING` | Arm returns to neutral | `CANCEL` | 0 |
| `NEUTRAL` | Relaxed right arm down, facing ground | No action* | — |

`GestureSequence` in `ultra96/comms/visualiser_protocol.py` owns per-device
sequencing. It accepts Aim followed by Throw, then requires Stop Aim or Neutral
before another gesture. Stop Aim before Throw cancels; *Neutral also emits
`CANCEL` when returning from an active catch sequence, otherwise it sends nothing.
Throw without Aim is ignored. Repeated windows of a held gesture emit only one
message until the recognized label changes/reset occurs. Touch does not change
Throw into battle entry in this gesture set.

`NetworkManager` translates Aim into the existing `BATTLE_CATCH` preparation event
followed by `ARM_PULLBACK`; catch preparation is ignored in the encounter phase.
The JSON itself remains the same four-field contract. Configure Pokemon move
slots to match this order (Guard/Protect in slot 4); existing assets and legacy
debug labels are not rewritten by the comms layer.

### All supported game actions:

| action | gesture_id | Trigger |
|--------|-----------|---------|
| `ARM_PULLBACK` | 0 | Arm draws back (show reticle) |
| `CATCH_THROW` | 0 | Overhead throw release (fire Pokeball) |
| `POKEBALL_THROW` | 0 | Existing UI/debug battle entry (not in new classifier set) |
| `BATTLE_MOVE` | 1 | Punch |
| `BATTLE_MOVE` | 2 | Downward Swipe |
| `BATTLE_MOVE` | 3 | Uppercut |
| `BATTLE_MOVE` | 4 | Guard |
| `BATTLE_ACTION` | 1–4 | Run, switch Pokemon, item, catch respectively |
| `CANCEL` | 0 | Hand drops / cancel action |

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
│  │      ↓ GestureEvents                       │    │
│  │ GameStateManager (FSM)                      │    │
│  │      ↓ Phase transitions                   │    │
│  │ CatchManager / BattleManager               │    │
│  │      ↓ Animations + VFX                    │    │
│  │ Lightship: Semantic Segmentation            │    │
│  │      ↓ Terrain-aware Pokemon spawning      │    │
│  │ Lightship: Depth Occlusion + Meshing        │    │
│  │      ↓ Pokemon hidden behind real objects  │    │
│  │ AR Camera + 3D Pokemon Models              │    │
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

## Next Steps

1. Import 2-3 Pokemon models and set up Animator Controllers
2. Test the full flow in Editor with MockInputController
3. Verify the phone receives MQTT inference messages through the SSH tunnels
4. Replace Ultra96 placeholder inference with the actual classifier
5. Verify Lightship semantic segmentation maps terrain correctly to Pokemon types
6. Add VFX (particle systems for sparkles, smoke, fizzle, hit effects)
