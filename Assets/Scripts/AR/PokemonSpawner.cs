using System.Collections.Generic;
using UnityEngine;
using Niantic.Lightship.AR.Semantics;

public class PokemonSpawner : MonoBehaviour
{
    [Header("Lightship References")]
    [SerializeField] private ARSemanticSegmentationManager semanticManager;

    [Header("Spawn Settings")]
    [SerializeField] private float spawnDistance = 3f;
    [SerializeField] private float spawnCooldown = 10f;
    [SerializeField] private float encounterRadius = 2f;
    [SerializeField] private float meshRaycastDistance = 10f;

    [Header("Pokemon Pools")]
    [SerializeField] private PokemonData[] grassPool;
    [SerializeField] private PokemonData[] waterPool;
    [SerializeField] private PokemonData[] flyingPool;
    [SerializeField] private PokemonData[] defaultPool;

    [Header("Runtime")]
    [SerializeField] private GameObject currentWildPokemon;
    [SerializeField] private PokemonData currentPokemonData;

    private float lastSpawnTime;
    private Animator currentAnimator;

    public PokemonData CurrentPokemonData => currentPokemonData;
    public GameObject CurrentWildPokemon => currentWildPokemon;

    private void OnEnable()
    {
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
            // Apply random offset within encounter radius
            Vector2 randomOffset = Random.insideUnitCircle * encounterRadius;
            position = hit.point + new Vector3(randomOffset.x, 0, randomOffset.y);
            return true;
        }

        return false;
    }

    private PokemonData PickPokemonByTerrain(Vector3 worldPosition)
    {
        if (semanticManager == null)
            return PickFromPool(defaultPool);

        Vector3 screenPos = Camera.main.WorldToScreenPoint(worldPosition);
        Vector2Int pixelPos = new Vector2Int((int)screenPos.x, (int)screenPos.y);

        // Query Lightship semantic channels at the spawn point
        if (HasSemanticChannel(pixelPos, "water") && waterPool.Length > 0)
            return PickFromPool(waterPool);

        if ((HasSemanticChannel(pixelPos, "grass") ||
             HasSemanticChannel(pixelPos, "foliage") ||
             HasSemanticChannel(pixelPos, "tree")) && grassPool.Length > 0)
            return PickFromPool(grassPool);

        if (HasSemanticChannel(pixelPos, "sky") && flyingPool.Length > 0)
            return PickFromPool(flyingPool);

        return PickFromPool(defaultPool);
    }

    private bool HasSemanticChannel(Vector2Int pixel, string channelName)
    {
        if (semanticManager == null) return false;

        if (!semanticManager.TryGetChannel(channelName, out var channel)) return false;

        // Sample the semantic texture at the given pixel
        if (!channel.TryGetCpuTexture(out var texture)) return false;

        int x = Mathf.Clamp(pixel.x * texture.width / Screen.width, 0, texture.width - 1);
        int y = Mathf.Clamp(pixel.y * texture.height / Screen.height, 0, texture.height - 1);

        // Channel textures are single-channel: > 0 means the label is present
        return texture.GetPixel(x, y).r > 0.5f;
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

        // Pick Pokemon based on terrain semantic at spawn point
        currentPokemonData = PickPokemonByTerrain(position);

        if (currentPokemonData.modelPrefab == null)
        {
            Debug.LogError($"[Spawner] {currentPokemonData.pokemonName} has no model prefab assigned!");
            return;
        }

        // Adjust position for flying Pokemon
        if (currentPokemonData.spawnBehavior == SpawnBehavior.Flying)
        {
            position.y += 1.5f;
        }

        // Instantiate on mesh surface
        currentWildPokemon = Instantiate(
            currentPokemonData.modelPrefab,
            position,
            Quaternion.identity
        );
        currentWildPokemon.transform.localScale = Vector3.one * currentPokemonData.spawnScale;

        // Face the camera
        Vector3 lookDir = Camera.main.transform.position - position;
        lookDir.y = 0;
        if (lookDir != Vector3.zero)
            currentWildPokemon.transform.rotation = Quaternion.LookRotation(lookDir);

        // Setup animator
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
