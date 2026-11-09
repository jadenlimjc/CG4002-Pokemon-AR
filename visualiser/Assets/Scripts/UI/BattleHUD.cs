using UnityEngine;
using UnityEngine.UI;
using TMPro;
using System.Collections;

public class BattleHUD : MonoBehaviour
{
    [Header("HUD Root")]
    [SerializeField] private GameObject battleHUDPanel;

    [Header("Player HP")]
    [SerializeField] private RectTransform playerHPFillRect;
    [SerializeField] private TextMeshProUGUI playerHPText;
    [SerializeField] private TextMeshProUGUI playerNameText;

    [Header("Wild Pokemon HP")]
    [SerializeField] private RectTransform wildHPFillRect;
    [SerializeField] private TextMeshProUGUI wildHPText;
    [SerializeField] private TextMeshProUGUI wildNameText;

    [Header("Move Display Tiles (4)")]
    [SerializeField] private GameObject movePanel;
    [SerializeField] private GameObject[] moveTiles = new GameObject[4];
    [SerializeField] private TextMeshProUGUI[] moveTileTexts = new TextMeshProUGUI[4];

    [Header("Action Display Tiles")]
    [SerializeField] private GameObject actionPanel;
    [SerializeField] private GameObject catchTile;
    [SerializeField] private GameObject pokemonTile;
    [SerializeField] private GameObject itemTile;
    [SerializeField] private GameObject runTile;

    [Header("Prompt")]
    [SerializeField] private GameObject promptPanel;
    [SerializeField] private TextMeshProUGUI promptText;


    [Header("Reticle")]
    [SerializeField] private GameObject reticleObject;

    [Header("HP Bar Colors")]
    [SerializeField] private Image playerHPFillImage;
    [SerializeField] private Image wildHPFillImage;

    [Header("Feedback")]
    [SerializeField] private float flashDuration = 0.2f;

    private void OnEnable()
    {
        SubscribeEvents();
    }

    private void Start()
    {
        if (playerHPFillImage == null && playerHPFillRect != null)
            playerHPFillImage = playerHPFillRect.GetComponent<Image>();
        if (wildHPFillImage == null && wildHPFillRect != null)
            wildHPFillImage = wildHPFillRect.GetComponent<Image>();

        if (playerHPFillImage != null)
            playerHPFillImage.color = Color.green;
        if (wildHPFillImage != null)
            wildHPFillImage.color = Color.red;

        SubscribeEvents();
    }

    private void SubscribeEvents()
    {
        if (GameStateManager.Instance != null)
        {
            GameStateManager.Instance.OnPhaseChanged -= HandlePhaseChanged;
            GameStateManager.Instance.OnPhaseChanged += HandlePhaseChanged;
        }

        if (BattleManager.Instance != null)
        {
            BattleManager.Instance.OnHPChanged -= UpdateHP;
            BattleManager.Instance.OnHPChanged += UpdateHP;
            BattleManager.Instance.OnBattleMessage -= ShowMessage;
            BattleManager.Instance.OnBattleMessage += ShowMessage;
        }

        if (CatchManager.Instance != null)
        {
            CatchManager.Instance.OnCatchResult -= HandleCatchResult;
            CatchManager.Instance.OnCatchResult += HandleCatchResult;
        }

        GestureEvents.OnGestureReceived -= HandleGestureVisual;
        GestureEvents.OnGestureReceived += HandleGestureVisual;
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
            CatchManager.Instance.OnCatchResult -= HandleCatchResult;

        GestureEvents.OnGestureReceived -= HandleGestureVisual;
    }

    private void HandlePhaseChanged(GamePhase oldPhase, GamePhase newPhase)
    {
        battleHUDPanel?.SetActive(
            newPhase == GamePhase.BattleActive ||
            newPhase == GamePhase.BattleEntry
        );

        switch (newPhase)
        {
            case GamePhase.BattleActive:
                ShowBattleUI();
                break;
            case GamePhase.BattleResult:
                ShowBattleResult();
                break;
            case GamePhase.Idle:
                HideAll();
                break;
        }
    }

    private void ShowBattleUI()
    {
        BattleManager battle = BattleManager.Instance;

        if (battle == null) return;

        if (playerNameText != null)
            playerNameText.text = battle.PlayerPokemon?.pokemonName ?? "???";
        if (wildNameText != null && battle.WildPokemonData != null)
            wildNameText.text = battle.WildPokemonData.pokemonName;

        if (promptPanel != null) promptPanel.SetActive(true);
        if (promptText != null)
            promptText.text = $"What will {battle.PlayerPokemon?.pokemonName ?? "???"} do?";

        if (battle.PlayerPokemon?.moves != null)
        {
            var moves = battle.PlayerPokemon.moves;
            for (int i = 0; i < 4; i++)
            {
                if (i < moves.Length && moveTiles[i] != null)
                {
                    moveTiles[i].SetActive(true);
                    if (moveTileTexts[i] != null)
                        moveTileTexts[i].text = moves[i].moveName;
                }
                else if (moveTiles[i] != null)
                {
                    moveTiles[i].SetActive(false);
                }
            }
        }

        UpdateHP(battle.PlayerHP, battle.WildHP);

        if (movePanel != null) movePanel.SetActive(true);
        if (actionPanel != null) actionPanel.SetActive(true);
    }

