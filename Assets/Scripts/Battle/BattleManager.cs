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

    [Header("Catch in Battle")]
    [SerializeField] private GameObject pokeballPrefab;
    [SerializeField] private GameObject reticleUI;
    [SerializeField] private float throwArc = 2f;
    [SerializeField] private int maxJiggles = 3;
    [SerializeField] private float jiggleInterval = 1f;

    private Animator playerAnimator;
    private Animator wildAnimator;
    private PokemonData wildPokemonData;
    private bool isBattleCatching = false;
    private bool isBattleAiming = false;
    private bool isWaitingRunConfirm = false;
    private GameObject activePokeball;

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
        if (GameStateManager.Instance != null)
            GameStateManager.Instance.OnPhaseChanged += HandlePhaseChanged;
        GestureEvents.OnGestureReceived += HandleGesture;
    }

    private void Start()
    {
        if (GameStateManager.Instance != null)
        {
            GameStateManager.Instance.OnPhaseChanged -= HandlePhaseChanged;
            GameStateManager.Instance.OnPhaseChanged += HandlePhaseChanged;
        }
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

        if (isWaitingRunConfirm)
        {
            if (action == GestureAction.BATTLE_RUN)
            {
                isWaitingRunConfirm = false;
                StartCoroutine(ExecuteRun());
            }
            else if (action == GestureAction.CANCEL)
            {
                isWaitingRunConfirm = false;
                OnBattleMessage?.Invoke("Stayed in battle!");
            }
            return;
        }

        if (isBattleCatching)
        {
            HandleBattleCatchGesture(action);
            return;
        }

        switch (action)
        {
            case GestureAction.BATTLE_MOVE_1:
            case GestureAction.BATTLE_MOVE_2:
            case GestureAction.BATTLE_MOVE_3:
            case GestureAction.BATTLE_MOVE_4:
                int moveIndex = action - GestureAction.BATTLE_MOVE_1;
                if (moveIndex < playerPokemon.moves.Length)
                    StartCoroutine(ExecutePlayerMove(moveIndex));
                break;

            case GestureAction.BATTLE_RUN:
                isWaitingRunConfirm = true;
                OnBattleMessage?.Invoke("Flee? Press Run again to confirm, Cancel to stay.");
                break;

            case GestureAction.BATTLE_SWITCH:
                OnBattleMessage?.Invoke("Switch Pokemon — Coming Soon!");
                break;

            case GestureAction.BATTLE_ITEM:
                OnBattleMessage?.Invoke("Use Item — Coming Soon!");
                break;

            case GestureAction.BATTLE_CATCH:
                isBattleCatching = true;
                OnBattleMessage?.Invoke("Catch mode! Aim then throw!");
                break;
        }
    }

    private void HandleBattleCatchGesture(GestureAction action)
    {
        switch (action)
        {
            case GestureAction.ARM_PULLBACK:
                isBattleAiming = true;
                if (reticleUI != null) reticleUI.SetActive(true);
                break;

            case GestureAction.CATCH_THROW when isBattleAiming:
                isBattleAiming = false;
                isBattleCatching = false;
                if (reticleUI != null) reticleUI.SetActive(false);
                StartCoroutine(ExecuteBattleCatch());
                break;

            case GestureAction.CANCEL:
                isBattleAiming = false;
                isBattleCatching = false;
                if (reticleUI != null) reticleUI.SetActive(false);
                OnBattleMessage?.Invoke("Catch cancelled.");
                break;
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

    private IEnumerator ExecuteRun()
    {
        isProcessingMove = true;
        OnBattleMessage?.Invoke("Got away safely!");
        yield return new WaitForSeconds(1.5f);

        CleanupBattle();
        GameStateManager.Instance.TransitionTo(GamePhase.Encounter);
        isProcessingMove = false;
    }

    private IEnumerator ExecuteBattleCatch()
    {
        isProcessingMove = true;
        PokemonSpawner spawner = FindFirstObjectByType<PokemonSpawner>();
        if (spawner == null || spawner.CurrentWildPokemon == null)
        {
            isProcessingMove = false;
            yield break;
        }

        Vector3 startPos = Camera.main.transform.position + Camera.main.transform.forward * 0.5f;
        Vector3 targetPos = spawner.CurrentWildPokemon.transform.position;

        if (pokeballPrefab != null)
            activePokeball = Instantiate(pokeballPrefab, startPos, Quaternion.identity);
        else
        {
            activePokeball = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            activePokeball.transform.position = startPos;
            activePokeball.transform.localScale = Vector3.one * 0.1f;
        }

        float duration = 0.8f;
        float elapsed = 0f;
        while (elapsed < duration)
        {
            elapsed += Time.deltaTime;
            float t = elapsed / duration;
            Vector3 pos = Vector3.Lerp(startPos, targetPos, t);
            pos.y += throwArc * Mathf.Sin(t * Mathf.PI);
            activePokeball.transform.position = pos;
            activePokeball.transform.Rotate(Vector3.right * 720 * Time.deltaTime);
            yield return null;
        }

        spawner.CurrentWildPokemon.SetActive(false);
        activePokeball.transform.position = targetPos;

        float catchRate = wildPokemonData.baseCatchRate;
        float hpRatio = (float)wildHP / wildPokemonData.maxHP;
        catchRate = Mathf.Clamp01(catchRate + (1f - hpRatio) * 0.3f);
        Debug.Log($"[BattleCatch] baseCatchRate={wildPokemonData.baseCatchRate}, hpRatio={hpRatio:F2}, finalCatchRate={catchRate:F2}");

        bool caught = true;
        for (int i = 0; i < maxJiggles; i++)
        {
            yield return new WaitForSeconds(jiggleInterval);
            yield return StartCoroutine(JigglePokeball());

            float roll = Random.value;
            Debug.Log($"[BattleCatch] Jiggle {i + 1}: roll={roll:F2}, catchRate={catchRate:F2}, pass={roll <= catchRate}");
            if (roll > catchRate)
            {
                caught = false;
                break;
            }
        }

        yield return new WaitForSeconds(0.5f);

        if (caught)
        {
            OnBattleMessage?.Invoke($"Gotcha! {wildPokemonData.pokemonName} was caught!");
            Destroy(activePokeball);
            yield return new WaitForSeconds(2f);
            GameStateManager.Instance.TransitionTo(GamePhase.BattleResult);
            yield return new WaitForSeconds(1f);
            GameStateManager.Instance.TransitionTo(GamePhase.Idle);
        }
        else
        {
            OnBattleMessage?.Invoke($"{wildPokemonData.pokemonName} broke free!");
            Destroy(activePokeball);
            spawner.CurrentWildPokemon.SetActive(true);

            if (wildAnimator != null)
                wildAnimator.SetTrigger("breakFree");

            yield return new WaitForSeconds(1f);
            yield return StartCoroutine(ExecuteWildMove());
        }

        isProcessingMove = false;
    }

    private IEnumerator JigglePokeball()
    {
        if (activePokeball == null) yield break;

        Quaternion originalRot = activePokeball.transform.rotation;
        float jiggleDuration = 0.4f;
        float elapsed = 0f;

        while (elapsed < jiggleDuration)
        {
            elapsed += Time.deltaTime;
            float angle = Mathf.Sin(elapsed * 30f) * 15f * (1f - elapsed / jiggleDuration);
            activePokeball.transform.rotation = originalRot * Quaternion.Euler(0, 0, angle);
            yield return null;
        }

        activePokeball.transform.rotation = originalRot;
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
        if (activePokeball != null)
        {
            Destroy(activePokeball);
            activePokeball = null;
        }
        isBattleCatching = false;
        isBattleAiming = false;
        isWaitingRunConfirm = false;
    }

    private IEnumerator DelayedTransition(GamePhase phase, float delay)
    {
        yield return new WaitForSeconds(delay);
        GameStateManager.Instance.TransitionTo(phase);
    }
}
