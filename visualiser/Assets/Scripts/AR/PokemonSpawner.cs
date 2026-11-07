using System.Collections.Generic;
using UnityEngine;
using UnityEngine.XR.ARFoundation;
using UnityEngine.XR.Management;
using NianticSpatial.NSDK.AR.Subsystems.SceneSegmentation;
using NianticSpatial.NSDK.AR.XRSubsystems;

public class PokemonSpawner : MonoBehaviour
{
    [Header("Spawn Settings")]
    [SerializeField] private float spawnDistance = 5f;
    [SerializeField] private float minSpawnDistance = 2f;
    [SerializeField] private float spawnCooldown = 10f;
    [SerializeField] private float meshRaycastDistance = 10f;
    [SerializeField] private float minSpawnClearance = 1f;
    [SerializeField] private int maxWildPokemon = 3;

    [Header("Pokemon Pools")]
    [SerializeField] private PokemonData[] grassPool;
    [SerializeField] private PokemonData[] skyPool;
    [SerializeField] private PokemonData[] defaultPool;

    private List<WildPokemonInstance> wildPokemon = new List<WildPokemonInstance>();
    private WildPokemonInstance engagedPokemon;
    private float lastSpawnTime;
    private NsdkSceneSegmentationSubsystem _segmentationSubsystem;
    private string lastDetectedTerrain = "Unknown";

    public PokemonData CurrentPokemonData => engagedPokemon?.Data;
    public GameObject CurrentWildPokemon => engagedPokemon?.GameObject;
    public string LastDetectedTerrain => lastDetectedTerrain;
    public WildPokemonInstance EngagedPokemon => engagedPokemon;
    public IReadOnlyList<WildPokemonInstance> AllWildPokemon => wildPokemon;

    public delegate void PokemonSpawnedHandler(WildPokemonInstance instance);
    public event PokemonSpawnedHandler OnPokemonSpawned;

    private void OnEnable()
    {
        if (GameStateManager.Instance != null)
            GameStateManager.Instance.OnPhaseChanged += HandlePhaseChanged;
    }

    private void Start()
    {
        if (GameStateManager.Instance != null)
            GameStateManager.Instance.OnPhaseChanged -= HandlePhaseChanged;
        if (GameStateManager.Instance != null)
            GameStateManager.Instance.OnPhaseChanged += HandlePhaseChanged;
    }

    private void OnDisable()
    {
        if (GameStateManager.Instance != null)
            GameStateManager.Instance.OnPhaseChanged -= HandlePhaseChanged;
    }

    private void Update()
    {
        if (GameStateManager.Instance == null) return;
        if (GameStateManager.Instance.CurrentPhase != GamePhase.Idle) return;

        wildPokemon.RemoveAll(w => w.GameObject == null);

        if (wildPokemon.Count >= maxWildPokemon) return;
        if (Time.time - lastSpawnTime < spawnCooldown) return;

        TrySpawnWildPokemon();
    }

    private bool TryAcquireSubsystem()
    {
        if (_segmentationSubsystem != null) return true;

        var xrManager = XRGeneralSettings.Instance?.Manager;
        if (xrManager == null || !xrManager.isInitializationComplete) return false;

        _segmentationSubsystem = xrManager.activeLoader?
            .GetLoadedSubsystem<XRSceneSegmentationSubsystem>() as NsdkSceneSegmentationSubsystem;

        return _segmentationSubsystem != null;
    }

    private void TrySpawnWildPokemon()
    {
        Vector3 spawnPosition;

        if (TryGetValidSpawnPosition(out spawnPosition))
        {
            Debug.Log($"[Spawner] Valid position at {spawnPosition}");
            PokemonData pokemon = PickPokemonByTerrain(spawnPosition);
            SpawnPokemonAt(spawnPosition, pokemon);
        }
        else
        {
#if UNITY_EDITOR
            if (TryGetEditorFallbackPosition(out spawnPosition))
            {
                Debug.Log("[Spawner] Editor fallback spawn");
                PokemonData pokemon = PickPokemonByTerrain(spawnPosition);
                SpawnPokemonAt(spawnPosition, pokemon);
            }
#else
            Debug.Log("[Spawner] No valid position found, skipping spawn");
#endif
        }
    }

