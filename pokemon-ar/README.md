# CG4002 Pokemon AR - Unity Setup Guide

## Prerequisites

- **Unity Hub** + **Unity 6** (6000.x)
- **Android Build Support** module (install via Unity Hub > Installs > Add Modules)
- Android device with **ARCore** support (or iOS with ARKit)
- Python 3.x (for mock server testing)

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

Copy the entire `Assets/Scripts/` folder from this repo into your Unity project's `Assets/` folder.

```
Assets/
├── Scripts/
│   ├── Core/
│   │   ├── GameState.cs          # FSM: Idle→Encounter→Catch/Battle→Result
│   │   ├── GestureData.cs        # Data contracts + event system
│   │   └── PokemonData.cs        # ScriptableObject for Pokemon stats
│   ├── Networking/
│   │   └── NetworkManager.cs     # UDP/TCP listener for gesture signals
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
| Lucario | Player's Pokemon | Close Combat, Protect, Brick Break, Drain Punch |
| Eevee | Wild (easy catch) | - |
| Machop | Wild (battle) | - |

## Step 7: Wire Up References

In the Inspector for each Manager:
- **PokemonSpawner**: Assign `ARSemanticSegmentationManager`, populate terrain pools (grassPool, waterPool, flyingPool, defaultPool)
- **BattleManager**: Assign the player's PokemonData ScriptableObject
- **CatchManager**: Assign Pokeball prefab, VFX prefabs (sparkle, smoke, fizzle), reticle UI object
- **BattleHUD**: Assign all UI text/slider references, reticle GameObject
- **NetworkManager**: Set port (default 8888), choose UDP or TCP mode

## Step 8: Test with Mock Server

### Option A: Keyboard (in Unity Editor)
Just press Play. The MockInputController shows controls in top-left:
- `A` = Aim (show reticle)
- `C` = Catch throw (fire Pokeball)
- `X` = Cancel (hide reticle)
- `B` = Battle entry
- `1-4` = Battle moves
- `R` = Reset

### Option B: Python UDP sender (simulates external hardware)
```bash
cd MockServer
python mock_gesture_server.py --ip 127.0.0.1 --port 8888
```

### Option C: Automated sequence
```bash
python continuous_mock.py --mode battle   # Auto-runs a battle
python continuous_mock.py --mode catch    # Auto-runs a catch (with aiming)
python continuous_mock.py --mode random   # Alternates randomly
```

## Step 9: Build to Device

1. **File → Build Settings**
2. Switch platform to Android (or iOS)
3. Add your scene to "Scenes in Build"
4. Click **Build and Run**
5. Grant camera permissions on device

---

## Network Protocol

The AI pipeline (Ultra96/laptop) sends JSON over UDP to port 8888:

```json
{
  "action": "BATTLE_MOVE",
  "gesture_id": 2,
  "confidence": 0.94,
  "timestamp": 1692345678000
}
```

### Action Types:

| action | gesture_id | Trigger |
|--------|-----------|---------|
| `ARM_PULLBACK` | 0 | Arm draws back (show reticle) |
| `CATCH_THROW` | 0 | Overhead throw release (fire Pokeball) |
| `POKEBALL_THROW` | 0 | Underhand throw motion (enter battle) |
| `BATTLE_MOVE` | 1 | Many punches (Close Combat) |
| `BATTLE_MOVE` | 2 | Block stance (Protect) |
| `BATTLE_MOVE` | 3 | Up-to-down motion (Brick Break) |
| `BATTLE_MOVE` | 4 | Single punch (Drain Punch) |
| `DODGE` | 0 | Dodge motion (future) |
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
               │ UDP JSON payload
               ▼
┌─────────────────────────────────────────────────────┐
│  Phone (Unity 6 AR App + Niantic Spatial SDK 4.1)   │
│  ┌─────────────────────────────────────────────┐    │
│  │ NetworkManager (listens on port 8888)       │    │
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
3. Test UDP communication with the Python mock server
4. Integrate with the actual Ultra96 AI pipeline
5. Verify Lightship semantic segmentation maps terrain correctly to Pokemon types
6. Add VFX (particle systems for sparkles, smoke, fizzle, hit effects)
