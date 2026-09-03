using System.Collections;
using UnityEngine;
using TMPro;

public class EncounterNotification : MonoBehaviour
{
    [Header("UI References")]
    [SerializeField] private GameObject notificationPanel;
    [SerializeField] private TextMeshProUGUI pokemonNameText;
    [SerializeField] private GameObject exclamationIcon; // "!" or startled symbol

    [Header("Animation")]
    [SerializeField] private float fadeInDuration = 0.3f;
    [SerializeField] private float displayDuration = 3f;
    [SerializeField] private float fadeOutDuration = 0.5f;

    private CanvasGroup canvasGroup;

    private void Awake()
    {
        canvasGroup = notificationPanel?.GetComponent<CanvasGroup>();
        if (canvasGroup == null && notificationPanel != null)
            canvasGroup = notificationPanel.AddComponent<CanvasGroup>();

        HideImmediate();
    }

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

    private void HandlePhaseChanged(GamePhase oldPhase, GamePhase newPhase)
    {
        if (newPhase == GamePhase.Encounter)
        {
            PokemonSpawner spawner = FindFirstObjectByType<PokemonSpawner>();
            string name = spawner?.CurrentPokemonData?.pokemonName ?? "???";
            ShowNotification(name);
        }
        else if (oldPhase == GamePhase.Encounter)
        {
            HideImmediate();
        }
    }

    private void ShowNotification(string pokemonName)
    {
        if (pokemonNameText != null)
            pokemonNameText.text = $"Wild {pokemonName} appeared!";

        StartCoroutine(AnimateNotification());
    }

    private IEnumerator AnimateNotification()
    {
        notificationPanel?.SetActive(true);
        if (exclamationIcon != null) exclamationIcon.SetActive(true);

        // Fade in
        float elapsed = 0f;
        while (elapsed < fadeInDuration)
        {
            elapsed += Time.deltaTime;
            if (canvasGroup != null)
                canvasGroup.alpha = elapsed / fadeInDuration;
            yield return null;
        }

        if (canvasGroup != null) canvasGroup.alpha = 1f;

        // Hold
        yield return new WaitForSeconds(displayDuration);

        // Fade out (but keep the encounter UI visible)
        elapsed = 0f;
        while (elapsed < fadeOutDuration)
        {
            elapsed += Time.deltaTime;
            if (canvasGroup != null)
                canvasGroup.alpha = 1f - (elapsed / fadeOutDuration);
            yield return null;
        }

        HideImmediate();
    }

    private void HideImmediate()
    {
        if (canvasGroup != null) canvasGroup.alpha = 0f;
        notificationPanel?.SetActive(false);
    }
}
