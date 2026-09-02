using System.Collections;
using UnityEngine;

public class BattleManager : MonoBehaviour
{
    public static BattleManager Instance { get; private set; }

    [Header("Player Pokemon")]
    [SerializeField] private PokemonData playerPokemon;
    [SerializeField] private GameObject playerPokemonInstance;

    [Header("Battle State")]
    [SerializeField] private int playerHP;
    [SerializeField] private int wildHP;
    [SerializeField] private bool isPlayerTurn = true;
    [SerializeField] private bool isProcessingMove = false;

    [Header("Spawn Offset")]
    [SerializeField] private float playerPokemonDistance = 1.5f;
    [SerializeField] private float playerPokemonSide = 0.5f; // offset to the right

    public int PlayerHP => playerHP;
    public int WildHP => wildHP;
    public int PlayerMaxHP => playerPokemon != null ? playerPokemon.maxHP : 100;
    public int WildMaxHP => FindFirstObjectByType<PokemonSpawner>()?.CurrentPokemonData?.maxHP ?? 100;
    public bool IsPlayerTurn => isPlayerTurn;
    public PokemonData PlayerPokemon => playerPokemon;

    public delegate void BattleEventHandler(string message);
    public event BattleEventHandler OnBattleMessage;

    public delegate void HPChangedHandler(int playerHP, int wildHP);
    public event HPChangedHandler OnHPChanged;

    private Animator playerAnimator;
    private Animator wildAnimator;
    private PokemonData wildPokemonData;

    private void Awake()
    {
        if (Instance != null && Instance != this)
        {
            Destroy(gameObject);
            return;
        }
        Instance = this;
    }

    private void OnEnable()
    {
        GameStateManager.Instance.OnPhaseChanged += HandlePhaseChanged;
        GestureEvents.OnGestureReceived += HandleGesture;
    }

    private void OnDisable()
    {
        if (GameStateManager.Instance != null)
            GameStateManager.Instance.OnPhaseChanged -= HandlePhaseChanged;
        GestureEvents.OnGestureReceived -= HandleGesture;
    }

    private void HandlePhaseChanged(GamePhase oldPhase, GamePhase newPhase)
    {
        if (newPhase == GamePhase.BattleEntry)
        {
            StartBattle();
        }
        else if (newPhase == GamePhase.Idle)
        {
            CleanupBattle();
        }
    }

    private void HandleGesture(GestureAction action, float confidence)
    {
        if (GameStateManager.Instance.CurrentPhase != GamePhase.BattleActive) return;
        if (isProcessingMove) return;
        if (!isPlayerTurn) return;

        int moveIndex = action switch
        {
            GestureAction.BATTLE_MOVE_1 => 0,
            GestureAction.BATTLE_MOVE_2 => 1,
            GestureAction.BATTLE_MOVE_3 => 2,
            GestureAction.BATTLE_MOVE_4 => 3,
            _ => -1
        };

        if (moveIndex >= 0 && moveIndex < playerPokemon.moves.Length)
        {
            StartCoroutine(ExecutePlayerMove(moveIndex));
        }
    }

    private void StartBattle()
    {
        PokemonSpawner spawner = FindFirstObjectByType<PokemonSpawner>();
        wildPokemonData = spawner.CurrentPokemonData;

        // Initialize HP
        playerHP = playerPokemon.maxHP;
        wildHP = wildPokemonData.maxHP;

        // Spawn player's Pokemon
        SpawnPlayerPokemon();

        // Get wild Pokemon animator
        if (spawner.CurrentWildPokemon != null)
            wildAnimator = spawner.CurrentWildPokemon.GetComponent<Animator>();

        isPlayerTurn = true;
        isProcessingMove = false;

        OnHPChanged?.Invoke(playerHP, wildHP);
        OnBattleMessage?.Invoke($"Go, {playerPokemon.pokemonName}!");

        // Transition to active after a short delay
        StartCoroutine(DelayedTransition(GamePhase.BattleActive, 2f));
    }

    private void SpawnPlayerPokemon()
    {
        if (playerPokemon.modelPrefab == null) return;

        Transform cam = Camera.main.transform;
        Vector3 spawnPos = cam.position
            + cam.forward * playerPokemonDistance
            + cam.right * playerPokemonSide;
        spawnPos.y -= 0.5f; // slightly below eye level

        playerPokemonInstance = Instantiate(
            playerPokemon.modelPrefab,
            spawnPos,
            Quaternion.identity
        );
        playerPokemonInstance.transform.localScale = Vector3.one * playerPokemon.spawnScale;

        // Face the wild Pokemon
        PokemonSpawner spawner = FindFirstObjectByType<PokemonSpawner>();
        if (spawner.CurrentWildPokemon != null)
        {
            Vector3 lookDir = spawner.CurrentWildPokemon.transform.position - spawnPos;
            lookDir.y = 0;
            if (lookDir != Vector3.zero)
                playerPokemonInstance.transform.rotation = Quaternion.LookRotation(lookDir);
        }

        playerAnimator = playerPokemonInstance.GetComponent<Animator>();
    }