    private void UpdateHP(int playerHP, int wildHP)
    {
        BattleManager battle = BattleManager.Instance;
        if (battle == null) return;

        if (playerNameText != null)
            playerNameText.text = battle.PlayerPokemon?.pokemonName ?? "???";

        float playerRatio = Mathf.Clamp01((float)playerHP / battle.PlayerMaxHP);
        float wildRatio = Mathf.Clamp01((float)wildHP / battle.WildMaxHP);

        if (playerHPFillRect != null)
            playerHPFillRect.localScale = new Vector3(playerRatio, 1f, 1f);
        if (playerHPText != null)
            playerHPText.text = $"{playerHP}/{battle.PlayerMaxHP}";

        if (wildHPFillRect != null)
            wildHPFillRect.localScale = new Vector3(wildRatio, 1f, 1f);
        if (wildHPText != null)
            wildHPText.text = $"{wildHP}/{battle.WildMaxHP}";

        RefreshMoveTiles(battle);
    }

    private void RefreshMoveTiles(BattleManager battle)
    {
        if (battle.PlayerPokemon?.moves == null) return;
        var moves = battle.PlayerPokemon.moves;
        for (int i = 0; i < 4; i++)
        {
            if (i < moves.Length && moveTiles[i] != null)
            {
                moveTiles[i].SetActive(true);
                if (moveTileTexts[i] != null)
                    moveTileTexts[i].text = moves[i].moveName;
            }
            else if (moveTiles[i] != null)
            {
                moveTiles[i].SetActive(false);
            }
        }
    }

    private void ShowMessage(string message)
    {
        if (promptText == null) return;

        if (message == "Your turn! Perform a move gesture!")
        {
            string name = BattleManager.Instance?.PlayerPokemon?.pokemonName ?? "???";
            promptText.text = $"What will {name} do?";
        }
        else
        {
            promptText.text = message;
        }
    }

    private void HandleCatchResult(bool success, string text)
    {
        if (success)
            ShowMessage($"Gotcha! {text}");
        else
            ShowMessage($"Oh no! {text} broke free!");
    }

    private void ShowBattleResult()
    {
        BattleManager battle = BattleManager.Instance;
        if (battle == null) return;

        bool playerWon = battle.PlayerHP > 0;
        ShowMessage(playerWon ? "You won the battle!" : "You lost the battle...");

        if (movePanel != null) movePanel.SetActive(false);
        if (actionPanel != null) actionPanel.SetActive(false);
    }

    private void HideAll()
    {
        battleHUDPanel?.SetActive(false);
        reticleObject?.SetActive(false);
        if (promptPanel != null) promptPanel.SetActive(false);
        if (movePanel != null) movePanel.SetActive(false);
        if (actionPanel != null) actionPanel.SetActive(false);
        if (promptText != null) promptText.text = "";
    }

    private void HandleGestureVisual(GestureAction action, float confidence)
    {
        if (GameStateManager.Instance == null ||
            GameStateManager.Instance.CurrentPhase != GamePhase.BattleActive)
            return;

        GameObject target = action switch
        {
            GestureAction.BATTLE_MOVE_1 => moveTiles.Length > 0 ? moveTiles[0] : null,
            GestureAction.BATTLE_MOVE_2 => moveTiles.Length > 1 ? moveTiles[1] : null,
            GestureAction.BATTLE_MOVE_3 => moveTiles.Length > 2 ? moveTiles[2] : null,
            GestureAction.BATTLE_MOVE_4 => moveTiles.Length > 3 ? moveTiles[3] : null,
            GestureAction.BATTLE_CATCH => catchTile,
            GestureAction.PARTY_POKEMON => pokemonTile,
            GestureAction.BATTLE_ITEM => itemTile,
            GestureAction.BATTLE_RUN => runTile,
            _ => null
        };

        if (target != null)
            StartCoroutine(FlashTile(target));
    }

    private IEnumerator FlashTile(GameObject tile)
    {
        RectTransform rt = tile.GetComponent<RectTransform>();
        if (rt == null) yield break;

        Vector3 originalScale = rt.localScale;
        Vector3 targetScale = originalScale * 1.3f;

        float half = flashDuration / 2f;
        float elapsed = 0f;

        while (elapsed < half)
        {
            elapsed += Time.deltaTime;
            rt.localScale = Vector3.Lerp(originalScale, targetScale, elapsed / half);
            yield return null;
        }

        elapsed = 0f;
        while (elapsed < half)
        {
            elapsed += Time.deltaTime;
            rt.localScale = Vector3.Lerp(targetScale, originalScale, elapsed / half);
            yield return null;
        }

        rt.localScale = originalScale;
    }
}
