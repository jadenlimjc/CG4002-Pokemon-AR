using System.Collections;
using UnityEngine;

public class BattleManager : MonoBehaviour
{
    public static BattleManager Instance { get; private set; }

    [Header("Player Pokemon")]
    [SerializeField] private GameObject playerPokemonInstance;

    [Header("Battle State")]
    [SerializeField] private int playerHP;
    [SerializeField] private int wildHP;
    [SerializeField] private bool isPlayerTurn = true;
    [SerializeField] private bool isProcessingMove = false;

    [Header("Spawn Offset")]
    [SerializeField] private float playerPokemonDistance = 1.5f;
    [SerializeField] private float playerPokemonSide = 0.5f;

    private PokemonData playerPokemon;

    public int PlayerHP => playerHP;
    public int WildHP => wildHP;
    public int PlayerMaxHP => playerPokemon != null ? playerPokemon.maxHP : 100;
    public int WildMaxHP => engagedWild?.Data?.maxHP ?? wildPokemonData?.maxHP ?? 100;
    public bool IsPlayerTurn => isPlayerTurn;
    public PokemonData PlayerPokemon => playerPokemon;
    public PokemonData WildPokemonData => wildPokemonData;

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

    [Header("Battle Pacing")]
    [Tooltip("Seconds per character when displaying battle messages")]
    [SerializeField] private float messageReadSpeed = 0.04f;
    [Tooltip("Minimum time a message stays on screen")]
    [SerializeField] private float minMessageTime = 1.0f;
    [Tooltip("Extra pause between player turn and wild turn")]
    [SerializeField] private float turnTransitionDelay = 1.0f;

    [Header("Potion")]
    [SerializeField] private int potionHealAmount = 20;

    private Animator playerAnimator;
    private Animator wildAnimator;
    private PokemonData wildPokemonData;
    private WildPokemonInstance engagedWild;
    private bool isBattleCatching = false;
    private bool isBattleAiming = false;
    private bool isWaitingRunConfirm = false;
    private bool isWaitingForcedSwitch = false;
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

