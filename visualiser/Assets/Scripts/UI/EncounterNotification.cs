using System.Collections;
using UnityEngine;
using TMPro;

public class EncounterNotification : MonoBehaviour
{
    [Header("UI References")]
    [SerializeField] private GameObject notificationPanel;
    [SerializeField] private TextMeshProUGUI pokemonNameText;
    [SerializeField] private TextMeshProUGUI terrainTypeText;
    [SerializeField] private GameObject exclamationIcon;

    [Header("Animation")]
    [SerializeField] private float fadeInDuration = 0.3f;
    [SerializeField] private float displayDuration = 3f;
    [SerializeField] private float fadeOutDuration = 0.5f;

    private CanvasGroup canvasGroup;
    private Coroutine activeAnimation;

    private void Awake()
    {
        canvasGroup = notificationPanel?.GetComponent<CanvasGroup>();
        if (canvasGroup == null && notificationPanel != null)
            canvasGroup = notificationPanel.AddComponent<CanvasGroup>();

        HideImmediate();
    }

    private void OnEnable()
    {
        PokemonSpawner spawner = FindFirstObjectByType<PokemonSpawner>();
        if (spawner != null)
            spawner.OnPokemonSpawned += HandlePokemonSpawned;
    }

    private void Start()
    {
        PokemonSpawner spawner = FindFirstObjectByType<PokemonSpawner>();
        if (spawner != null)
        {
            spawner.OnPokemonSpawned -= HandlePokemonSpawned;
            spawner.OnPokemonSpawned += HandlePokemonSpawned;
        }
    }

    private void OnDisable()
    {
        PokemonSpawner spawner = FindFirstObjectByType<PokemonSpawner>();
        if (spawner != null)
            spawner.OnPokemonSpawned -= HandlePokemonSpawned;
    }

    private void HandlePokemonSpawned(WildPokemonInstance instance)
    {
        string name = instance?.Data?.pokemonName ?? "???";
        string terrain = instance?.SpawnTerrain ?? "Unknown";
        ShowNotification(name, terrain);
    }

    private void ShowNotification(string pokemonName, string terrain)
    {
        if (pokemonNameText != null)
            pokemonNameText.text = $"Wild {pokemonName} appeared!";

        if (terrainTypeText != null)
            terrainTypeText.text = $"Terrain: {terrain}";

        if (activeAnimation != null)
            StopCoroutine(activeAnimation);
        activeAnimation = StartCoroutine(AnimateNotification());
    }

    private IEnumerator AnimateNotification()
    {
        notificationPanel?.SetActive(true);
        if (exclamationIcon != null) exclamationIcon.SetActive(true);

        float elapsed = 0f;
        while (elapsed < fadeInDuration)
        {
            elapsed += Time.deltaTime;
            if (canvasGroup != null)
                canvasGroup.alpha = elapsed / fadeInDuration;
            yield return null;
        }

        if (canvasGroup != null) canvasGroup.alpha = 1f;

        yield return new WaitForSeconds(displayDuration);

        elapsed = 0f;
        while (elapsed < fadeOutDuration)
        {
            elapsed += Time.deltaTime;
            if (canvasGroup != null)
                canvasGroup.alpha = 1f - (elapsed / fadeOutDuration);
            yield return null;
        }

        HideImmediate();
        activeAnimation = null;
    }

    private void HideImmediate()
    {
        if (canvasGroup != null) canvasGroup.alpha = 0f;
        notificationPanel?.SetActive(false);
    }
}
