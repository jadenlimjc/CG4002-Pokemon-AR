using System.Collections;
using UnityEngine;
using UnityEngine.UI;

public class CatchManager : MonoBehaviour
{
    public static CatchManager Instance { get; private set; }

    [Header("Pokeball Settings")]
    [SerializeField] private GameObject pokeballPrefab;
    [SerializeField] private float throwArc = 2f;

    [Header("Reticle")]
    [SerializeField] private GameObject reticleUI;
    [SerializeField] private float reticleRadius = 150f;
    private CrosshairUI crosshairUI;

    [Header("Catch Animation")]
    [SerializeField] private int maxJiggles = 3;
    [SerializeField] private float jiggleInterval = 1f;

    [Header("VFX")]
    [SerializeField] private GameObject sparkleVFX;
    [SerializeField] private GameObject smokeVFX;
    [SerializeField] private GameObject fizzleVFX;

    private GameObject activePokeball;
    private bool isAiming = false;

    public delegate void CatchEventHandler(bool success, string pokemonName);
    public event CatchEventHandler OnCatchResult;

    public bool IsAiming => isAiming;

    private void Awake()
    {
        if (Instance != null && Instance != this)
        {
            Destroy(gameObject);
            return;
        }
        Instance = this;
        if (reticleUI != null)
            crosshairUI = reticleUI.GetComponent<CrosshairUI>();
    }

    private void Update()
    {
        if (isAiming && crosshairUI != null)
            crosshairUI.SetHighlight(FindPokemonInReticle() != null);
    }

    private void OnEnable()
    {
        GestureEvents.OnGestureReceived += HandleGesture;
    }

    private void OnDisable()
    {
        GestureEvents.OnGestureReceived -= HandleGesture;
    }

    private void HandleGesture(GestureAction action, float confidence)
    {
        var phase = GameStateManager.Instance.CurrentPhase;
        if (phase != GamePhase.Idle && phase != GamePhase.Encounter) return;

        if (PartyMenuUI.Instance != null && PartyMenuUI.Instance.IsOpen) return;

        if (action == GestureAction.PARTY_POKEMON)
        {
            OpenPartyMenuForLeadSelect();
            return;
        }

        switch (action)
        {
            case GestureAction.ARM_PULLBACK:
                isAiming = true;
                ShowReticle();
                break;

            case GestureAction.CATCH_THROW when isAiming:
                isAiming = false;
                HideReticle();
                WildPokemonInstance catchTarget = FindPokemonInReticle();
                if (catchTarget != null)
                {
                    PokemonSpawner spawner = FindFirstObjectByType<PokemonSpawner>();
                    spawner.EngagePokemon(catchTarget);
                    GameStateManager.Instance.TransitionTo(GamePhase.CatchAttempt);
                    StartCoroutine(ThrowPokeball(true));
                }
                else
                {
                    GameStateManager.Instance.TransitionTo(GamePhase.CatchAttempt);
                    StartCoroutine(ThrowPokeball(false));
                }
                break;

            case GestureAction.BATTLE_THROW when isAiming:
                isAiming = false;
                HideReticle();
                WildPokemonInstance battleTarget = FindPokemonInReticle();
                if (battleTarget != null)
                {
                    PokemonSpawner spawner = FindFirstObjectByType<PokemonSpawner>();
                    spawner.EngagePokemon(battleTarget);
                    GameStateManager.Instance.TransitionTo(GamePhase.BattleEntry);
                }
                break;

            case GestureAction.CANCEL when isAiming:
                isAiming = false;
                HideReticle();
                break;
        }
    }

    private void OpenPartyMenuForLeadSelect()
    {
        if (PlayerParty.Instance == null) return;
        if (PartyMenuUI.Instance == null) return;

        PartyMenuUI.Instance.OnPokemonSelected += HandleLeadSelect;
        PartyMenuUI.Instance.OnMenuClosed += HandleLeadSelectClosed;
        PartyMenuUI.Instance.Show(battleContext: false);
    }