    private IEnumerator ExecutePlayerMove(int moveIndex)
    {
        isProcessingMove = true;
        MoveData move = playerPokemon.moves[moveIndex];

        OnBattleMessage?.Invoke($"{playerPokemon.pokemonName} used {move.moveName}!");

        // Play attack animation
        if (playerAnimator != null && !string.IsNullOrEmpty(move.animationTrigger))
            playerAnimator.SetTrigger(move.animationTrigger);

        yield return new WaitForSeconds(1f);

        // Check if Protect
        if (move.isProtect)
        {
            OnBattleMessage?.Invoke($"{playerPokemon.pokemonName} is protecting itself!");
            yield return new WaitForSeconds(1f);
            // Skip wild Pokemon's turn
            isProcessingMove = false;
            yield break;
        }

        // Calculate damage
        bool hits = Random.Range(0, 100) < move.accuracy;
        if (hits)
        {
            int damage = CalculateDamage(move.power, playerPokemon.attack, wildPokemonData.defense);
            wildHP = Mathf.Max(0, wildHP - damage);
            OnHPChanged?.Invoke(playerHP, wildHP);

            // Hit reaction on wild Pokemon
            if (wildAnimator != null)
                wildAnimator.SetTrigger("isHit");

            OnBattleMessage?.Invoke($"It dealt {damage} damage!");
        }
        else
        {
            OnBattleMessage?.Invoke("The attack missed!");
        }

        yield return new WaitForSeconds(1f);

        // Check if wild fainted
        if (wildHP <= 0)
        {
            OnBattleMessage?.Invoke($"Wild {wildPokemonData.pokemonName} fainted!");
            if (wildAnimator != null)
                wildAnimator.SetTrigger("isFainted");
            yield return new WaitForSeconds(2f);
            GameStateManager.Instance.TransitionTo(GamePhase.BattleResult);
            isProcessingMove = false;
            yield break;
        }

        // Wild Pokemon's turn
        yield return StartCoroutine(ExecuteWildMove());

        isProcessingMove = false;
    }

    private IEnumerator ExecuteWildMove()
    {
        isPlayerTurn = false;

        yield return new WaitForSeconds(0.5f);

        // Wild Pokemon uses a random basic attack
        int wildDamage = CalculateDamage(50, wildPokemonData.attack, playerPokemon.defense);
        playerHP = Mathf.Max(0, playerHP - wildDamage);
        OnHPChanged?.Invoke(playerHP, wildHP);

        if (wildAnimator != null)
            wildAnimator.SetTrigger("isAttacking");

        OnBattleMessage?.Invoke($"Wild {wildPokemonData.pokemonName} attacked! Dealt {wildDamage} damage!");

        // Vibrate device on hit (haptic feedback for FireBeetle)
        Handheld.Vibrate();

        yield return new WaitForSeconds(1f);

        // Check if player fainted
        if (playerHP <= 0)
        {
            OnBattleMessage?.Invoke($"{playerPokemon.pokemonName} fainted!");
            if (playerAnimator != null)
                playerAnimator.SetTrigger("isFainted");
            yield return new WaitForSeconds(2f);
            GameStateManager.Instance.TransitionTo(GamePhase.BattleResult);
            yield break;
        }

        isPlayerTurn = true;
        OnBattleMessage?.Invoke("Your turn! Perform a move gesture!");
    }

    private int CalculateDamage(int power, int attack, int defense)
    {
        // Simplified Pokemon damage formula
        float damage = ((2f * 50f / 5f + 2f) * power * ((float)attack / defense)) / 50f + 2f;
        // Add some randomness (85-100%)
        damage *= Random.Range(0.85f, 1f);
        return Mathf.Max(1, Mathf.RoundToInt(damage));
    }

    private void CleanupBattle()
    {
        if (playerPokemonInstance != null)
        {
            Destroy(playerPokemonInstance);
            playerPokemonInstance = null;
        }
    }

    private IEnumerator DelayedTransition(GamePhase phase, float delay)
    {
        yield return new WaitForSeconds(delay);
        GameStateManager.Instance.TransitionTo(phase);
    }
}
