using System.Collections.Generic;
using UnityEngine;
using UnityEngine.XR.ARFoundation;
using UnityEngine.XR.Management;
using NianticSpatial.NSDK.AR.Subsystems.SceneSegmentation;
using NianticSpatial.NSDK.AR.XRSubsystems;

public class PokemonSpawner : MonoBehaviour
{
    [Header("Spawn Settings")]
    [SerializeField] private float spawnDistance = 3f;
    [SerializeField] private float spawnCooldown = 10f;
    [SerializeField] private float encounterRadius = 0.5f;
    [SerializeField] private float meshRaycastDistance = 10f;

    [Header("Pokemon Pools")]
    [SerializeField] private PokemonData[] grassPool;
    [SerializeField] private PokemonData[] skyPool;
    [SerializeField] private PokemonData[] defaultPool;

    [Header("Runtime")]
    [SerializeField] private GameObject currentWildPokemon;
    [SerializeField] private PokemonData currentPokemonData;

    private float lastSpawnTime;
    private Animator currentAnimator;
    private NsdkSceneSegmentationSubsystem _segmentationSubsystem;

    private string lastDetectedTerrain = "Unknown";

    public PokemonData CurrentPokemonData => currentPokemonData;
    public GameObject CurrentWildPokemon => currentWildPokemon;
    public string LastDetectedTerrain => lastDetectedTerrain;

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

        if (TryGetMeshSpawnPosition(out spawnPosition))
        {
            Debug.Log($"[Spawner] Mesh hit at {spawnPosition}");
            SpawnPokemon(spawnPosition);
        }
        else
        {
#if UNITY_EDITOR
            Transform cam = Camera.main.transform;
            spawnPosition = cam.position + cam.forward * spawnDistance;
            spawnPosition.y = cam.position.y - 1f;
            Debug.Log("[Spawner] Editor fallback spawn");
            SpawnPokemon(spawnPosition);
#else
            Debug.Log("[Spawner] No mesh hit, skipping spawn (waiting for AR mesh)");
#endif
        }
    }

    private bool TryGetMeshSpawnPosition(out Vector3 position)
    {
        position = Vector3.zero;

        // Try multiple random screen positions to find a horizontal (ground) surface
        int maxAttempts = 10;
        for (int i = 0; i < maxAttempts; i++)
        {
            float screenX = Random.Range(Screen.width * 0.15f, Screen.width * 0.85f);
            float screenY = Random.Range(Screen.height * 0.3f, Screen.height * 0.8f);

            Ray ray = Camera.main.ScreenPointToRay(new Vector3(screenX, screenY, 0));

            if (Physics.Raycast(ray, out RaycastHit hit, meshRaycastDistance))
            {
                float dist = Vector3.Distance(Camera.main.transform.position, hit.point);
                if (dist < 1f || dist > meshRaycastDistance) continue;

                // Only accept roughly horizontal surfaces (ground/floor)
                float upDot = Vector3.Dot(hit.normal, Vector3.up);
                if (upDot < 0.7f)
                {
                    Debug.Log($"[Spawner] Skipping non-ground surface (normal dot: {upDot:F2})");
                    continue;
                }

                Debug.Log($"[Spawner] Ground hit: {hit.collider.name} at {hit.point} (dist: {dist:F1}m, normal dot: {upDot:F2})");
                position = hit.point;
                return true;
            }
        }

        return false;
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

    private void SpawnPokemon(Vector3 position)
    {
        if (defaultPool == null || defaultPool.Length == 0)
        {
            Debug.LogWarning("[Spawner] No Pokemon configured in any pool!");
            return;
        }

        currentPokemonData = PickPokemonByTerrain(position);

        if (currentPokemonData.modelPrefab == null)
        {
            Debug.LogError($"[Spawner] {currentPokemonData.pokemonName} has no model prefab assigned!");
            return;
        }

        if (currentPokemonData.spawnBehavior == SpawnBehavior.Flying)
        {
            position.y += 1.5f;
        }

        currentWildPokemon = Instantiate(
            currentPokemonData.modelPrefab,
            position,
            currentPokemonData.modelPrefab.transform.rotation
        );
        currentWildPokemon.transform.localScale = Vector3.one * currentPokemonData.spawnScale;
        currentWildPokemon.transform.rotation = currentWildPokemon.transform.rotation * Quaternion.Euler(0f, Random.Range(0f, 360f), 0f);

        currentAnimator = currentWildPokemon.GetComponent<Animator>();
        if (currentAnimator != null)
        {
            currentAnimator.SetBool("isWalking", currentPokemonData.spawnBehavior == SpawnBehavior.Ground);
            currentAnimator.SetBool("isFlying", currentPokemonData.spawnBehavior == SpawnBehavior.Flying);
        }

        lastSpawnTime = Time.time;
        GameStateManager.Instance.TransitionTo(GamePhase.Encounter);

        Debug.Log($"[Spawner] Wild {currentPokemonData.pokemonName} appeared at {position}!");
    }

    private void HandlePhaseChanged(GamePhase oldPhase, GamePhase newPhase)
    {
        if (newPhase == GamePhase.Idle && currentWildPokemon != null)
        {
            Destroy(currentWildPokemon);
            currentWildPokemon = null;
            currentPokemonData = null;
        }
    }

    public void DespawnWild()
    {
        if (currentWildPokemon != null)
        {
            Destroy(currentWildPokemon);
            currentWildPokemon = null;
        }
    }
}