        if (PartyMenuUI.Instance != null)
            PartyMenuUI.Instance.OnPokemonSelected += HandlePartySelection;
    }

    private void Start()
    {
        if (GameStateManager.Instance != null)
        {
            GameStateManager.Instance.OnPhaseChanged -= HandlePhaseChanged;
            GameStateManager.Instance.OnPhaseChanged += HandlePhaseChanged;
        }

        if (PartyMenuUI.Instance != null)
        {
            PartyMenuUI.Instance.OnPokemonSelected -= HandlePartySelection;
            PartyMenuUI.Instance.OnPokemonSelected += HandlePartySelection;
        }
    }

    private void OnDisable()
    {
        if (GameStateManager.Instance != null)
            GameStateManager.Instance.OnPhaseChanged -= HandlePhaseChanged;
        GestureEvents.OnGestureReceived -= HandleGesture;

        if (PartyMenuUI.Instance != null)
            PartyMenuUI.Instance.OnPokemonSelected -= HandlePartySelection;
    }

    private void HandlePhaseChanged(GamePhase oldPhase, GamePhase newPhase)
    {
        if (newPhase == GamePhase.BattleEntry)
        {
            StartBattle();
        }
        else if (newPhase == GamePhase.BattleResult)
        {
            if (wildHP <= 0 && engagedWild != null)
            {
                PokemonSpawner spawner = FindFirstObjectByType<PokemonSpawner>();
                spawner?.RemoveWildPokemon(engagedWild);
            }
            SaveHPToParty();
            StartCoroutine(DelayedTransition(GamePhase.Idle, 3f));
        }
        else if (newPhase == GamePhase.Idle)
        {
            CleanupBattle();
            engagedWild = null;
        }
    }

    private void HandleGesture(GestureAction action, float confidence)
    {
        if (GameStateManager.Instance.CurrentPhase != GamePhase.BattleActive) return;
        if (isProcessingMove) return;
        if (!isPlayerTurn) return;

        if (PartyMenuUI.Instance != null && PartyMenuUI.Instance.IsOpen) return;

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
                if (playerPokemon != null && moveIndex < playerPokemon.moves.Length)
                    StartCoroutine(ExecutePlayerMove(moveIndex));
                break;

            case GestureAction.BATTLE_RUN:
                isWaitingRunConfirm = true;
                OnBattleMessage?.Invoke("Flee? Press Run again to confirm, Cancel to stay.");
                break;

            case GestureAction.PARTY_POKEMON:
                OpenPartyMenu();
                break;

            case GestureAction.BATTLE_ITEM:
                StartCoroutine(UsePotion());
                break;

            case GestureAction.BATTLE_CATCH:
                isBattleCatching = true;
                OnBattleMessage?.Invoke("Catch mode! Aim then throw!");
                break;
        }
    }

    private void OpenPartyMenu()
    {
        if (PlayerParty.Instance == null || PlayerParty.Instance.Count <= 1) return;
        if (PartyMenuUI.Instance == null) return;

        isProcessingMove = true;
        PartyMenuUI.Instance.OnMenuClosed += HandlePartyMenuClosed;
        PartyMenuUI.Instance.Show(battleContext: true);
    }

    public void ForceOpenPartyMenu()
    {
        if (PlayerParty.Instance == null || !PlayerParty.Instance.HasUsablePokemon()) return;
        if (PartyMenuUI.Instance == null) return;

        isWaitingForcedSwitch = true;
        isProcessingMove = true;
        OnBattleMessage?.Invoke("Choose a Pokemon!");
        PartyMenuUI.Instance.Show(battleContext: true, forcedSwitch: true);
    }

    private void HandlePartyMenuClosed()
    {
        if (PartyMenuUI.Instance != null)
            PartyMenuUI.Instance.OnMenuClosed -= HandlePartyMenuClosed;

        if (!isWaitingForcedSwitch)
            isProcessingMove = false;
    }

    private void HandlePartySelection(int partyIndex, bool isBattle)
    {
        if (!isBattle) return;
        StartCoroutine(ExecuteSwitch(partyIndex));
    }

    private IEnumerator ExecuteSwitch(int partyIndex)
    {
        isWaitingForcedSwitch = false;
        PlayerParty party = PlayerParty.Instance;
        if (party == null) { isProcessingMove = false; yield break; }

        string oldName = playerPokemon.pokemonName;
        SaveHPToParty();

        yield return StartCoroutine(ShowMessage($"{oldName}, come back!"));

        if (playerPokemonInstance != null)
        {
            Destroy(playerPokemonInstance);
            playerPokemonInstance = null;
        }

        party.SetLead(partyIndex);
        playerPokemon = party.LeadPokemon.Data;
        playerHP = party.LeadPokemon.CurrentHP;

        Transform cam = Camera.main.transform;
        Vector3 spawnPos = cam.position
            + cam.forward * playerPokemonDistance
            + cam.right * playerPokemonSide;
        spawnPos.y -= 0.5f;

        SpawnPlayerPokemon(spawnPos);

        yield return StartCoroutine(ShowMessage($"Go, {playerPokemon.pokemonName}!"));

        OnHPChanged?.Invoke(playerHP, wildHP);

        yield return new WaitForSeconds(turnTransitionDelay);

        yield return StartCoroutine(ExecuteWildMove());

        isProcessingMove = false;
    }

    private IEnumerator UsePotion()
    {
        if (playerPokemon == null) yield break;

        if (playerHP >= playerPokemon.maxHP)
        {
            OnBattleMessage?.Invoke($"{playerPokemon.pokemonName}'s HP is full!");
            yield break;
        }

        isProcessingMove = true;

        int actualHeal = Mathf.Min(potionHealAmount, playerPokemon.maxHP - playerHP);
        playerHP += actualHeal;
        SaveHPToParty();

        yield return StartCoroutine(ShowMessage($"Player used a Potion! It restored {actualHeal} HP!"));

        OnHPChanged?.Invoke(playerHP, wildHP);

        yield return new WaitForSeconds(turnTransitionDelay);

        yield return StartCoroutine(ExecuteWildMove());

        isProcessingMove = false;
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
        engagedWild = spawner.EngagedPokemon;
        wildPokemonData = engagedWild.Data;

        if (PlayerParty.Instance != null && PlayerParty.Instance.LeadPokemon != null)
        {
            playerPokemon = PlayerParty.Instance.LeadPokemon.Data;
            playerHP = PlayerParty.Instance.LeadPokemon.CurrentHP;
        }
        else
        {
            playerHP = 100;
        }

        wildHP = wildPokemonData.maxHP;

        OnHPChanged?.Invoke(playerHP, wildHP);

        StartCoroutine(BattleEntrySequence());
    }

    private IEnumerator BattleEntrySequence()
    {
        Transform cam = Camera.main.transform;
        Vector3 spawnPos = cam.position
            + cam.forward * playerPokemonDistance
            + cam.right * playerPokemonSide;
        spawnPos.y -= 0.5f;

        Vector3 throwStart = cam.position - cam.right * 0.3f - cam.up * 0.3f + cam.forward * 0.3f;

        GameObject pokeball;
        if (pokeballPrefab != null)
            pokeball = Instantiate(pokeballPrefab, throwStart, Quaternion.identity);
        else
        {
            pokeball = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            pokeball.transform.position = throwStart;
            pokeball.transform.localScale = Vector3.one * 0.1f;
        }

        float duration = 0.8f;
        float elapsed = 0f;
        while (elapsed < duration)
        {
            elapsed += Time.deltaTime;
            float t = elapsed / duration;
            Vector3 pos = Vector3.Lerp(throwStart, spawnPos, t);
            pos.y += throwArc * Mathf.Sin(t * Mathf.PI);
            pokeball.transform.position = pos;
            pokeball.transform.Rotate(Vector3.right * 720 * Time.deltaTime);
            yield return null;
        }

        pokeball.transform.rotation = Quaternion.identity;
        pokeball.transform.position = spawnPos;

        yield return new WaitForSeconds(0.3f);

        Destroy(pokeball);

        SpawnPlayerPokemon(spawnPos);

        if (engagedWild?.GameObject != null)
        {
            wildAnimator = engagedWild.Animator;

            if (playerPokemonInstance != null)
            {
                Vector3 lookDir = playerPokemonInstance.transform.position - engagedWild.GameObject.transform.position;
                lookDir.y = 0;
                if (lookDir != Vector3.zero)
                {
                    Vector3 prefabAngles = engagedWild.Data.modelPrefab.transform.rotation.eulerAngles;
                    float targetY = Quaternion.LookRotation(lookDir).eulerAngles.y;
                    engagedWild.GameObject.transform.rotation = Quaternion.Euler(prefabAngles.x, targetY, prefabAngles.z);
                }
            }
        }

        isPlayerTurn = true;
        isProcessingMove = false;

        OnBattleMessage?.Invoke($"Go, {playerPokemon.pokemonName}!");

        yield return new WaitForSeconds(2f);

        GameStateManager.Instance.TransitionTo(GamePhase.BattleActive);
    }

    private void SpawnPlayerPokemon(Vector3 spawnPos)
    {
        if (playerPokemon == null || playerPokemon.modelPrefab == null) return;

        playerPokemonInstance = Instantiate(
            playerPokemon.modelPrefab,
            spawnPos,
            Quaternion.identity
        );
        playerPokemonInstance.transform.localScale = Vector3.one * playerPokemon.spawnScale;

        if (engagedWild?.GameObject != null)
        {
            Vector3 lookDir = engagedWild.GameObject.transform.position - spawnPos;
            lookDir.y = 0;
            if (lookDir != Vector3.zero)
                playerPokemonInstance.transform.rotation = Quaternion.LookRotation(lookDir);
        }

        playerAnimator = playerPokemonInstance.GetComponent<Animator>();
    }

    private float ReadingTime(string message)
    {
        return Mathf.Max(minMessageTime, message.Length * messageReadSpeed);
    }

    private IEnumerator ShowMessage(string message)
    {
        OnBattleMessage?.Invoke(message);
        yield return new WaitForSeconds(ReadingTime(message));
    }

    private IEnumerator WaitForAnimation(Animator animator, float minWait = 0.2f)
    {
        if (animator == null) { yield return new WaitForSeconds(minWait); yield break; }

        yield return new WaitForSeconds(minWait);

        yield return null;

        AnimatorStateInfo state = animator.GetCurrentAnimatorStateInfo(0);
        while (state.normalizedTime < 1f)
        {
            yield return null;
            state = animator.GetCurrentAnimatorStateInfo(0);
        }
    }

    private IEnumerator ExecutePlayerMove(int moveIndex)
    {
        isProcessingMove = true;
        MoveData move = playerPokemon.moves[moveIndex];

        yield return StartCoroutine(ShowMessage($"{playerPokemon.pokemonName} used {move.moveName}!"));

        if (playerAnimator != null && !string.IsNullOrEmpty(move.animationTrigger))
            playerAnimator.SetTrigger(move.animationTrigger);

        yield return StartCoroutine(WaitForAnimation(playerAnimator));

        if (move.isProtect)
        {
            yield return StartCoroutine(ExecuteWildMove(blocked: true));
            isProcessingMove = false;
            yield break;
        }

        bool hits = Random.Range(0, 100) < move.accuracy;
        if (hits)
        {
            int damage = CalculateDamage(move.power, playerPokemon.attack, wildPokemonData.defense);
            wildHP = Mathf.Max(0, wildHP - damage);
            OnHPChanged?.Invoke(playerHP, wildHP);

            if (wildAnimator != null)
                wildAnimator.SetTrigger("isHit");

            yield return StartCoroutine(ShowMessage($"It dealt {damage} damage!"));

            yield return StartCoroutine(WaitForAnimation(wildAnimator));
        }
        else
        {
            yield return StartCoroutine(ShowMessage("The attack missed!"));
        }

        if (wildHP <= 0)
        {
            yield return StartCoroutine(ShowMessage($"Wild {wildPokemonData.pokemonName} fainted!"));
            if (wildAnimator != null)
                wildAnimator.SetTrigger("isFainted");
            yield return StartCoroutine(WaitForAnimation(wildAnimator));
            GameStateManager.Instance.TransitionTo(GamePhase.BattleResult);
            isProcessingMove = false;
            yield break;
        }

        yield return new WaitForSeconds(turnTransitionDelay);

        yield return StartCoroutine(ExecuteWildMove());

        isProcessingMove = false;
    }

    private IEnumerator ExecuteWildMove(bool blocked = false)
    {
        isPlayerTurn = false;

        yield return StartCoroutine(ShowMessage($"Wild {wildPokemonData.pokemonName} attacked!"));

        if (wildAnimator != null)
            wildAnimator.SetTrigger("isAttacking");

        yield return StartCoroutine(WaitForAnimation(wildAnimator));

        if (blocked)
        {
            yield return StartCoroutine(ShowMessage($"{playerPokemon.pokemonName} protected itself!"));
            isPlayerTurn = true;
            OnBattleMessage?.Invoke("Your turn! Perform a move gesture!");
            yield break;
        }

        int wildDamage = CalculateDamage(50, wildPokemonData.attack, playerPokemon.defense);
        playerHP = Mathf.Max(0, playerHP - wildDamage);
        if (DemoModeManager.Instance != null && DemoModeManager.Instance.IsGodMode)
            playerHP = Mathf.Max(1, playerHP);
        OnHPChanged?.Invoke(playerHP, wildHP);
        SaveHPToParty();

        Handheld.Vibrate();

        yield return StartCoroutine(ShowMessage($"Dealt {wildDamage} damage!"));

        if (playerHP <= 0)
        {
            yield return StartCoroutine(ShowMessage($"{playerPokemon.pokemonName} fainted!"));
            if (playerAnimator != null)
                playerAnimator.SetTrigger("isFainted");
            yield return StartCoroutine(WaitForAnimation(playerAnimator));

            if (PlayerParty.Instance != null && PlayerParty.Instance.HasUsablePokemon())
            {
                ForceOpenPartyMenu();
                yield break;
            }

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
        PokemonSpawner spawner = FindFirstObjectByType<PokemonSpawner>();
        spawner?.DisengagePokemon();
        GameStateManager.Instance.TransitionTo(GamePhase.Idle);
        isProcessingMove = false;
    }

    private IEnumerator ExecuteBattleCatch()
    {
        isProcessingMove = true;

        if (engagedWild == null || engagedWild.GameObject == null)
        {
            isProcessingMove = false;
            yield break;
        }

        Vector3 startPos = Camera.main.transform.position + Camera.main.transform.forward * 0.5f;
        Vector3 targetPos = engagedWild.GameObject.transform.position;

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

        activePokeball.transform.rotation = Quaternion.identity;
        engagedWild.GameObject.SetActive(false);
        activePokeball.transform.position = targetPos;

        float hpRatio = (float)wildHP / wildPokemonData.maxHP;
        float catchRate = (DemoModeManager.Instance != null && DemoModeManager.Instance.IsGodMode)
            ? 1f
            : Mathf.Clamp01(wildPokemonData.baseCatchRate + (1f - hpRatio) * 0.3f);
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
            bool added = PlayerParty.Instance != null && PlayerParty.Instance.AddPokemon(wildPokemonData);
            string catchMsg = added
                ? $"Gotcha! {wildPokemonData.pokemonName} was caught and added to your party!"
                : $"Gotcha! {wildPokemonData.pokemonName} was caught! But your party is full...";
            OnBattleMessage?.Invoke(catchMsg);
            Destroy(activePokeball);
            PokemonSpawner spawner = FindFirstObjectByType<PokemonSpawner>();
            spawner?.RemoveWildPokemon(engagedWild);
            yield return new WaitForSeconds(2f);
            GameStateManager.Instance.TransitionTo(GamePhase.BattleResult);
            yield return new WaitForSeconds(1f);
            GameStateManager.Instance.TransitionTo(GamePhase.Idle);
        }
        else
        {
            OnBattleMessage?.Invoke($"{wildPokemonData.pokemonName} broke free!");
            Destroy(activePokeball);
            engagedWild.GameObject.SetActive(true);

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
        float damage = ((2f * 50f / 5f + 2f) * power * ((float)attack / defense)) / 50f + 2f;
        damage *= Random.Range(0.85f, 1f);
        return Mathf.Max(1, Mathf.RoundToInt(damage));
    }

    private void SaveHPToParty()
    {
        if (PlayerParty.Instance != null)
            PlayerParty.Instance.SaveHP(playerHP);
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
        isWaitingForcedSwitch = false;
    }

    private IEnumerator DelayedTransition(GamePhase phase, float delay)
    {
        yield return new WaitForSeconds(delay);
        GameStateManager.Instance.TransitionTo(phase);
    }
}
