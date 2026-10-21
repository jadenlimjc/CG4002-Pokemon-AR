using UnityEngine;
using UnityEngine.UI;
using TMPro;
using System.Collections;

public class BattleHUD : MonoBehaviour
{
    [Header("HUD Root")]
    [SerializeField] private GameObject battleHUDPanel;

    [Header("Player HP")]
    [SerializeField] private Slider playerHPBar;
    [SerializeField] private TextMeshProUGUI playerHPText;
    [SerializeField] private TextMeshProUGUI playerNameText;

    [Header("Wild Pokemon HP")]
    [SerializeField] private Slider wildHPBar;
    [SerializeField] private TextMeshProUGUI wildHPText;
    [SerializeField] private TextMeshProUGUI wildNameText;

    [Header("Move Display Tiles (4)")]
    [SerializeField] private GameObject movePanel;
    [SerializeField] private GameObject[] moveTiles = new GameObject[4];
    [SerializeField] private TextMeshProUGUI[] moveTileTexts = new TextMeshProUGUI[4];
    [SerializeField] private Image[] moveTileImages = new Image[4];

    [Header("Action Display Tiles")]
    [SerializeField] private GameObject actionPanel;
    [SerializeField] private GameObject catchTile;
    [SerializeField] private GameObject pokemonTile;
    [SerializeField] private GameObject itemTile;
    [SerializeField] private GameObject runTile;

    [Header("Prompt")]
    [SerializeField] private TextMeshProUGUI promptText;

    [Header("Battle Messages")]
    [SerializeField] private TextMeshProUGUI messageText;
    [SerializeField] private float messageDisplayTime = 2f;

    [Header("Reticle")]
    [SerializeField] private GameObject reticleObject;

    [Header("Feedback")]
    [SerializeField] private float flashDuration = 0.2f;

    private void OnEnable()
    {
        SubscribeEvents();
    }

    private void Start()
    {
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
        PokemonSpawner spawner = FindFirstObjectByType<PokemonSpawner>();

        if (battle == null) return;

        if (playerNameText != null)
            playerNameText.text = battle.PlayerPokemon?.pokemonName ?? "???";
        if (wildNameText != null && spawner?.CurrentPokemonData != null)
            wildNameText.text = spawner.CurrentPokemonData.pokemonName;

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
                    if (moveTileImages[i] != null)
                        moveTileImages[i].color = GetTypeColor(moves[i].moveType);
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

        if (movePanel != null) movePanel.SetActive(false);
        if (actionPanel != null) actionPanel.SetActive(false);
    }

    private void HideAll()
    {
        battleHUDPanel?.SetActive(false);
        reticleObject?.SetActive(false);
        if (movePanel != null) movePanel.SetActive(false);
        if (actionPanel != null) actionPanel.SetActive(false);
        if (messageText != null) messageText.text = "";
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
            GestureAction.BATTLE_SWITCH => pokemonTile,
            GestureAction.BATTLE_ITEM => itemTile,
            GestureAction.BATTLE_RUN => runTile,
            _ => null
        };

        if (target != null)
            StartCoroutine(FlashTile(target));
    }

    private IEnumerator FlashTile(GameObject tile)
    {
        Image img = tile.GetComponent<Image>();
        if (img == null) yield break;

        Color original = img.color;
        img.color = Color.Lerp(original, Color.white, 0.6f);
        yield return new WaitForSeconds(flashDuration);
        img.color = original;
    }

    public static Color GetTypeColor(PokemonType type)
    {
        return type switch
        {
            PokemonType.Normal   => new Color(0.66f, 0.65f, 0.48f),
            PokemonType.Fire     => new Color(0.93f, 0.51f, 0.19f),
            PokemonType.Water    => new Color(0.39f, 0.56f, 0.94f),
            PokemonType.Grass    => new Color(0.47f, 0.78f, 0.30f),
            PokemonType.Electric => new Color(0.97f, 0.82f, 0.17f),
            PokemonType.Ice      => new Color(0.59f, 0.85f, 0.84f),
            PokemonType.Fighting => new Color(0.76f, 0.18f, 0.16f),
            PokemonType.Poison   => new Color(0.63f, 0.24f, 0.63f),
            PokemonType.Ground   => new Color(0.88f, 0.75f, 0.40f),
            PokemonType.Flying   => new Color(0.66f, 0.56f, 0.95f),
            PokemonType.Psychic  => new Color(0.98f, 0.33f, 0.53f),
            PokemonType.Bug      => new Color(0.65f, 0.73f, 0.10f),
            PokemonType.Rock     => new Color(0.71f, 0.63f, 0.21f),
            PokemonType.Ghost    => new Color(0.44f, 0.34f, 0.59f),
            PokemonType.Dragon   => new Color(0.44f, 0.21f, 0.99f),
            PokemonType.Dark     => new Color(0.44f, 0.34f, 0.27f),
            PokemonType.Steel    => new Color(0.72f, 0.72f, 0.81f),
            PokemonType.Fairy    => new Color(0.84f, 0.52f, 0.68f),
            _                    => new Color(0.50f, 0.50f, 0.50f),
        };
    }
}