    private void HandleLeadSelect(int partyIndex, bool isBattle)
    {
        if (isBattle) return;
        PlayerParty.Instance?.SetLead(partyIndex);
    }

    private void HandleLeadSelectClosed()
    {
        if (PartyMenuUI.Instance != null)
        {
            PartyMenuUI.Instance.OnPokemonSelected -= HandleLeadSelect;
            PartyMenuUI.Instance.OnMenuClosed -= HandleLeadSelectClosed;
        }
    }

    private void ShowReticle()
    {
        if (reticleUI != null)
            reticleUI.SetActive(true);
    }

    private void HideReticle()
    {
        if (reticleUI != null)
            reticleUI.SetActive(false);
    }

    private WildPokemonInstance FindPokemonInReticle()
    {
        PokemonSpawner spawner = FindFirstObjectByType<PokemonSpawner>();
        if (spawner == null) return null;

        Vector2 screenCenter = new Vector2(Screen.width / 2f, Screen.height / 2f);
        WildPokemonInstance bestMatch = null;
        float bestDist = float.MaxValue;

        foreach (var wild in spawner.AllWildPokemon)
        {
            if (wild.GameObject == null || !wild.GameObject.activeInHierarchy) continue;

            Renderer[] renderers = wild.GameObject.GetComponentsInChildren<Renderer>();
            if (renderers.Length == 0) continue;

            Bounds bounds = renderers[0].bounds;
            for (int r = 1; r < renderers.Length; r++)
                bounds.Encapsulate(renderers[r].bounds);

            Vector3[] corners = new Vector3[8];
            corners[0] = new Vector3(bounds.min.x, bounds.min.y, bounds.min.z);
            corners[1] = new Vector3(bounds.max.x, bounds.min.y, bounds.min.z);
            corners[2] = new Vector3(bounds.min.x, bounds.max.y, bounds.min.z);
            corners[3] = new Vector3(bounds.max.x, bounds.max.y, bounds.min.z);
            corners[4] = new Vector3(bounds.min.x, bounds.min.y, bounds.max.z);
            corners[5] = new Vector3(bounds.max.x, bounds.min.y, bounds.max.z);
            corners[6] = new Vector3(bounds.min.x, bounds.max.y, bounds.max.z);
            corners[7] = new Vector3(bounds.max.x, bounds.max.y, bounds.max.z);

            float minX = float.MaxValue, maxX = float.MinValue;
            float minY = float.MaxValue, maxY = float.MinValue;
            bool anyVisible = false;

            for (int i = 0; i < 8; i++)
            {
                Vector3 sp = Camera.main.WorldToScreenPoint(corners[i]);
                if (sp.z <= 0) continue;
                anyVisible = true;
                minX = Mathf.Min(minX, sp.x);
                maxX = Mathf.Max(maxX, sp.x);
                minY = Mathf.Min(minY, sp.y);
                maxY = Mathf.Max(maxY, sp.y);
            }
            if (!anyVisible) continue;

            float closestX = Mathf.Clamp(screenCenter.x, minX, maxX);
            float closestY = Mathf.Clamp(screenCenter.y, minY, maxY);
            float dist = Vector2.Distance(screenCenter, new Vector2(closestX, closestY));

            if (dist <= reticleRadius && dist < bestDist)
            {
                bestDist = dist;
                bestMatch = wild;
            }
        }

        Debug.Log($"[Catch] FindPokemonInReticle: {(bestMatch != null ? bestMatch.Data.pokemonName : "none")}, dist: {bestDist:F0}px");
        return bestMatch;
    }

