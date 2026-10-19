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
        if (GameStateManager.Instance.CurrentPhase != GamePhase.Encounter) return;

        switch (action)
        {
            case GestureAction.ARM_PULLBACK:
                isAiming = true;
                ShowReticle();
                break;

            case GestureAction.CATCH_THROW when isAiming:
                isAiming = false;
                HideReticle();
                GameStateManager.Instance.TransitionTo(GamePhase.CatchAttempt);
                if (IsPokemonInReticle())
                    StartCoroutine(ThrowPokeball(true));
                else
                    StartCoroutine(ThrowPokeball(false));
                break;

            case GestureAction.POKEBALL_THROW when isAiming:
                isAiming = false;
                HideReticle();
                GameStateManager.Instance.TransitionTo(GamePhase.BattleEntry);
                break;

            case GestureAction.CANCEL when isAiming:
                isAiming = false;
                HideReticle();
                break;
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

    private bool IsPokemonInReticle()
    {
        PokemonSpawner spawner = FindFirstObjectByType<PokemonSpawner>();
        if (spawner == null || spawner.CurrentWildPokemon == null)
        {
            Debug.Log("[Catch] No spawner or wild pokemon found");
            return false;
        }

        Renderer renderer = spawner.CurrentWildPokemon.GetComponentInChildren<Renderer>();
        if (renderer == null)
        {
            Debug.Log("[Catch] No renderer on wild pokemon");
            return false;
        }

        // Project the Pokemon's bounding box corners to screen space
        Bounds bounds = renderer.bounds;
        Vector2 screenCenter = new Vector2(Screen.width / 2f, Screen.height / 2f);

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

        for (int i = 0; i < 8; i++)
        {
            Vector3 sp = Camera.main.WorldToScreenPoint(corners[i]);
            if (sp.z <= 0) continue;
            minX = Mathf.Min(minX, sp.x);
            maxX = Mathf.Max(maxX, sp.x);
            minY = Mathf.Min(minY, sp.y);
            maxY = Mathf.Max(maxY, sp.y);
        }

        // Check if reticle circle overlaps with Pokemon's screen rect
        float closestX = Mathf.Clamp(screenCenter.x, minX, maxX);
        float closestY = Mathf.Clamp(screenCenter.y, minY, maxY);
        float dist = Vector2.Distance(screenCenter, new Vector2(closestX, closestY));

        bool hit = dist <= reticleRadius;
        Debug.Log($"[Catch] Pokemon screen rect: ({minX:F0},{minY:F0})-({maxX:F0},{maxY:F0}), reticle dist to rect: {dist:F0}px, hit: {hit}");
        return hit;
    }

    private IEnumerator ThrowPokeball(bool hit)
    {
        Debug.Log($"[Catch] ThrowPokeball called, hit={hit}");
        PokemonSpawner spawner = FindFirstObjectByType<PokemonSpawner>();
        if (spawner == null || spawner.CurrentWildPokemon == null)
        {
            Debug.Log("[Catch] ThrowPokeball aborted — no spawner or wild pokemon");
            yield break;
        }

        Vector3 startPos = Camera.main.transform.position + Camera.main.transform.forward * 0.5f;
        Vector3 targetPos;

        if (hit)
        {
            targetPos = spawner.CurrentWildPokemon.transform.position;
        }
        else
        {
            // Miss: throw toward screen center world projection but offset past the Pokemon
            Ray ray = Camera.main.ScreenPointToRay(new Vector3(Screen.width / 2f, Screen.height / 2f, 0));
            targetPos = ray.GetPoint(5f);
        }

        // Spawn pokeball
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

        // Animate throw arc
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

        if (hit)
        {
            yield return StartCoroutine(CatchSequence(spawner));
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

        OnCatchResult?.Invoke(false, FindFirstObjectByType<PokemonSpawner>()?.CurrentPokemonData?.pokemonName ?? "???");
        GameStateManager.Instance.TransitionTo(GamePhase.CatchResult);

        yield return new WaitForSeconds(2f);

        GameStateManager.Instance.TransitionTo(GamePhase.Encounter);
    }

    private IEnumerator CatchSequence(PokemonSpawner spawner)
    {
        Vector3 targetPos = spawner.CurrentWildPokemon.transform.position;

        // Pokeball hit - hide wild Pokemon
        spawner.CurrentWildPokemon.SetActive(false);

        // Spawn smoke VFX
        if (smokeVFX != null)
            Instantiate(smokeVFX, targetPos, Quaternion.identity);

        // Pokeball lands at target
        activePokeball.transform.position = new Vector3(targetPos.x, targetPos.y - 0.5f, targetPos.z);

        // Calculate catch success via jiggle sequence
        float catchRate = spawner.CurrentPokemonData.baseCatchRate;
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

            OnCatchResult?.Invoke(true, spawner.CurrentPokemonData.pokemonName);

            yield return new WaitForSeconds(2f);
            Destroy(activePokeball);
            GameStateManager.Instance.TransitionTo(GamePhase.CatchResult);

            yield return new WaitForSeconds(3f);
            GameStateManager.Instance.TransitionTo(GamePhase.Idle);
        }
        else
        {
            OnCatchResult?.Invoke(false, spawner.CurrentPokemonData.pokemonName);

            Destroy(activePokeball);
            spawner.CurrentWildPokemon.SetActive(true);

            Animator wildAnim = spawner.CurrentWildPokemon.GetComponent<Animator>();
            if (wildAnim != null)
                wildAnim.SetTrigger("breakFree");

            GameStateManager.Instance.TransitionTo(GamePhase.CatchResult);

            yield return new WaitForSeconds(2f);
            GameStateManager.Instance.TransitionTo(GamePhase.Encounter);
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
