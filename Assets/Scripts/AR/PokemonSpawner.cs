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
    [SerializeField] private float encounterRadius = 2f;
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

    public PokemonData CurrentPokemonData => currentPokemonData;
    public GameObject CurrentWildPokemon => currentWildPokemon;

    private void OnEnable()
    {
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
            SpawnPokemon(spawnPosition);
        }
        else
        {
            // Fallback: spawn in front of camera (editor testing without AR)
            Transform cam = Camera.main.transform;
            spawnPosition = cam.position + cam.forward * spawnDistance;
            spawnPosition.y = cam.position.y - 1f;
            SpawnPokemon(spawnPosition);
        }
    }

    private bool TryGetMeshSpawnPosition(out Vector3 position)
    {
        position = Vector3.zero;

        // Raycast from screen center onto Lightship-generated mesh
        Ray ray = Camera.main.ScreenPointToRay(
            new Vector3(Screen.width / 2f, Screen.height / 2f, 0));

        if (Physics.Raycast(ray, out RaycastHit hit, meshRaycastDistance))
        {
            Vector2 randomOffset = Random.insideUnitCircle * encounterRadius;
            position = hit.point + new Vector3(randomOffset.x, 0, randomOffset.y);
            return true;
        }

        return false;
    }

    private PokemonData PickPokemonByTerrain(Vector3 worldPosition)
    {
        if (!TryAcquireSubsystem() || !_segmentationSubsystem.running)
            return PickFromPool(defaultPool);

        // Try to sample the Grass channel at the spawn point
        if (TryCheckChannel(SceneSegmentationChannel.Grass, worldPosition) && grassPool.Length > 0)
            return PickFromPool(grassPool);

        if (TryCheckChannel(SceneSegmentationChannel.NaturalGround, worldPosition) && grassPool.Length > 0)
            return PickFromPool(grassPool);

        if (TryCheckChannel(SceneSegmentationChannel.Sky, worldPosition) && skyPool.Length > 0)
            return PickFromPool(skyPool);

        return PickFromPool(defaultPool);
    }

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

        // Convert world position to screen position
        Vector3 screenPos = Camera.main.WorldToScreenPoint(worldPosition);
        if (screenPos.z <= 0)
        {
            cpuImage.Dispose();
            return false;
        }

        // Map screen coords to image coords
        int x = Mathf.Clamp((int)(screenPos.x / Screen.width * cpuImage.width), 0, cpuImage.width - 1);
        int y = Mathf.Clamp((int)(screenPos.y / Screen.height * cpuImage.height), 0, cpuImage.height - 1);

        // Convert to NativeArray and sample
        var plane = cpuImage.GetPlane(0);
        int index = y * cpuImage.width + x;
        bool isPresent = index < plane.data.Length && plane.data[index] > 128;

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
            Quaternion.identity
        );
        currentWildPokemon.transform.localScale = Vector3.one * currentPokemonData.spawnScale;

        Vector3 lookDir = Camera.main.transform.position - position;
        lookDir.y = 0;
        if (lookDir != Vector3.zero)
            currentWildPokemon.transform.rotation = Quaternion.LookRotation(lookDir);

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
