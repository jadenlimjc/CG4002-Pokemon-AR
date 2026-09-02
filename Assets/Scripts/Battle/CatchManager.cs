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
        if (action == GestureAction.POKEBALL_THROW &&
            GameStateManager.Instance.CurrentPhase == GamePhase.Encounter)
        {
            if (isAiming)
                HideReticle();
            GameStateManager.Instance.TransitionTo(GamePhase.BattleEntry);
            return;
        }

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
        PokemonSpawner spawner = FindObjectOfType<PokemonSpawner>();
        if (spawner == null || spawner.CurrentWildPokemon == null) return false;

        Vector3 screenPos = Camera.main.WorldToScreenPoint(
            spawner.CurrentWildPokemon.transform.position);

        if (screenPos.z <= 0) return false;

        Vector2 screenCenter = new Vector2(Screen.width / 2f, Screen.height / 2f);
        float distance = Vector2.Distance(
            screenCenter,
            new Vector2(screenPos.x, screenPos.y));

        return distance <= reticleRadius;
    }

    private IEnumerator ThrowPokeball(bool hit)
    {
        PokemonSpawner spawner = FindObjectOfType<PokemonSpawner>();
        if (spawner == null || spawner.CurrentWildPokemon == null) yield break;

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
        // Fizzle out
        if (fizzleVFX != null)
            Instantiate(fizzleVFX, activePokeball.transform.position, Quaternion.identity);

        Destroy(activePokeball);
        activePokeball = null;

        yield return new WaitForSeconds(1f);

        // Return to encounter - Pokemon is still there
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