    private bool TryGetValidSpawnPosition(out Vector3 position)
    {
        position = Vector3.zero;
        int maxAttempts = 10;
        Transform cam = Camera.main.transform;

        for (int i = 0; i < maxAttempts; i++)
        {
            float angle = Random.Range(0f, 360f);
            float distance = Random.Range(minSpawnDistance, spawnDistance);

            Vector3 offset = new Vector3(
                Mathf.Sin(angle * Mathf.Deg2Rad) * distance,
                0f,
                Mathf.Cos(angle * Mathf.Deg2Rad) * distance
            );
            Vector3 candidateXZ = cam.position + offset;

            Vector3 rayOrigin = new Vector3(candidateXZ.x, cam.position.y + 3f, candidateXZ.z);
            if (!Physics.Raycast(rayOrigin, Vector3.down, out RaycastHit hit, meshRaycastDistance)) continue;

            float upDot = Vector3.Dot(hit.normal, Vector3.up);
            if (upDot < 0.7f) continue;

            if (!HasClearance(hit.point)) continue;

            if (!HasDistanceFromExisting(hit.point)) continue;

            position = hit.point;
            return true;
        }

        return false;
    }

#if UNITY_EDITOR
    private bool TryGetEditorFallbackPosition(out Vector3 position)
    {
        position = Vector3.zero;
        Transform cam = Camera.main.transform;
        int maxAttempts = 10;

        for (int i = 0; i < maxAttempts; i++)
        {
            float angle = Random.Range(0f, 360f);
            float distance = Random.Range(minSpawnDistance, spawnDistance);

            Vector3 offset = new Vector3(
                Mathf.Sin(angle * Mathf.Deg2Rad) * distance,
                0f,
                Mathf.Cos(angle * Mathf.Deg2Rad) * distance
            );
            position = cam.position + offset;
            position.y = cam.position.y - 1f;

            if (HasDistanceFromExisting(position))
                return true;
        }

        return false;
    }
#endif

    private bool HasClearance(Vector3 position)
    {
        Vector3[] directions = { Vector3.forward, Vector3.back, Vector3.left, Vector3.right };

        foreach (var dir in directions)
        {
            if (Physics.Raycast(position + Vector3.up * 0.3f, dir, minSpawnClearance))
                return false;

            Vector3 checkPos = position + dir * minSpawnClearance + Vector3.up * 0.5f;
            if (!Physics.Raycast(checkPos, Vector3.down, out RaycastHit groundHit, 1.5f))
                return false;

            if (Mathf.Abs(groundHit.point.y - position.y) > 0.3f)
                return false;
        }

        return true;
    }

    private bool HasDistanceFromExisting(Vector3 position)
    {
        foreach (var existing in wildPokemon)
        {
            if (existing.GameObject == null) continue;
            if (Vector3.Distance(existing.GameObject.transform.position, position) < minSpawnClearance)
                return false;
        }
        return true;
    }

    private PokemonData PickPokemonByTerrain(Vector3 worldPosition)
    {
        if (!TryAcquireSubsystem() || !_segmentationSubsystem.running)
        {
            lastDetectedTerrain = "Default (no segmentation)";
            return PickFromPool(defaultPool);
        }

        if (TryCheckChannel(SceneSegmentationChannel.Grass, worldPosition) && grassPool.Length > 0)
        {
            lastDetectedTerrain = "Grass";
            return PickFromPool(grassPool);
        }

        if (TryCheckChannel(SceneSegmentationChannel.NaturalGround, worldPosition) && grassPool.Length > 0)
        {
            lastDetectedTerrain = "Natural Ground";
            return PickFromPool(grassPool);
        }

        if (TryCheckChannel(SceneSegmentationChannel.Sky, worldPosition) && skyPool.Length > 0)
        {
            lastDetectedTerrain = "Sky";
            return PickFromPool(skyPool);
        }

        if (TryCheckChannel(SceneSegmentationChannel.ArtificialGround, worldPosition))
        {
            lastDetectedTerrain = "Artificial Ground";
            return PickFromPool(defaultPool);
        }

        if (TryCheckChannel(SceneSegmentationChannel.Ground, worldPosition))
        {
            lastDetectedTerrain = "Ground";
            return PickFromPool(defaultPool);
        }

        lastDetectedTerrain = "Default";
        return PickFromPool(defaultPool);
    }

    [SerializeField] private float terrainDetectionThreshold = 0.05f;

