using UnityEngine;
using UnityEngine.UI;
using TMPro;
using System.Collections;

public class BattleHUD : MonoBehaviour
{
    [Header("HUD Root")]
    [SerializeField] private GameObject battleHUDPanel;
    [SerializeField] private GameObject encounterPanel;

    [Header("Player HP")]
    [SerializeField] private Slider playerHPBar;
    [SerializeField] private TextMeshProUGUI playerHPText;
    [SerializeField] private TextMeshProUGUI playerNameText;

    [Header("Wild Pokemon HP")]
    [SerializeField] private Slider wildHPBar;
    [SerializeField] private TextMeshProUGUI wildHPText;
    [SerializeField] private TextMeshProUGUI wildNameText;

    [Header("Move Indicators")]
    [SerializeField] private GameObject movePanel;
    [SerializeField] private TextMeshProUGUI move1Text;
    [SerializeField] private TextMeshProUGUI move2Text;
    [SerializeField] private TextMeshProUGUI move3Text;
    [SerializeField] private TextMeshProUGUI move4Text;

    [Header("Battle Messages")]
    [SerializeField] private TextMeshProUGUI messageText;
    [SerializeField] private float messageDisplayTime = 2f;

    [Header("Encounter UI")]
    [SerializeField] private TextMeshProUGUI encounterText;
    [SerializeField] private GameObject actionPrompt; // "Overhead throw = Catch | Underhand throw = Battle"

    [Header("Reticle")]
    [SerializeField] private GameObject reticleObject; // Crosshair image centered on screen

    private void OnEnable()
    {
        GameStateManager.Instance.OnPhaseChanged += HandlePhaseChanged;

        if (BattleManager.Instance != null)
        {
            BattleManager.Instance.OnHPChanged += UpdateHP;
            BattleManager.Instance.OnBattleMessage += ShowMessage;
        }

        if (CatchManager.Instance != null)
        {
            CatchManager.Instance.OnCatchResult += HandleCatchResult;
        }
    }

    private void OnDisable()
    {
        if (GameStateManager.Instance != null)
            GameStateManager.Instance.OnPhaseChanged -= HandlePhaseChanged;

        if (BattleManager.Instance != null)
        {
            BattleManager.Instance.OnHPChanged -= UpdateHP;
            BattleManager.Instance.OnBattleMessage -= ShowMessage;
        }

        if (CatchManager.Instance != null)
        {
            CatchManager.Instance.OnCatchResult -= HandleCatchResult;
        }
    }

    private void HandlePhaseChanged(GamePhase oldPhase, GamePhase newPhase)
    {
        // Show/hide panels based on phase
        battleHUDPanel?.SetActive(
            newPhase == GamePhase.BattleActive ||
            newPhase == GamePhase.BattleEntry
        );

        encounterPanel?.SetActive(newPhase == GamePhase.Encounter);

        switch (newPhase)
        {
            case GamePhase.Encounter:
                ShowEncounterUI();
                break;
            case GamePhase.BattleActive:
                ShowBattleUI();
                break;
            case GamePhase.BattleResult:
                ShowBattleResult();
                break;
            case GamePhase.CatchResult:
                // Handled by CatchManager event
                break;
            case GamePhase.Idle:
                HideAll();
                break;
        }
    }

    private void ShowEncounterUI()
    {
        PokemonSpawner spawner = FindFirstObjectByType<PokemonSpawner>();
        if (spawner != null && spawner.CurrentPokemonData != null)
        {
            string pokeName = spawner.CurrentPokemonData.pokemonName;
            if (encounterText != null)
                encounterText.text = $"Wild {pokeName} appeared!";
        }

        if (actionPrompt != null)
            actionPrompt.SetActive(true);
    }

    private void ShowBattleUI()
    {
        BattleManager battle = BattleManager.Instance;
        PokemonSpawner spawner = FindFirstObjectByType<PokemonSpawner>();

        if (battle == null) return;

        // Set names
        if (playerNameText != null)
            playerNameText.text = battle.PlayerPokemon?.pokemonName ?? "???";
        if (wildNameText != null && spawner?.CurrentPokemonData != null)
            wildNameText.text = spawner.CurrentPokemonData.pokemonName;

        // Set move labels
        if (battle.PlayerPokemon?.moves != null)
        {
            var moves = battle.PlayerPokemon.moves;
            if (move1Text != null && moves.Length > 0) move1Text.text = $"1: {moves[0].moveName}";
            if (move2Text != null && moves.Length > 1) move2Text.text = $"2: {moves[1].moveName}";
            if (move3Text != null && moves.Length > 2) move3Text.text = $"3: {moves[2].moveName}";
            if (move4Text != null && moves.Length > 3) move4Text.text = $"4: {moves[3].moveName}";
        }

        // Initialize HP bars
        UpdateHP(battle.PlayerHP, battle.WildHP);

        if (movePanel != null)
            movePanel.SetActive(true);
    }

    private void UpdateHP(int playerHP, int wildHP)
    {
        BattleManager battle = BattleManager.Instance;
        if (battle == null) return;

        if (playerHPBar != null)
            playerHPBar.value = (float)playerHP / battle.PlayerMaxHP;
        if (playerHPText != null)
            playerHPText.text = $"{playerHP}/{battle.PlayerMaxHP}";

        if (wildHPBar != null)
            wildHPBar.value = (float)wildHP / battle.WildMaxHP;
        if (wildHPText != null)
            wildHPText.text = $"{wildHP}/{battle.WildMaxHP}";
    }

    private void ShowMessage(string message)
    {
        if (messageText != null)
        {
            messageText.text = message;
            StopCoroutine(nameof(ClearMessageAfterDelay));
            StartCoroutine(ClearMessageAfterDelay());
        }
    }

    private IEnumerator ClearMessageAfterDelay()
    {
        yield return new WaitForSeconds(messageDisplayTime);
        if (messageText != null)
            messageText.text = "";
    }

    private void HandleCatchResult(bool success, string pokemonName)
    {
        if (messageText != null)
        {
            messageText.text = success
                ? $"Gotcha! {pokemonName} was caught!"
                : $"Oh no! {pokemonName} broke free!";
        }
    }

    private void ShowBattleResult()
    {
        BattleManager battle = BattleManager.Instance;
        if (battle == null) return;

        bool playerWon = battle.WildHP <= 0;
        ShowMessage(playerWon ? "You won the battle!" : "You lost the battle...");
    }

    private void HideAll()
    {
        battleHUDPanel?.SetActive(false);
        encounterPanel?.SetActive(false);
        reticleObject?.SetActive(false);
        if (messageText != null) messageText.text = "";
    }
}