    private IEnumerator ThrowPokeball(bool hit)
    {
        PokemonSpawner spawner = FindFirstObjectByType<PokemonSpawner>();
        WildPokemonInstance target = spawner?.EngagedPokemon;

        Debug.Log($"[Catch] ThrowPokeball called, hit={hit}");
        if (hit && (target == null || target.GameObject == null))
        {
            Debug.Log("[Catch] ThrowPokeball aborted — no engaged pokemon");
            yield break;
        }

        Vector3 startPos = Camera.main.transform.position + Camera.main.transform.forward * 0.5f;
        Vector3 targetPos;

        if (hit)
        {
            targetPos = target.GameObject.transform.position;
        }
        else
        {
            Ray ray = Camera.main.ScreenPointToRay(new Vector3(Screen.width / 2f, Screen.height / 2f, 0));
            targetPos = ray.GetPoint(5f);
        }

        if (pokeballPrefab != null)
        {
            activePokeball = Instantiate(pokeballPrefab, startPos, Quaternion.identity);
        }
        else
        {
            activePokeball = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            activePokeball.transform.position = startPos;
            activePokeball.transform.localScale = Vector3.one * 0.1f;
        }

        float duration = hit ? 0.8f : 1.2f;
        float elapsed = 0f;

        while (elapsed < duration)
        {
            elapsed += Time.deltaTime;
            float t = elapsed / duration;

            Vector3 pos = Vector3.Lerp(startPos, targetPos, t);
            float arc = throwArc * Mathf.Sin(t * Mathf.PI);
            pos.y += arc;

            activePokeball.transform.position = pos;
            activePokeball.transform.Rotate(Vector3.right * 720 * Time.deltaTime);

            yield return null;
        }

        activePokeball.transform.rotation = Quaternion.identity;

        if (hit)
        {
            yield return StartCoroutine(CatchSequence(spawner, target));
        }
        else
        {
            yield return StartCoroutine(MissSequence());
        }
    }

    private IEnumerator MissSequence()
    {
        if (fizzleVFX != null)
            Instantiate(fizzleVFX, activePokeball.transform.position, Quaternion.identity);

        Destroy(activePokeball);
        activePokeball = null;

        yield return new WaitForSeconds(0.5f);

        GameStateManager.Instance.TransitionTo(GamePhase.Idle);
    }

    private IEnumerator CatchSequence(PokemonSpawner spawner, WildPokemonInstance target)
    {
        Vector3 targetPos = target.GameObject.transform.position;

        target.GameObject.SetActive(false);

        if (smokeVFX != null)
            Instantiate(smokeVFX, targetPos, Quaternion.identity);

        activePokeball.transform.position = targetPos;

        float catchRate = (DemoModeManager.Instance != null && DemoModeManager.Instance.IsGodMode)
            ? 1f
            : target.Data.baseCatchRate;
        bool caught = false;

        for (int i = 0; i < maxJiggles; i++)
        {
            yield return new WaitForSeconds(jiggleInterval);
            yield return StartCoroutine(JigglePokeball());

            if (Random.value > catchRate)
            {
                caught = false;
                break;
            }

            if (i == maxJiggles - 1)
            {
                caught = true;
            }
        }

        yield return new WaitForSeconds(0.5f);

        if (caught)
        {
            if (sparkleVFX != null)
                Instantiate(sparkleVFX, activePokeball.transform.position, Quaternion.identity);

            bool added = PlayerParty.Instance != null && PlayerParty.Instance.AddPokemon(target.Data);
            string pokemonName = target.Data.pokemonName;
            string catchText = added
                ? $"{pokemonName} was caught and added to your party!"
                : $"{pokemonName} was caught! But your party is full...";
            OnCatchResult?.Invoke(true, catchText);

            yield return new WaitForSeconds(2f);
            Destroy(activePokeball);
            spawner.RemoveWildPokemon(target);
            GameStateManager.Instance.TransitionTo(GamePhase.CatchResult);

            yield return new WaitForSeconds(3f);
            GameStateManager.Instance.TransitionTo(GamePhase.Idle);
        }
        else
        {
            OnCatchResult?.Invoke(false, target.Data.pokemonName);

            Destroy(activePokeball);
            target.GameObject.SetActive(true);

            if (target.Animator != null)
                target.Animator.SetTrigger("breakFree");

            GameStateManager.Instance.TransitionTo(GamePhase.CatchResult);

            yield return new WaitForSeconds(2f);
            spawner.DisengagePokemon();
            GameStateManager.Instance.TransitionTo(GamePhase.Idle);
        }
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
}