    private bool TryCheckChannel(SceneSegmentationChannel channel, Vector3 worldPosition)
    {
        if (_segmentationSubsystem == null) return false;

        if (!_segmentationSubsystem.TryAcquireSceneSegmentationChannelCpuImage(
                channel: channel,
                cameraParams: null,
                cpuImage: out var cpuImage,
                samplerMatrix: out _))
        {
            return false;
        }

        var plane = cpuImage.GetPlane(0);
        int totalPixels = cpuImage.width * cpuImage.height;
        int pixelCount = Mathf.Min(plane.data.Length, totalPixels);

        int aboveThreshold = 0;
        for (int i = 0; i < pixelCount; i++)
        {
            if (plane.data[i] > 128) aboveThreshold++;
        }

        float coverage = (float)aboveThreshold / pixelCount;
        bool isPresent = coverage > terrainDetectionThreshold;

        Debug.Log($"[Terrain] {channel}: {aboveThreshold}/{pixelCount} pixels ({coverage:P1}), threshold={terrainDetectionThreshold:P0}, detected={isPresent}");

        cpuImage.Dispose();
        return isPresent;
    }

    private PokemonData PickFromPool(PokemonData[] pool)
    {
        if (pool == null || pool.Length == 0)
            return defaultPool[Random.Range(0, defaultPool.Length)];
        return pool[Random.Range(0, pool.Length)];
    }

    private void SpawnPokemonAt(Vector3 position, PokemonData pokemon)
    {
        if (pokemon.modelPrefab == null)
        {
            Debug.LogError($"[Spawner] {pokemon.pokemonName} has no model prefab assigned!");
            return;
        }

        if (pokemon.spawnBehavior == SpawnBehavior.Flying)
        {
            position.y += 1.5f;
        }

        GameObject go = Instantiate(
            pokemon.modelPrefab,
            position,
            pokemon.modelPrefab.transform.rotation
        );
        go.transform.localScale = Vector3.one * pokemon.spawnScale;
        Vector3 prefabAngles = pokemon.modelPrefab.transform.rotation.eulerAngles;
        go.transform.rotation = Quaternion.Euler(prefabAngles.x, Random.Range(0f, 360f), prefabAngles.z);

        Animator anim = go.GetComponent<Animator>();
        if (anim != null)
        {
            anim.SetBool("isWalking", pokemon.spawnBehavior == SpawnBehavior.Ground);
            anim.SetBool("isFlying", pokemon.spawnBehavior == SpawnBehavior.Flying);
        }

        var instance = new WildPokemonInstance(go, pokemon, lastDetectedTerrain);
        wildPokemon.Add(instance);
        lastSpawnTime = Time.time;

        Debug.Log($"[Spawner] Wild {pokemon.pokemonName} appeared at {position}! ({wildPokemon.Count}/{maxWildPokemon} active)");
        OnPokemonSpawned?.Invoke(instance);
    }

    private void HandlePhaseChanged(GamePhase oldPhase, GamePhase newPhase)
    {
        if (newPhase == GamePhase.Idle)
        {
            DisengagePokemon();
        }
    }

    public void EngagePokemon(WildPokemonInstance instance)
    {
        engagedPokemon = instance;
    }

    public void DisengagePokemon()
    {
        engagedPokemon = null;
    }

    public void RemoveWildPokemon(WildPokemonInstance instance)
    {
        if (instance == null) return;
        wildPokemon.Remove(instance);
        if (instance.GameObject != null)
            Destroy(instance.GameObject);
        if (engagedPokemon == instance)
            engagedPokemon = null;
    }

    public void ForceSpawn(PokemonData pokemon = null)
    {
        if (GameStateManager.Instance != null &&
            GameStateManager.Instance.CurrentPhase != GamePhase.Idle)
            return;

        Transform cam = Camera.main.transform;
        Vector3 spawnPosition = cam.position + cam.forward * spawnDistance;
        spawnPosition.y = cam.position.y - 1f;

        PokemonData chosen = pokemon ?? PickFromPool(defaultPool);
        SpawnPokemonAt(spawnPosition, chosen);

        var spawned = wildPokemon[wildPokemon.Count - 1];
        EngagePokemon(spawned);
        GameStateManager.Instance.TransitionTo(GamePhase.Encounter);
    }

    public void DespawnWild()
    {
        for (int i = wildPokemon.Count - 1; i >= 0; i--)
        {
            if (wildPokemon[i].GameObject != null)
                Destroy(wildPokemon[i].GameObject);
        }
        wildPokemon.Clear();
        engagedPokemon = null;
    }
}
